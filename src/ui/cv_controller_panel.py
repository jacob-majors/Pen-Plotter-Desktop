from __future__ import annotations
import cv2
import math
import threading
import numpy as np

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QProgressBar, QButtonGroup,
)
from PySide6.QtCore import Qt, QRectF, QTimer, Signal
from PySide6.QtGui import (
    QPainter, QPen, QColor, QBrush, QImage, QPixmap,
    QFont, QPainterPath,
)

from cv_controller.core.tracker import FaceTracker
from cv_controller.core.hand_tracker import HandTracker

HAND_CONNECTIONS = [
    (0, 1), (1, 2), (2, 3), (3, 4),
    (0, 5), (5, 6), (6, 7), (7, 8),
    (0, 9), (9, 10), (10, 11), (11, 12),
    (0, 13), (13, 14), (14, 15), (15, 16),
    (0, 17), (17, 18), (18, 19), (19, 20),
    (5, 9), (9, 13), (13, 17),
]

OVERLAY_BG = QColor("#18181b")
CAM_W, CAM_H = 220, 165   # overlay size — slightly smaller to avoid clipping


# ── Camera overlay with rounded corners ───────────────────────────────────────

class CamOverlay(QWidget):
    RADIUS = 14

    def __init__(self, parent):
        super().__init__(parent)
        self._pixmap: QPixmap | None = None
        self._face_lms: list | None = None
        self._hand_data: dict | None = None
        self.setAttribute(Qt.WA_OpaquePaintEvent)

    def set_frame(self, frame: np.ndarray | None):
        if frame is None:
            self._pixmap = None
        else:
            # Scale DOWN to display size in OpenCV before touching Qt —
            # processes 220×165 px instead of 640×480 px, eliminates paint-time scaling
            small = cv2.resize(frame, (CAM_W, CAM_H), interpolation=cv2.INTER_LINEAR)
            rgb = cv2.cvtColor(small, cv2.COLOR_BGR2RGB)
            self._pixmap = QPixmap.fromImage(
                QImage(rgb.tobytes(), CAM_W, CAM_H, CAM_W * 3, QImage.Format_RGB888)
            )
        self.update()

    def set_face_landmarks(self, lms: list):
        self._face_lms = lms
        self._hand_data = None
        self.update()

    def set_hand_landmarks(self, data: dict):
        self._hand_data = data
        self._face_lms = None
        self.update()

    def clear_landmarks(self):
        self._face_lms = None
        self._hand_data = None
        self.update()

    def paintEvent(self, _e):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        w, h = self.width(), self.height()
        r = self.RADIUS

        painter.fillRect(0, 0, w, h, OVERLAY_BG)

        clip = QPainterPath()
        clip.addRoundedRect(QRectF(0, 0, w, h), r, r)
        painter.setClipPath(clip)

        if self._pixmap:
            # Pixmap is already pre-scaled to (w, h) — draw directly, no runtime scaling
            painter.drawPixmap(0, 0, self._pixmap)

            if self._face_lms:
                painter.setPen(Qt.NoPen)
                painter.setBrush(QBrush(QColor(0, 230, 80, 200)))
                for nx, ny in self._face_lms:
                    painter.drawEllipse(int(nx * w) - 1, int(ny * h) - 1, 2, 2)

            if self._hand_data:
                lms = self._hand_data["landmarks"]
                pinch = self._hand_data.get("pinch", False)
                bone = QColor(255, 80, 60, 220) if pinch else QColor(40, 200, 255, 220)
                painter.setPen(QPen(bone, 1.5))
                painter.setBrush(Qt.NoBrush)
                for a, b in HAND_CONNECTIONS:
                    if a < len(lms) and b < len(lms):
                        painter.drawLine(int(lms[a][0]*w), int(lms[a][1]*h),
                                         int(lms[b][0]*w), int(lms[b][1]*h))
                painter.setPen(Qt.NoPen)
                painter.setBrush(QBrush(QColor(255, 255, 255, 230)))
                for nx, ny in lms:
                    painter.drawEllipse(int(nx*w) - 3, int(ny*h) - 3, 6, 6)
        else:
            painter.fillRect(0, 0, w, h, QColor("#09090b"))
            painter.setPen(QColor("#52525b"))
            painter.setFont(QFont("Arial", 10))
            painter.drawText(QRectF(0, 0, w, h), Qt.AlignCenter, "No feed")

        painter.setClipping(False)
        painter.setPen(QPen(QColor(255, 255, 255, 40), 1.5))
        painter.setBrush(Qt.NoBrush)
        painter.drawRoundedRect(QRectF(0.75, 0.75, w - 1.5, h - 1.5), r, r)


