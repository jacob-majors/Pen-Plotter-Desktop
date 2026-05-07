from __future__ import annotations
import math

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QListWidget, QListWidgetItem, QFrame,
)
from PySide6.QtCore import Qt, QRectF, QSize
from PySide6.QtGui import (
    QPainter, QPen, QColor, QBrush, QPixmap, QPainterPath, QFont,
)

from core.presets import (
    generate_spirograph, generate_fractal_star, generate_shaded_sphere,
    generate_rose_curve, generate_golden_spiral, generate_hilbert_curve,
    generate_lissajous, generate_sierpinski, generate_dragon_curve,
    generate_phyllotaxis,
)

BG = QColor("#18181b")
PAPER = QColor("#fafaf8")
GRID = QColor("#dce1e8")
STROKE = QColor("#1e293b")
TRAVEL = QColor("#e2e8f0")
PAD = 24

PRESETS = [
    ("Spirograph",     "⊙",  "#6366f1", generate_spirograph),
    ("Fractal Star",   "✦",  "#f59e0b", generate_fractal_star),
    ("Shaded Sphere",  "◑",  "#64748b", lambda: generate_shaded_sphere(use_pencil=True)),
    ("Rose Curve",     "❀",  "#ec4899", generate_rose_curve),
    ("Golden Spiral",  "𝜑",  "#f97316", generate_golden_spiral),
    ("Hilbert Curve",  "⊞",  "#0ea5e9", generate_hilbert_curve),
    ("Lissajous",      "∞",  "#8b5cf6", generate_lissajous),
    ("Sierpiński",     "△",  "#10b981", generate_sierpinski),
    ("Dragon Curve",   "↯",  "#ef4444", generate_dragon_curve),
    ("Phyllotaxis",    "✿",  "#84cc16", generate_phyllotaxis),
]


# ── Canvas ────────────────────────────────────────────────────────────────────

