"""
draw_panel.py — Unified Draw tab.

Layout (left → right):
  ToolColumn  (44 px)  — narrow icon-only column, Inkscape-style
  PatternsPanel(190 px) — pattern card list, old-preset-panel style
  DrawCanvas  (flex)   — drawing surface
  RightPanel  (190 px) — stats, plot progress, Plot button

Toolbar (top): Undo · Clear · Paper size · Save · Load · Import SVG

Keyboard:
  Ctrl+Z  undo           Enter     finish polyline
  Ctrl+S  save           Escape    cancel current shape
  Ctrl+O  load           Shift     constrain (45°/square/circle)
"""
from __future__ import annotations
import json
import math
import threading
from pathlib import Path

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QFrame, QListWidget, QListWidgetItem,
    QProgressBar, QFileDialog, QComboBox, QButtonGroup,
    QAbstractItemView, QSizePolicy,
)
from PySide6.QtCore import Qt, QRectF, QSize, QTimer, Signal
from PySide6.QtGui import (
    QPainter, QPen, QColor, QBrush, QPixmap, QIcon,
    QFont, QPainterPath, QKeySequence, QShortcut,
)

from core.presets import (
    generate_spirograph, generate_fractal_star, generate_shaded_sphere,
    generate_rose_curve, generate_golden_spiral, generate_hilbert_curve,
    generate_lissajous, generate_sierpinski, generate_dragon_curve,
    generate_phyllotaxis,
)
from core.svg_import import parse_svg

BG    = QColor("#18181b")
PAPER = QColor("#fafaf8")
GRID  = QColor("#dce1e8")
INK   = QColor("#1e293b")
LIVE  = QColor("#3b82f6")
PAD   = 24

TOOLS = [
    ("pen",     "Pen  — drag to draw freehand"),
    ("polyline","Polyline  — click points, dbl-click or Enter to finish"),
    ("rect",    "Rectangle  — drag, Shift = square"),
    ("ellipse", "Ellipse  — drag, Shift = circle"),
]

PRESETS = [
    ("Spirograph",    "⊙", "#6366f1", generate_spirograph),
    ("Fractal Star",  "✦", "#f59e0b", generate_fractal_star),
    ("Shaded Sphere", "◑", "#64748b", lambda: generate_shaded_sphere(use_pencil=True)),
    ("Rose Curve",    "❀", "#ec4899", generate_rose_curve),
    ("Golden Spiral", "φ",  "#f97316", generate_golden_spiral),
    ("Hilbert Curve", "H",  "#0ea5e9", generate_hilbert_curve),
    ("Lissajous",     "∞", "#8b5cf6", generate_lissajous),
    ("Sierpinski",    "△", "#10b981", generate_sierpinski),
    ("Dragon Curve",  "D",  "#ef4444", generate_dragon_curve),
    ("Phyllotaxis",   "✿", "#84cc16", generate_phyllotaxis),
]

PAPER_PRESETS = [
    ("220 × 220 mm",  220.0, 220.0),
    ("A4 portrait",   210.0, 297.0),
    ("A4 landscape",  297.0, 210.0),
    ("A5",            148.0, 210.0),
    ("Letter",        215.9, 279.4),
    ("Square 150 mm", 150.0, 150.0),
]


# ── icon painters ─────────────────────────────────────────────────────────────