# ── Tracking canvas ────────────────────────────────────────────────────────────

class TrackingCanvas(QWidget):
    PAD = 20
    PLOT_INTERVAL_MS = 80     # G-code send rate in live-plot mode
    PLOT_MIN_DIST_MM  = 0.8   # don't send if movement < this (mm)

    def __init__(self, plotter=None):
        super().__init__()
        self.setMinimumSize(500, 400)

        self._plotter = plotter
        self._realtime = False          # live-plot mode flag

        self._cx: float = 0.5
        self._cy: float = 0.5
        self.pen_down: bool = False
        self._strokes: list[list[tuple[float, float]]] = []
        self._current: list[tuple[float, float]] = []

        self._bg_cache: QPixmap | None = None
        self._strokes_cache: QPixmap | None = None
        self._last_plot: tuple[float, float] = (0.0, 0.0)
        self._plotting_in_progress = False

        # Throttled plotter update
        self._plot_timer = QTimer(self)
        self._plot_timer.setInterval(self.PLOT_INTERVAL_MS)
        self._plot_timer.timeout.connect(self._flush_plot)

        self._cam = CamOverlay(self)
        self._cam.setFixedSize(CAM_W, CAM_H)

    # ── show / resize — fixes cam position ────────────────────────────────────

    def showEvent(self, event):
        super().showEvent(event)
        # Defer by one event-loop tick so the layout has settled
        QTimer.singleShot(0, self._reposition_cam)

    def resizeEvent(self, _e):
        super().resizeEvent(_e)
        self._bg_cache = None
        self._strokes_cache = None
        self._reposition_cam()

    def _reposition_cam(self):
        w, h = self.width(), self.height()
        if w <= 0 or h <= 0:
            return
        margin = 14
        # Pin to TOP-RIGHT — always fully visible regardless of window/monitor height
        x = max(0, w - CAM_W - margin)
        y = margin
        self._cam.move(x, y)
        self._cam.raise_()

    # ── cursor / pen ──────────────────────────────────────────────────────────

    def set_realtime(self, enabled: bool):
        self._realtime = enabled
        if not enabled:
            self._plot_timer.stop()

    def move_cursor(self, dx: int, dy: int):
        pw, ph = self._paper_size()
        self._cx = max(0.0, min(1.0, self._cx + dx / pw))
        self._cy = max(0.0, min(1.0, self._cy + dy / ph))
        if self.pen_down:
            self._current.append((self._cx, self._cy))
        self.update()

    def set_cursor(self, nx: float, ny: float):
        self._cx = max(0.0, min(1.0, float(nx)))
        self._cy = max(0.0, min(1.0, float(ny)))
        if self.pen_down:
            self._current.append((self._cx, self._cy))
        self.update()

    def toggle_pen(self):
        self._lift_pen() if self.pen_down else self._lower_pen()

    def _lower_pen(self):
        self.pen_down = True
        self._current = [(self._cx, self._cy)]
        if self._realtime and self._plotter:
            threading.Thread(target=self._plotter.pen_down, daemon=True).start()
            # Reset distance tracker so next flush sends immediately
            self._last_plot = self._cursor_mm()
            self._plot_timer.start()
        self.update()

    def _lift_pen(self):
        self.pen_down = False
        if len(self._current) > 1:
            self._strokes.append(list(self._current))
            self._strokes_cache = None  # new stroke added — invalidate
        self._current = []
        if self._realtime and self._plotter:
            self._plot_timer.stop()
            threading.Thread(target=self._plotter.pen_up, daemon=True).start()
        self.update()

    def clear(self):
        self._strokes.clear()
        self._current.clear()
        self.pen_down = False
        self._strokes_cache = None
        self.update()

    def update_cam(self, frame: np.ndarray | None):
        self._cam.set_frame(frame)

    # ── live-plot helpers ─────────────────────────────────────────────────────

    def _cursor_mm(self) -> tuple[float, float]:
        if not self._plotter:
            return (self._cx * 220.0, (1 - self._cy) * 220.0)
        s = self._plotter.settings
        return (self._cx * s["x_max"], (1 - self._cy) * s["y_max"])

    def _flush_plot(self):
        if not self._realtime or not self._plotter or not self._plotter.connected:
            return
        if not self.pen_down:
            return
        x_mm, y_mm = self._cursor_mm()
        dist = math.hypot(x_mm - self._last_plot[0], y_mm - self._last_plot[1])
        if dist < self.PLOT_MIN_DIST_MM:
            return
        self._last_plot = (x_mm, y_mm)
        feed = self._plotter.settings.get("feed_draw", 1500)
        
        if self._plotting_in_progress:
            return

        def _do_plot():
            self._plotting_in_progress = True
            try:
                self._plotter.move_to(x_mm, y_mm, feed)
            finally:
                self._plotting_in_progress = False

        threading.Thread(target=_do_plot, daemon=True).start()

    def plot_canvas(self):
        """Send all drawn strokes to the plotter (Design → Plot flow)."""
        if not self._plotter or not self._plotter.connected:
            return
        paths = self._strokes_to_mm()
        threading.Thread(target=self._send_paths, args=(paths,), daemon=True).start()

    def _strokes_to_mm(self) -> list[list[tuple[float, float]]]:
        if not self._plotter:
            return []
        s = self._plotter.settings
        result = []
        for stroke in self._strokes:
            if len(stroke) >= 2:
                result.append([(nx * s["x_max"], (1 - ny) * s["y_max"])
                               for nx, ny in stroke])
        return result

    def _send_paths(self, paths: list):
        if not self._plotter:
            return
        for path in paths:
            if not path:
                continue
            self._plotter.pen_up()
            self._plotter.move_to(path[0][0], path[0][1])
            self._plotter.pen_down()
            for x, y in path[1:]:
                self._plotter.move_to(x, y, self._plotter.settings.get("feed_draw", 1500))
        self._plotter.pen_up()

    # ── geometry ──────────────────────────────────────────────────────────────

    def _paper_rect(self) -> QRectF:
        p = self.PAD
        return QRectF(p, p, self.width() - p * 2, self.height() - p * 2)

    def _paper_size(self) -> tuple[float, float]:
        r = self._paper_rect()
        return r.width(), r.height()

    def _to_px(self, nx: float, ny: float) -> tuple[int, int]:
        r = self._paper_rect()
        return int(r.x() + nx * r.width()), int(r.y() + ny * r.height())

    # ── background cache ──────────────────────────────────────────────────────

    def _get_bg(self) -> QPixmap:
        if self._bg_cache is None:
            self._bg_cache = self._render_bg()
        return self._bg_cache

    def _render_bg(self) -> QPixmap:
        w, h = self.width(), self.height()
        if w <= 0 or h <= 0:
            return QPixmap(1, 1)
        pix = QPixmap(w, h)
        pix.fill(OVERLAY_BG)
        pr = self._paper_rect()
        p = QPainter(pix)
        p.setRenderHint(QPainter.Antialiasing)
        for i in range(10, 0, -1):
            alpha = int(90 * (1 - i / 10))
            p.setBrush(QColor(0, 0, 0, alpha))
            p.setPen(Qt.NoPen)
            p.drawRoundedRect(
                QRectF(pr.x() + i * .5, pr.y() + i * .7, pr.width(), pr.height()), 4, 4)
        p.setBrush(QColor("#fafaf8"))
        p.setPen(Qt.NoPen)
        p.drawRoundedRect(pr, 4, 4)
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(QColor("#dce1e8")))
        sp = 28
        ox, oy = int(pr.x()), int(pr.y())
        for gx in range(ox + sp, ox + int(pr.width()), sp):
            for gy in range(oy + sp, oy + int(pr.height()), sp):
                p.drawEllipse(gx - 1, gy - 1, 2, 2)
        p.end()
        return pix

    # ── strokes cache ─────────────────────────────────────────────────────────

    def _render_strokes(self) -> QPixmap:
        w, h = self.width(), self.height()
        pix = QPixmap(w, h)
        pix.fill(Qt.transparent)
        pr = self._paper_rect()
        p = QPainter(pix)
        p.setRenderHint(QPainter.Antialiasing)
        clip = QPainterPath()
        clip.addRoundedRect(pr, 4, 4)
        p.setClipPath(clip)
        p.setPen(QPen(QColor("#1e293b"), 2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.setBrush(Qt.NoBrush)
        for stroke in self._strokes:
            self._paint_stroke(p, stroke)
        p.end()
        return pix

    # ── paint ─────────────────────────────────────────────────────────────────

    def paintEvent(self, _e):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        pr = self._paper_rect()

        painter.drawPixmap(0, 0, self._get_bg())

        # Completed strokes — drawn once and cached
        if self._strokes:
            if self._strokes_cache is None:
                self._strokes_cache = self._render_strokes()
            painter.drawPixmap(0, 0, self._strokes_cache)

        # Live (in-progress) stroke only
        if self._current:
            clip = QPainterPath()
            clip.addRoundedRect(pr, 4, 4)
            painter.setClipPath(clip)
            live_col = QColor("#ef4444") if self._realtime else QColor("#3b82f6")
            painter.setPen(QPen(live_col, 2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            painter.setBrush(Qt.NoBrush)
            self._paint_stroke(painter, self._current)

        painter.setClipping(False)

        # Cursor crosshair
        cx, cy = self._to_px(self._cx, self._cy)
        cur_col = QColor("#ef4444") if self.pen_down else QColor("#475569")
        gap, arm, dot = 6, 14, 3
        painter.setPen(QPen(cur_col, 1.5))
        painter.setBrush(Qt.NoBrush)
        painter.drawLine(cx + gap, cy, cx + arm, cy)
        painter.drawLine(cx - arm, cy, cx - gap, cy)
        painter.drawLine(cx, cy + gap, cx, cy + arm)
        painter.drawLine(cx, cy - arm, cx, cy - gap)
        painter.setBrush(QBrush(cur_col))
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(cx - dot, cy - dot, dot * 2, dot * 2)

        # Top-left pills: pen state + mode
        def _pill(x, y, w, h, col, text):
            painter.setBrush(QBrush(col))
            painter.setPen(Qt.NoPen)
            painter.drawRoundedRect(x, y, w, h, h / 2, h / 2)
            painter.setPen(QPen(QColor("white")))
            painter.setFont(QFont("Arial", 9, QFont.Bold))
            painter.drawText(x, y, w, h, Qt.AlignCenter, text)

        ox = int(pr.x()) + 10
        oy = int(pr.y()) + 10
        pen_col = QColor("#ef4444") if self.pen_down else QColor("#334155")
        _pill(ox, oy, 90, 22, pen_col, "● PEN DOWN" if self.pen_down else "○ PEN UP")
        if self._realtime:
            _pill(ox + 100, oy, 90, 22, QColor("#7c3aed"), "⚡ LIVE PLOT")

    def _paint_stroke(self, painter: QPainter, stroke: list):
        for i in range(1, len(stroke)):
            x1, y1 = self._to_px(*stroke[i - 1])
            x2, y2 = self._to_px(*stroke[i])
            painter.drawLine(x1, y1, x2, y2)


# ── Panel ──────────────────────────────────────────────────────────────────────

class CvControllerPanel(QWidget):
    strokes_sent = Signal(list)   # emitted when user clicks "→ Draw"

    def __init__(self, plotter=None):
        super().__init__()
        self._plotter = plotter

        self._face = FaceTracker()
        self._hand = HandTracker()
        self._active_tracker = None

        self._canvas = TrackingCanvas(plotter)

        self._face.frame_ready.connect(self._canvas.update_cam)
        self._face.status_changed.connect(self._on_status)
        self._face.download_progress.connect(self._on_progress)
        self._face.head_delta.connect(self._canvas.move_cursor)
        self._face.gesture_fired.connect(self._on_face_gesture)
        self._face.face_landmarks.connect(self._canvas._cam.set_face_landmarks)

        self._hand.frame_ready.connect(self._canvas.update_cam)
        self._hand.status_changed.connect(self._on_status)
        self._hand.download_progress.connect(self._on_progress)
        self._hand.hand_position.connect(self._canvas.set_cursor)
        self._hand.gesture_fired.connect(self._on_hand_gesture)
        self._hand.hand_landmarks.connect(self._canvas._cam.set_hand_landmarks)

        self._build_ui()

        # Refresh plotter status in toolbar every second
        self._status_timer = QTimer(self)
        self._status_timer.setInterval(1000)
        self._status_timer.timeout.connect(self._refresh_plotter_status)
        self._status_timer.start()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        toolbar = QWidget()
        toolbar.setFixedHeight(48)
        toolbar.setStyleSheet("background:#1e1e1e;border-bottom:1px solid #2d2d2d;")
        tlay = QHBoxLayout(toolbar)
        tlay.setContentsMargins(14, 0, 14, 0)
        tlay.setSpacing(8)

        # Input mode
        mode_group = QButtonGroup(self)
        self._btn_face = QPushButton("Face")
        self._btn_face.setCheckable(True)
        self._btn_face.setChecked(True)
        self._btn_face.setFixedWidth(60)
        self._btn_hand = QPushButton("Hand")
        self._btn_hand.setCheckable(True)
        self._btn_hand.setFixedWidth(60)
        for b in (self._btn_face, self._btn_hand):
            b.setStyleSheet(
                "QPushButton{border:1px solid #444;border-radius:4px;padding:4px 6px;}"
                "QPushButton:checked{background:#3b82f6;color:white;border-color:#3b82f6;}"
            )
            mode_group.addButton(b)
        self._btn_face.clicked.connect(self._select_face)
        self._btn_hand.clicked.connect(self._select_hand)

        tlay.addWidget(QLabel("Input:"))
        tlay.addWidget(self._btn_face)
        tlay.addWidget(self._btn_hand)
        tlay.addWidget(self._vsep())

        # Start / stop
        self._btn_start = QPushButton("▶  Start")
        self._btn_start.setFixedWidth(110)
        self._btn_start.setStyleSheet(
            "background:#166534;color:white;font-weight:bold;border-radius:4px;padding:5px 10px;"
        )
        self._btn_start.clicked.connect(self._toggle_tracking)
        tlay.addWidget(self._btn_start)

        self._dl_bar = QProgressBar()
        self._dl_bar.setVisible(False)
        self._dl_bar.setFixedWidth(160)
        self._dl_bar.setFormat("Downloading: %p%")
        tlay.addWidget(self._dl_bar)

        tlay.addWidget(self._vsep())

        # Drawing mode: Design vs Live Plot
        draw_group = QButtonGroup(self)
        self._btn_design = QPushButton("Design")
        self._btn_design.setCheckable(True)
        self._btn_design.setChecked(True)
        self._btn_design.setFixedWidth(76)
        self._btn_live = QPushButton("⚡ Live Plot")
        self._btn_live.setCheckable(True)
        self._btn_live.setFixedWidth(90)
        for b in (self._btn_design, self._btn_live):
            b.setStyleSheet(
                "QPushButton{border:1px solid #444;border-radius:4px;padding:4px 6px;}"
                "QPushButton:checked{background:#7c3aed;color:white;border-color:#7c3aed;}"
            )
            draw_group.addButton(b)
        self._btn_design.clicked.connect(lambda: self._set_draw_mode(False))
        self._btn_live.clicked.connect(lambda: self._set_draw_mode(True))
        tlay.addWidget(self._btn_design)
        tlay.addWidget(self._btn_live)

        # Plotter status dot
        self._plotter_dot = QLabel("●")
        self._plotter_dot.setStyleSheet("color:#374151;font-size:14px;padding:0 4px;")
        self._plotter_dot.setToolTip("Plotter not connected")
        tlay.addWidget(self._plotter_dot)

        tlay.addStretch()

        self._hint = QLabel("Blink to toggle pen  ·  Head direction moves cursor")
        self._hint.setStyleSheet("color:#52525b;font-size:11px;")
        tlay.addWidget(self._hint)

        tlay.addWidget(self._vsep())

        btn_plot = QPushButton("Plot Canvas")
        btn_plot.setStyleSheet(
            "QPushButton{background:#1e3a8a;color:#93c5fd;border:1px solid #1e40af;"
            "border-radius:4px;padding:5px 12px;font-weight:bold;}"
            "QPushButton:hover{background:#1e40af;}"
        )
        btn_plot.setToolTip("Send all drawn strokes to the plotter")
        btn_plot.clicked.connect(self._canvas.plot_canvas)
        tlay.addWidget(btn_plot)

        btn_clear = QPushButton("Clear")
        btn_clear.setStyleSheet(
            "QPushButton{border:1px solid #444;border-radius:4px;padding:5px 10px;}"
            "QPushButton:hover{background:#2d2d2d;}"
        )
        btn_clear.clicked.connect(self._canvas.clear)
        tlay.addWidget(btn_clear)

        btn_send = QPushButton("→ Draw")
        btn_send.setToolTip("Copy current strokes to the Draw tab")
        btn_send.setStyleSheet(
            "QPushButton{border:1px solid #7c3aed;color:#a78bfa;border-radius:4px;padding:5px 10px;}"
            "QPushButton:hover{background:#4c1d95;color:white;}"
        )
        btn_send.clicked.connect(self._send_to_draw)
        tlay.addWidget(btn_send)

        self._status = QLabel("Idle")
        self._status.setStyleSheet("color:#71717a;font-size:11px;padding-left:6px;")
        tlay.addWidget(self._status)

        root.addWidget(toolbar)
        root.addWidget(self._canvas, stretch=1)

    @staticmethod
    def _vsep() -> QWidget:
        f = QWidget()
        f.setFixedWidth(1)
        f.setStyleSheet("background:#333;")
        return f

    # ── draw mode ─────────────────────────────────────────────────────────────

    def _set_draw_mode(self, live: bool):
        if live and self._plotter and not self._plotter.connected:
            # Don't allow live mode without a connected plotter
            self._btn_design.setChecked(True)
            self._btn_live.setChecked(False)
            self._on_status("Connect the plotter first to use Live Plot mode")
            return
        self._canvas.set_realtime(live)
        if live:
            self._hint.setText("Blink = pen up/down  ·  Movement plots in real-time to plotter")
        else:
            if self._btn_face.isChecked():
                self._hint.setText("Blink to toggle pen  ·  Head direction moves cursor")
            else:
                self._hint.setText("Pinch to toggle pen  ·  Move hand to move cursor")

    def _refresh_plotter_status(self):
        if self._plotter and self._plotter.connected:
            self._plotter_dot.setStyleSheet("color:#4ade80;font-size:14px;padding:0 4px;")
            self._plotter_dot.setToolTip(
                f"Plotter connected — "
                f"X:{self._plotter.position['x']:.1f} "
                f"Y:{self._plotter.position['y']:.1f}"
            )
        else:
            self._plotter_dot.setStyleSheet("color:#374151;font-size:14px;padding:0 4px;")
            self._plotter_dot.setToolTip("Plotter not connected")
            # If plotter disconnects while in live mode, fall back to design
            if self._canvas._realtime:
                self._btn_design.setChecked(True)
                self._btn_live.setChecked(False)
                self._canvas.set_realtime(False)

    # ── input mode ────────────────────────────────────────────────────────────

    def _select_face(self):
        if self._active_tracker is self._face:
            return
        self._stop_active()
        self._canvas._cam.clear_landmarks()
        self._hint.setText("Blink to toggle pen  ·  Head direction moves cursor")

    def _select_hand(self):
        if self._active_tracker is self._hand:
            return
        self._stop_active()
        self._canvas._cam.clear_landmarks()
        self._hint.setText("Pinch to toggle pen  ·  Move hand to move cursor")

    def _stop_active(self):
        if self._active_tracker:
            self._active_tracker.stop()
            self._active_tracker = None
        self._btn_start.setText("▶  Start")
        self._btn_start.setStyleSheet(
            "background:#166534;color:white;font-weight:bold;border-radius:4px;padding:5px 10px;"
        )

    def _toggle_tracking(self):
        if self._active_tracker and self._active_tracker._running:
            self._stop_active()
            return
        tracker = self._face if self._btn_face.isChecked() else self._hand
        tracker.start()
        if tracker._running or tracker.model_ready():
            self._active_tracker = tracker
            self._btn_start.setText("■  Stop")
            self._btn_start.setStyleSheet(
                "background:#7f1d1d;color:white;font-weight:bold;border-radius:4px;padding:5px 10px;"
            )

    # ── gesture slots ─────────────────────────────────────────────────────────

    def _on_face_gesture(self, gesture: str):
        if gesture in ("eyeBlinkLeft", "eyeBlinkRight"):
            self._canvas.toggle_pen()

    def _on_hand_gesture(self, gesture: str):
        if gesture == "pinch_down":
            self._canvas._lower_pen()
        elif gesture == "pinch_up":
            self._canvas._lift_pen()

    def _on_status(self, msg: str):
        self._status.setText(msg)
        if "ownload" in msg:
            self._dl_bar.setVisible(True)

    def _on_progress(self, pct: int):
        self._dl_bar.setValue(pct)
        if pct >= 100:
            self._dl_bar.setVisible(False)

    def _send_to_draw(self):
        """Emit all drawn strokes so the app can add them to the Draw tab."""
        strokes = list(self._canvas._strokes)
        if strokes:
            self.strokes_sent.emit(strokes)