class PatternCanvas(QWidget):
    def __init__(self, plotter):
        super().__init__()
        self.plotter = plotter
        self.setMinimumSize(400, 400)
        self.paths: list = []
        self._bg: QPixmap | None = None

    def load_paths(self, paths: list):
        self.paths = paths
        self.update()

    def resizeEvent(self, _e):
        super().resizeEvent(_e)
        self._bg = None

    def _paper_rect(self) -> QRectF:
        return QRectF(PAD, PAD, self.width() - PAD * 2, self.height() - PAD * 2)

    def _get_bg(self) -> QPixmap:
        if self._bg is None:
            self._bg = self._render_bg()
        return self._bg

    def _render_bg(self) -> QPixmap:
        w, h = self.width(), self.height()
        if w <= 0 or h <= 0:
            return QPixmap(1, 1)
        pix = QPixmap(w, h)
        pix.fill(BG)
        pr = self._paper_rect()
        p = QPainter(pix)
        p.setRenderHint(QPainter.Antialiasing)
        for i in range(10, 0, -1):
            alpha = int(90 * (1 - i / 10))
            p.setBrush(QColor(0, 0, 0, alpha))
            p.setPen(Qt.NoPen)
            p.drawRoundedRect(
                QRectF(pr.x() + i * .5, pr.y() + i * .7, pr.width(), pr.height()), 4, 4
            )
        p.setBrush(PAPER)
        p.setPen(Qt.NoPen)
        p.drawRoundedRect(pr, 4, 4)
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(GRID))
        sp = 28
        ox, oy = int(pr.x()), int(pr.y())
        for gx in range(ox + sp, ox + int(pr.width()), sp):
            for gy in range(oy + sp, oy + int(pr.height()), sp):
                p.drawEllipse(gx - 1, gy - 1, 2, 2)
        p.end()
        return pix

    def paintEvent(self, _e):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        pr = self._paper_rect()

        painter.drawPixmap(0, 0, self._get_bg())

        # ── Draw Soft Limits ──────────────────────────────────────────────────
        s = self.plotter.settings
        if s.get("soft_limits", True):
            BED = 220.0
            lx, rx = s["x_min"] / BED, s["x_max"] / BED
            ty, by = s["y_min"] / BED, s["y_max"] / BED
            
            px, py = int(pr.x() + lx * pr.width()), int(pr.y() + (1 - by) * pr.height())
            pw = int((rx - lx) * pr.width())
            ph = int((by - ty) * pr.height())
            
            limit_pen = QPen(QColor("#3b82f6"), 1, Qt.DashLine)
            painter.setPen(limit_pen)
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(px, py, pw, ph)
            
            painter.setFont(QFont("Inter", 8))
            painter.drawText(px + 4, py + ph - 4, "SOFT LIMITS ACTIVE")

        if not self.paths:
            return

        clip = QPainterPath()
        clip.addRoundedRect(pr, 4, 4)
        painter.setClipPath(clip)

        BED = 220.0
        sx = pr.width() / BED
        sy = pr.height() / BED

        ink = QPen(STROKE, 1, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
        trav = QPen(TRAVEL, 0.5, Qt.DashLine)
        dot_on = QBrush(QColor("#10b981"))
        dot_off = QBrush(QColor("#ef4444"))

        last = None
        for path in self.paths:
            if not path:
                continue
            x0 = int(pr.x() + path[0][0] * sx)
            y0 = int(pr.y() + (BED - path[0][1]) * sy)

            if last:
                painter.setPen(trav)
                painter.setBrush(Qt.NoBrush)
                painter.drawLine(last[0], last[1], x0, y0)

            painter.setPen(Qt.NoPen)
            painter.setBrush(dot_on)
            painter.drawEllipse(x0 - 3, y0 - 3, 6, 6)

            painter.setPen(ink)
            painter.setBrush(Qt.NoBrush)
            for i in range(1, len(path)):
                x1 = int(pr.x() + path[i-1][0] * sx)
                y1 = int(pr.y() + (BED - path[i-1][1]) * sy)
                x2 = int(pr.x() + path[i][0] * sx)
                y2 = int(pr.y() + (BED - path[i][1]) * sy)
                painter.drawLine(x1, y1, x2, y2)

            xe = int(pr.x() + path[-1][0] * sx)
            ye = int(pr.y() + (BED - path[-1][1]) * sy)
            painter.setPen(Qt.NoPen)
            painter.setBrush(dot_off)
            painter.drawEllipse(xe - 3, ye - 3, 6, 6)
            last = (xe, ye)


# ── Panel ─────────────────────────────────────────────────────────────────────

class PresetPanel(QWidget):
    def __init__(self, plotter):
        super().__init__()
        self.plotter = plotter
        self._paths: list = []
        self._build_ui()
        self._select(0)

    def _build_ui(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── left sidebar ──────────────────────────────────────────────────────
        sidebar = QFrame()
        sidebar.setFixedWidth(220)
        sidebar.setStyleSheet("background: #1e293b; border-right: 1px solid #334155;")
        sl = QVBoxLayout(sidebar)
        sl.setContentsMargins(0, 0, 0, 0)
        sl.setSpacing(0)

        hdr = QLabel("  PATTERNS")
        hdr.setFixedHeight(40)
        hdr.setStyleSheet(
            "font-size:10px;font-weight:800;color:#94a3b8;letter-spacing:2px;"
            "border-bottom:1px solid #334155;padding-left:12px;background: #0f172a;"
        )
        sl.addWidget(hdr)

        self._list = QListWidget()
        self._list.setStyleSheet("""
            QListWidget { background:transparent; border:none; outline:none; }
            QListWidget::item { padding:0px; border-bottom:1px solid #334155; }
            QListWidget::item:selected { background:#334155; border-left:3px solid #3b82f6; }
            QListWidget::item:hover:!selected { background:#1e293b; }
        """)
        for name, icon, color, _ in PRESETS:
            item = QListWidgetItem()
            item.setSizeHint(QSize(220, 52))
            self._list.addItem(item)
            self._list.setItemWidget(item, self._card(icon, name, color))

        self._list.currentRowChanged.connect(self._select)
        sl.addWidget(self._list)
        root.addWidget(sidebar)

        # ── canvas ────────────────────────────────────────────────────────────
        self._canvas = PatternCanvas(self.plotter)
        root.addWidget(self._canvas, stretch=1)

        # ── right sidebar ─────────────────────────────────────────────────────
        right = QFrame()
        right.setFixedWidth(200)
        right.setStyleSheet("background: #1e293b; border-left: 1px solid #334155;")
        rl = QVBoxLayout(right)
        rl.setContentsMargins(16, 16, 16, 16)
        rl.setSpacing(10)

        def section(text):
            lbl = QLabel(text)
            lbl.setStyleSheet("font-size:10px;font-weight:800;color:#94a3b8;letter-spacing:1px;")
            rl.addWidget(lbl)
            sep = QFrame()
            sep.setFrameShape(QFrame.HLine)
            sep.setFixedHeight(1)
            sep.setStyleSheet("background:#334155;")
            rl.addWidget(sep)

        section("OUTPUT")
        self._lbl_strokes = QLabel("Strokes\n—")
        self._lbl_distance = QLabel("Distance\n—")
        self._lbl_lifts = QLabel("Lifts\n—")
        for lbl in (self._lbl_strokes, self._lbl_distance, self._lbl_lifts):
            lbl.setStyleSheet("color:#d1d5db;font-size:12px;line-height:1.6;")
            rl.addWidget(lbl)

        rl.addSpacing(8)
        section("LEGEND")
        for hex_col, label in [("#10b981", "Pen down"), ("#ef4444", "Pen lift"),
                                ("#e2e8f0", "Travel move")]:
            row = QHBoxLayout()
            dot = QLabel()
            dot.setFixedSize(10, 10)
            dot.setStyleSheet(f"background:{hex_col};border-radius:5px;")
            row.addWidget(dot)
            row.addWidget(QLabel(label, styleSheet="color:#9ca3af;font-size:12px;"))
            row.addStretch()
            rl.addLayout(row)

        rl.addStretch()

        btn = QPushButton("▶  Plot Pattern")
        btn.setObjectName("btnPrimary")
        btn.setStyleSheet("padding: 10px 0; font-size: 13px;")
        btn.clicked.connect(self._plot)
        rl.addWidget(btn)

        root.addWidget(right)

    @staticmethod
    def _card(icon: str, name: str, color: str) -> QWidget:
        w = QWidget()
        w.setStyleSheet("background:transparent;")
        lay = QHBoxLayout(w)
        lay.setContentsMargins(12, 8, 12, 8)
        lay.setSpacing(10)
        dot = QLabel(icon)
        dot.setFixedSize(32, 32)
        dot.setAlignment(Qt.AlignCenter)
        dot.setStyleSheet(
            f"background:{color}22;border-radius:8px;color:{color};font-size:16px;"
        )
        lay.addWidget(dot)
        lbl = QLabel(name)
        lbl.setStyleSheet("color:#d1d5db;font-size:13px;background:transparent;")
        lay.addWidget(lbl)
        lay.addStretch()
        return w

    def _select(self, row: int):
        if row < 0 or row >= len(PRESETS):
            return
        self._paths = PRESETS[row][3]()
        self._canvas.load_paths(self._paths)
        strokes = len(self._paths)
        dist = sum(
            math.hypot(p[i][0]-p[i-1][0], p[i][1]-p[i-1][1])
            for p in self._paths for i in range(1, len(p))
        )
        self._lbl_strokes.setText(f"Strokes\n{strokes:,}")
        self._lbl_distance.setText(f"Distance\n{dist/1000:.2f} m")
        self._lbl_lifts.setText(f"Lifts\n{strokes:,}")

    def _plot(self):
        if not self.plotter.connected:
            return
        for path in self._paths:
            if not path:
                continue
            self.plotter.send_gcode("G90")
            self.plotter.send_gcode("G0 Z5")
            self.plotter.send_gcode(f"G0 X{path[0][0]:.2f} Y{path[0][1]:.2f} F3000")
            self.plotter.send_gcode("G0 Z-2")
            for pt in path[1:]:
                self.plotter.send_gcode(f"G1 X{pt[0]:.2f} Y{pt[1]:.2f} F1500")
        self.plotter.send_gcode("G0 Z5")