def _tool_icon(tool: str, size: int = 22) -> QIcon:
    """Programmatically drawn vector icon for each tool."""
    pix = QPixmap(size, size)
    pix.fill(QColor(0, 0, 0, 0))
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing)
    c = QColor("#c0c8d4")
    pen = QPen(c, 1.5, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    m, s = 3, size

    if tool == "pen":
        path = QPainterPath()
        path.moveTo(m, s - m)
        path.cubicTo(m + 1, s * 0.4, s - m - 1, s * 0.6, s - m, m)
        p.drawPath(path)
        p.setBrush(QBrush(c))
        p.setPen(Qt.NoPen)
        p.drawEllipse(s - m - 2, m - 1, 3, 3)

    elif tool == "polyline":
        pts = [(m, s-m), (m+3, s//2-1), (s-m-3, s//2+2), (s-m, m)]
        for i in range(1, len(pts)):
            p.drawLine(pts[i-1][0], pts[i-1][1], pts[i][0], pts[i][1])
        p.setBrush(QBrush(c))
        p.setPen(Qt.NoPen)
        for x, y in pts:
            p.drawEllipse(x - 2, y - 2, 4, 4)

    elif tool == "rect":
        p.drawRect(m, m, s - m*2, s - m*2)

    elif tool == "ellipse":
        p.drawEllipse(m, m + 2, s - m*2, s - m*2 - 4)

    p.end()
    return QIcon(pix)


def _pattern_icon(char: str, color: str, size: int = 24) -> QIcon:
    pix = QPixmap(size, size)
    pix.fill(QColor(0, 0, 0, 0))
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing)
    bg = QColor(color)
    bg.setAlpha(38)
    p.setBrush(QBrush(bg))
    p.setPen(Qt.NoPen)
    p.drawRoundedRect(2, 2, size - 4, size - 4, 4, 4)
    p.setPen(QPen(QColor(color)))
    p.setFont(QFont("Arial", int(size * 0.5), QFont.Bold))
    p.drawText(QRectF(0, 0, size, size), Qt.AlignCenter, char)
    p.end()
    return QIcon(pix)


# ── narrow Inkscape-style tool column ─────────────────────────────────────────

_TOOL_BTN = """
    QPushButton {{
        border: none;
        border-radius: 6px;
        background: transparent;
        padding: 0;
    }}
    QPushButton:hover   {{ background: #2d2d2d; }}
    QPushButton:checked {{ background: #1e3a5f; border: 1px solid #3b82f6; }}
"""


class ToolColumn(QWidget):
    tool_changed = Signal(str)

    def __init__(self, canvas_undo, canvas_clear):
        super().__init__()
        self.setFixedWidth(44)
        self.setStyleSheet("background:#161618; border-right:1px solid #2d2d2d;")

        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 12, 4, 12)
        lay.setSpacing(4)

        group = QButtonGroup(self)
        self._btns: dict[str, QPushButton] = {}

        for key, tip in TOOLS:
            btn = QPushButton()
            btn.setCheckable(True)
            btn.setFixedSize(36, 36)
            btn.setIcon(_tool_icon(key, size=22))
            btn.setIconSize(QSize(22, 22))
            btn.setToolTip(tip)
            btn.setStyleSheet(_TOOL_BTN)
            btn.clicked.connect(lambda _, t=key: self.tool_changed.emit(t))
            group.addButton(btn)
            lay.addWidget(btn, alignment=Qt.AlignHCenter)
            self._btns[key] = btn

        self._btns["pen"].setChecked(True)

        # thin separator before utility buttons
        lay.addSpacing(6)
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("background:#2d2d2d;")
        sep.setFixedHeight(1)
        lay.addWidget(sep)
        lay.addSpacing(6)

        for symbol, tip, fn in [
            ("↩", "Undo  (Ctrl+Z)", canvas_undo),
            ("✕", "Clear canvas",   canvas_clear),
        ]:
            btn = QPushButton(symbol)
            btn.setFixedSize(36, 36)
            btn.setToolTip(tip)
            btn.setStyleSheet("""
                QPushButton { border:none; border-radius:6px; background:transparent;
                              color:#6b7280; font-size:14px; }
                QPushButton:hover { background:#2d2d2d; color:#d1d5db; }
            """)
            btn.clicked.connect(fn)
            lay.addWidget(btn, alignment=Qt.AlignHCenter)

        lay.addStretch()

    def select_tool(self, tool: str):
        if tool in self._btns:
            self._btns[tool].setChecked(True)


# ── patterns panel ────────────────────────────────────────────────────────────

_LIST_STYLE = """
    QListWidget { background:transparent; border:none; outline:none; }
    QListWidget::item { padding:0; border-bottom:1px solid #222; }
    QListWidget::item:selected { background:#262626; border-left:3px solid #3b82f6; }
    QListWidget::item:hover:!selected { background:#212121; }
"""


class PatternsPanel(QWidget):
    pattern_selected = Signal(int)

    def __init__(self):
        super().__init__()
        self.setFixedWidth(190)
        self.setStyleSheet("background:#1a1a1a; border-right:1px solid #2d2d2d;")

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        hdr = QLabel("  PATTERNS")
        hdr.setFixedHeight(36)
        hdr.setStyleSheet(
            "font-size:10px; font-weight:bold; color:#6b7280; letter-spacing:2px;"
            "border-bottom:1px solid #2d2d2d; padding-left:4px;"
        )
        lay.addWidget(hdr)

        self._list = QListWidget()
        self._list.setStyleSheet(_LIST_STYLE)
        self._list.setSelectionMode(QAbstractItemView.SingleSelection)
        self._list.setFocusPolicy(Qt.NoFocus)

        for name, icon_char, color, _ in PRESETS:
            item = QListWidgetItem()
            item.setSizeHint(QSize(190, 44))
            item.setIcon(_pattern_icon(icon_char, color, size=24))
            item.setText(f"  {name}")
            item.setFont(QFont("Arial", 12))
            self._list.addItem(item)

        self._list.itemClicked.connect(
            lambda item: self.pattern_selected.emit(self._list.row(item))
        )
        lay.addWidget(self._list, stretch=1)

        note = QLabel("  Click to add to canvas")
        note.setStyleSheet("color:#3d3d3d; font-size:10px; padding:4px 0;")
        lay.addWidget(note)


# ── right panel ───────────────────────────────────────────────────────────────

class RightPanel(QWidget):
    plot_requested   = Signal()
    cancel_requested = Signal()

    def __init__(self, plotter=None):
        super().__init__()
        self._plotter = plotter
        self.setFixedWidth(190)
        self.setStyleSheet("background:#1a1a1a; border-left:1px solid #2d2d2d;")

        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 14, 14, 14)
        lay.setSpacing(10)

        def hdr(text):
            lbl = QLabel(text)
            lbl.setStyleSheet(
                "font-size:10px; font-weight:bold; color:#6b7280; letter-spacing:1px;"
            )
            lay.addWidget(lbl)
            sep = QFrame()
            sep.setFrameShape(QFrame.HLine)
            sep.setFixedHeight(1)
            sep.setStyleSheet("background:#2d2d2d;")
            lay.addWidget(sep)

        hdr("STATS")
        self.lbl_paths    = QLabel("Paths\n—")
        self.lbl_distance = QLabel("Distance\n—")
        self.lbl_time     = QLabel("Est. time\n—")
        for l in (self.lbl_paths, self.lbl_distance, self.lbl_time):
            l.setStyleSheet("color:#d1d5db; font-size:12px;")
            lay.addWidget(l)

        lay.addSpacing(6)
        hdr("PROGRESS")

        self.prog_bar = QProgressBar()
        self.prog_bar.setVisible(False)
        self.prog_bar.setFixedHeight(10)
        lay.addWidget(self.prog_bar)

        self.prog_lbl = QLabel("")
        self.prog_lbl.setStyleSheet("color:#9ca3af; font-size:11px;")
        self.prog_lbl.setVisible(False)
        lay.addWidget(self.prog_lbl)

        lay.addStretch()

        self.btn_cancel = QPushButton("Cancel")
        self.btn_cancel.setVisible(False)
        self.btn_cancel.setStyleSheet(
            "QPushButton{border:1px solid #ef4444;color:#ef4444;border-radius:4px;padding:5px;}"
            "QPushButton:hover{background:#7f1d1d;color:white;}"
        )
        self.btn_cancel.clicked.connect(self.cancel_requested)
        lay.addWidget(self.btn_cancel)

        self.btn_plot = QPushButton("▶  Plot All")
        self.btn_plot.setStyleSheet(
            "QPushButton{background:#1e3a8a;color:#93c5fd;font-weight:bold;"
            "border:1px solid #1e40af;border-radius:6px;padding:12px 0;}"
            "QPushButton:hover{background:#1e40af;}"
            "QPushButton:disabled{background:#111827;color:#4b5563;border-color:#374151;}"
        )
        self.btn_plot.clicked.connect(self.plot_requested)
        lay.addWidget(self.btn_plot)

    def update_stats(self, canvas: "DrawCanvas"):
        s = canvas.stats()
        n, d = s["paths"], s["distance_mm"]
        self.lbl_paths.setText(f"Paths\n{n:,}")
        self.lbl_distance.setText(f"Distance\n{d / 1000:.2f} m")
        if self._plotter and n > 0:
            feed   = self._plotter.settings.get("feed_draw", 1500)
            settle = self._plotter.settings.get("servo_settle_ms", 150) / 1000
            secs   = int(d / (feed / 60) + n * settle * 2)
            m, s_  = divmod(secs, 60)
            self.lbl_time.setText(f"Est. time\n{m}m {s_:02d}s")
        else:
            self.lbl_time.setText("Est. time\n—")


# ── drawing canvas ────────────────────────────────────────────────────────────

class DrawCanvas(QWidget):
    def __init__(self, plotter=None):
        super().__init__()
        self.setMinimumSize(400, 400)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setCursor(Qt.CrossCursor)

        self._plotter = plotter
        self.tool = "pen"
        self.paths: list[list[tuple[float, float]]] = []

        self._drawing = False
        self._pts:   list[tuple] = []
        self._start: tuple | None = None
        self._mouse: tuple | None = None
        self._shift = False
        self._bg:   QPixmap | None = None

    # ── public ────────────────────────────────────────────────────────────────

    def set_tool(self, t: str):
        self.tool = t
        self._cancel()

    def undo(self):
        if self._drawing and self.tool == "polyline" and len(self._pts) > 1:
            self._pts.pop()
        elif self._drawing:
            self._cancel()
            return
        elif self.paths:
            self.paths.pop()
        self.update()

    def clear(self):
        self.paths.clear()
        self._cancel()

    def add_paths_mm(self, paths_mm: list, bed_mm: float = 220.0):
        for path in paths_mm:
            if len(path) >= 2:
                self.paths.append([(x / bed_mm, 1.0 - y / bed_mm) for x, y in path])
        self.update()

    def add_paths_norm(self, paths: list):
        self.paths.extend(p for p in paths if len(p) >= 2)
        self.update()

    def get_plotter_paths(self) -> list:
        bx = self._plotter.settings["x_max"] if self._plotter else 220.0
        by = self._plotter.settings["y_max"] if self._plotter else 220.0
        return [[(nx * bx, (1 - ny) * by) for nx, ny in p]
                for p in self.paths if len(p) >= 2]

    def to_json(self) -> dict:
        return {"version": 1, "paths": self.paths}

    def load_json(self, data: dict):
        self.paths = [list(map(tuple, p)) for p in data.get("paths", [])]
        self._cancel()
        self.update()

    def stats(self) -> dict:
        n = len(self.paths)
        dist = sum(
            math.hypot(p[i][0]-p[i-1][0], p[i][1]-p[i-1][1])
            for p in self.paths for i in range(1, len(p))
        )
        bed = self._plotter.settings["x_max"] if self._plotter else 220.0
        return {"paths": n, "distance_mm": dist * bed}

    # ── coords ────────────────────────────────────────────────────────────────

    def _paper_rect(self) -> QRectF:
        return QRectF(PAD, PAD, self.width() - PAD*2, self.height() - PAD*2)

    def _norm(self, qp) -> tuple:
        pr = self._paper_rect()
        return (max(0.0, min(1.0, (qp.x() - pr.x()) / pr.width())),
                max(0.0, min(1.0, (qp.y() - pr.y()) / pr.height())))

    def _px(self, nx: float, ny: float) -> tuple:
        pr = self._paper_rect()
        return int(pr.x() + nx * pr.width()), int(pr.y() + ny * pr.height())

    @staticmethod
    def _c45(o, t):
        dx, dy = t[0]-o[0], t[1]-o[1]
        d = math.hypot(dx, dy)
        a = round(math.atan2(dy, dx) / (math.pi/4)) * (math.pi/4)
        return o[0]+d*math.cos(a), o[1]+d*math.sin(a)

    @staticmethod
    def _csq(o, t):
        dx, dy = t[0]-o[0], t[1]-o[1]
        s = max(abs(dx), abs(dy))
        return o[0]+math.copysign(s, dx), o[1]+math.copysign(s, dy)

    def _cancel(self):
        self._drawing = False; self._pts = []; self._start = None; self.update()

    def _finish_polyline(self):
        if len(self._pts) >= 2:
            self.paths.append(list(self._pts))
        self._cancel()

    @staticmethod
    def _rect_path(x0, y0, x1, y1):
        a, b, c, d = min(x0,x1), min(y0,y1), max(x0,x1), max(y0,y1)
        return [(a,b),(c,b),(c,d),(a,d),(a,b)]

    @staticmethod
    def _ellipse_path(x0, y0, x1, y1, n=64):
        cx, cy = (x0+x1)/2, (y0+y1)/2
        rx, ry = abs(x1-x0)/2, abs(y1-y0)/2
        if rx < 1e-6 or ry < 1e-6:
            return []
        return [(cx+rx*math.cos(2*math.pi*i/n), cy+ry*math.sin(2*math.pi*i/n))
                for i in range(n+1)]

    # ── events ────────────────────────────────────────────────────────────────

    def resizeEvent(self, _e):
        super().resizeEvent(_e); self._bg = None

    def keyPressEvent(self, e):
        self._shift = bool(e.modifiers() & Qt.ShiftModifier)
        k = e.key()
        if k == Qt.Key_Escape:
            self._cancel()
        elif k in (Qt.Key_Return, Qt.Key_Enter) and self.tool == "polyline":
            self._finish_polyline()
        elif e.modifiers() & Qt.ControlModifier and k == Qt.Key_Z:
            self.undo()
        super().keyPressEvent(e)

    def keyReleaseEvent(self, e):
        self._shift = bool(e.modifiers() & Qt.ShiftModifier)
        self.update()
        super().keyReleaseEvent(e)

    def mousePressEvent(self, e):
        if e.button() != Qt.LeftButton: return
        self.setFocus()
        pos = self._norm(e.pos())
        if self.tool == "pen":
            self._drawing = True; self._pts = [pos]
        elif self.tool == "polyline":
            if not self._drawing:
                self._drawing = True; self._pts = [pos]
            else:
                self._pts.append(self._c45(self._pts[-1], pos) if self._shift else pos)
        elif self.tool in ("rect", "ellipse"):
            self._drawing = True; self._start = pos

    def mouseMoveEvent(self, e):
        self._shift = bool(e.modifiers() & Qt.ShiftModifier)
        self._mouse = self._norm(e.pos())
        if self._drawing and self.tool == "pen":
            self._pts.append(self._mouse)
        self.update()

    def mouseReleaseEvent(self, e):
        if e.button() != Qt.LeftButton: return
        pos = self._norm(e.pos())
        if self.tool == "pen" and self._drawing:
            if len(self._pts) >= 2:
                self.paths.append(list(self._pts))
            self._cancel()
        elif self.tool in ("rect", "ellipse") and self._drawing:
            end = self._csq(self._start, pos) if self._shift else pos
            path = (self._rect_path(*self._start, *end) if self.tool == "rect"
                    else self._ellipse_path(*self._start, *end))
            if path:
                self.paths.append(path)
            self._drawing = False; self._start = None

    def mouseDoubleClickEvent(self, e):
        if e.button() == Qt.LeftButton and self.tool == "polyline" and self._drawing:
            self._finish_polyline()

    # ── background ────────────────────────────────────────────────────────────

    def _get_bg(self) -> QPixmap:
        if self._bg is None:
            self._bg = self._render_bg()
        return self._bg

    def _render_bg(self) -> QPixmap:
        w, h = self.width(), self.height()
        if w <= 0 or h <= 0: return QPixmap(1, 1)
        pix = QPixmap(w, h)
        pix.fill(BG)
        pr = self._paper_rect()
        p = QPainter(pix)
        p.setRenderHint(QPainter.Antialiasing)
        for i in range(10, 0, -1):
            p.setBrush(QColor(0, 0, 0, int(90*(1-i/10))))
            p.setPen(Qt.NoPen)
            p.drawRoundedRect(QRectF(pr.x()+i*.5, pr.y()+i*.7, pr.width(), pr.height()), 4, 4)
        p.setBrush(PAPER); p.setPen(Qt.NoPen)
        p.drawRoundedRect(pr, 4, 4)
        p.setPen(Qt.NoPen); p.setBrush(QBrush(GRID))
        sp, ox, oy = 28, int(pr.x()), int(pr.y())
        for gx in range(ox+sp, ox+int(pr.width()), sp):
            for gy in range(oy+sp, oy+int(pr.height()), sp):
                p.drawEllipse(gx-1, gy-1, 2, 2)
        p.end()
        return pix

    # ── paint ─────────────────────────────────────────────────────────────────

    def paintEvent(self, _e):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        pr = self._paper_rect()
        painter.drawPixmap(0, 0, self._get_bg())

        clip = QPainterPath()
        clip.addRoundedRect(pr, 4, 4)
        painter.setClipPath(clip)

        painter.setPen(QPen(INK, 2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        painter.setBrush(Qt.NoBrush)
        for path in self.paths:
            self._draw_pts(painter, path)

        if self._drawing:
            painter.setPen(QPen(LIVE, 2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            m = self._mouse
            if self.tool in ("pen", "polyline") and self._pts:
                self._draw_pts(painter, self._pts)
                if self.tool == "polyline" and m:
                    end = self._c45(self._pts[-1], m) if self._shift else m
                    painter.setPen(QPen(LIVE, 1.5, Qt.DashLine))
                    x1, y1 = self._px(*self._pts[-1])
                    x2, y2 = self._px(*end)
                    painter.drawLine(x1, y1, x2, y2)
                    painter.setBrush(QBrush(LIVE))
                    painter.setPen(Qt.NoPen)
                    for pt in self._pts:
                        px_, py_ = self._px(*pt)
                        painter.drawEllipse(px_-4, py_-4, 8, 8)
            elif self.tool in ("rect", "ellipse") and self._start and m:
                end = self._csq(self._start, m) if self._shift else m
                painter.setPen(QPen(LIVE, 2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
                painter.setBrush(Qt.NoBrush)
                path = (self._rect_path(*self._start, *end) if self.tool == "rect"
                        else self._ellipse_path(*self._start, *end, n=64))
                if path:
                    self._draw_pts(painter, path)

        painter.setClipping(False)
        if self._mouse:
            mx, my = self._px(*self._mouse)
            painter.setBrush(QBrush(LIVE))
            painter.setPen(Qt.NoPen)
            painter.drawEllipse(mx-3, my-3, 6, 6)

    def _draw_pts(self, painter: QPainter, pts: list):
        for i in range(1, len(pts)):
            x1, y1 = self._px(*pts[i-1])
            x2, y2 = self._px(*pts[i])
            painter.drawLine(x1, y1, x2, y2)


# ── main panel ────────────────────────────────────────────────────────────────

class DrawPanel(QWidget):
    _plot_progress = Signal(int, int)
    _plot_done     = Signal(bool)

    def __init__(self, plotter=None):
        super().__init__()
        self._plotter    = plotter
        self._plot_cancel = threading.Event()

        self._canvas   = DrawCanvas(plotter)
        self._tools    = ToolColumn(self._canvas.undo, self._canvas.clear)
        self._patterns = PatternsPanel()
        self._right    = RightPanel(plotter)

        self._tools.tool_changed.connect(self._canvas.set_tool)
        self._patterns.pattern_selected.connect(self._add_pattern)
        self._right.plot_requested.connect(self._start_plot)
        self._right.cancel_requested.connect(lambda: self._plot_cancel.set())

        self._plot_progress.connect(self._on_plot_progress)
        self._plot_done.connect(self._on_plot_done)

        self._build_ui()
        QShortcut(QKeySequence("Ctrl+Z"), self, self._canvas.undo)
        QShortcut(QKeySequence("Ctrl+S"), self, self._save)
        QShortcut(QKeySequence("Ctrl+O"), self, self._load)

        t = QTimer(self)
        t.setInterval(1000)
        t.timeout.connect(lambda: self._right.update_stats(self._canvas))
        t.start()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_toolbar())

        body = QWidget()
        blay = QHBoxLayout(body)
        blay.setContentsMargins(0, 0, 0, 0)
        blay.setSpacing(0)
        blay.addWidget(self._tools)
        blay.addWidget(self._patterns)
        blay.addWidget(self._canvas, stretch=1)
        blay.addWidget(self._right)
        root.addWidget(body, stretch=1)

    def _build_toolbar(self) -> QWidget:
        bar = QWidget()
        bar.setFixedHeight(44)
        bar.setStyleSheet("background:#1e1e1e; border-bottom:1px solid #2d2d2d;")
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(12, 0, 12, 0)
        lay.setSpacing(6)

        def btn(label: str, tip: str = "") -> QPushButton:
            b = QPushButton(label)
            if tip: b.setToolTip(tip)
            b.setStyleSheet(
                "QPushButton{border:1px solid #444;border-radius:4px;padding:4px 10px;}"
                "QPushButton:hover{background:#2d2d2d;}"
            )
            return b

        lay.addWidget(QLabel("Paper:"))
        self._paper_combo = QComboBox()
        self._paper_combo.setFixedWidth(138)
        self._paper_combo.setStyleSheet(
            "background:#262626;border:1px solid #404040;"
            "border-radius:4px;padding:3px 6px;color:#fff;"
        )
        for name, *_ in PAPER_PRESETS:
            self._paper_combo.addItem(name)
        self._paper_combo.currentIndexChanged.connect(self._apply_paper)
        lay.addWidget(self._paper_combo)

        lay.addWidget(self._vsep())

        for label, fn, tip in [
            ("Save",       self._save,       "Ctrl+S"),
            ("Load",       self._load,       "Ctrl+O"),
            ("Import SVG", self._import_svg, "Import an SVG file"),
        ]:
            b = btn(label, tip)
            b.clicked.connect(fn)
            lay.addWidget(b)

        lay.addStretch()

        self._status_lbl = QLabel("Ready")
        self._status_lbl.setStyleSheet("color:#52525b; font-size:11px;")
        lay.addWidget(self._status_lbl)

        return bar

    @staticmethod
    def _vsep() -> QWidget:
        f = QWidget()
        f.setFixedSize(1, 22)
        f.setStyleSheet("background:#333;")
        return f

    # ── paper ─────────────────────────────────────────────────────────────────

    def _apply_paper(self, idx: int):
        if not self._plotter or idx < 0 or idx >= len(PAPER_PRESETS):
            return
        _, xmax, ymax = PAPER_PRESETS[idx]
        self._plotter.settings["x_max"] = xmax
        self._plotter.settings["y_max"] = ymax
        self._canvas._bg = None
        self._canvas.update()
        self._set_status(f"Paper: {PAPER_PRESETS[idx][0]}")

    # ── patterns ──────────────────────────────────────────────────────────────

    def _add_pattern(self, row: int):
        if 0 <= row < len(PRESETS):
            name, _, _, gen = PRESETS[row]
            self._canvas.add_paths_mm(gen(), bed_mm=220.0)
            self._set_status(f"Added {name}")
            self._patterns._list.clearSelection()

    # ── file I/O ──────────────────────────────────────────────────────────────

    def _save(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Drawing", "", "Plot files (*.plot);;JSON (*.json)")
        if path:
            Path(path).write_text(json.dumps(self._canvas.to_json(), indent=2))
            self._set_status(f"Saved → {Path(path).name}")

    def _load(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Load Drawing", "", "Plot files (*.plot);;JSON (*.json)")
        if path:
            try:
                self._canvas.load_json(json.loads(Path(path).read_text()))
                self._set_status(f"Loaded {Path(path).name}")
            except Exception as exc:
                self._set_status(f"Load failed: {exc}")

    def _import_svg(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Import SVG", "", "SVG files (*.svg)")
        if path:
            try:
                paths = parse_svg(path)
                if paths:
                    self._canvas.add_paths_norm(paths)
                    self._set_status(f"Imported {len(paths)} paths")
                else:
                    self._set_status("No paths found in SVG")
            except Exception as exc:
                self._set_status(f"SVG import failed: {exc}")

    # ── plot ──────────────────────────────────────────────────────────────────

    def _start_plot(self):
        if not self._plotter or not self._plotter.connected:
            self._set_status("Connect the plotter first")
            return
        paths = self._canvas.get_plotter_paths()
        if not paths:
            self._set_status("Nothing to plot")
            return
        self._plot_cancel.clear()
        self._right.btn_plot.setEnabled(False)
        self._right.btn_cancel.setVisible(True)
        self._right.prog_bar.setRange(0, len(paths))
        self._right.prog_bar.setValue(0)
        self._right.prog_bar.setVisible(True)
        self._right.prog_lbl.setVisible(True)
        threading.Thread(target=self._run_plot, args=(paths,), daemon=True).start()

    def _run_plot(self, paths: list):
        total = len(paths)
        for i, path in enumerate(paths):
            if self._plot_cancel.is_set():
                self._plotter.pen_up()
                self._plot_done.emit(False)
                return
            if len(path) < 2:
                continue
            self._plotter.pen_up()
            self._plotter.move_to(path[0][0], path[0][1])
            self._plotter.pen_down()
            for x, y in path[1:]:
                if self._plot_cancel.is_set():
                    self._plotter.pen_up()
                    self._plot_done.emit(False)
                    return
                self._plotter.move_to(x, y, self._plotter.settings.get("feed_draw", 1500))
            self._plot_progress.emit(i + 1, total)
        self._plotter.pen_up()
        self._plot_done.emit(True)

    def _on_plot_progress(self, current: int, total: int):
        self._right.prog_bar.setValue(current)
        self._right.prog_lbl.setText(f"Stroke {current} / {total}")

    def _on_plot_done(self, success: bool):
        self._right.prog_bar.setVisible(False)
        self._right.prog_lbl.setVisible(False)
        self._right.btn_cancel.setVisible(False)
        self._right.btn_plot.setEnabled(True)
        self._set_status("Plot complete ✓" if success else "Plot cancelled")

    # ── Track → Draw ──────────────────────────────────────────────────────────

    def receive_strokes(self, strokes: list):
        self._canvas.add_paths_norm(strokes)
        self._set_status(f"Received {len(strokes)} stroke(s) from Track")

    def _set_status(self, msg: str):
        self._status_lbl.setText(msg)
