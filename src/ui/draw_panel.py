"""
draw_panel.py — Unified Draw tab.

Layout: ToolColumn (44 px) | Canvas (flex) | RightPanel (230 px)
RightPanel: PATTERNS list (top, scrollable) + STATS + PLOT (bottom)

Toolbar: Undo · Clear · Paper size · Save · Load · Import SVG
"""
from __future__ import annotations
import json
import math
from pathlib import Path

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QFrame, QListWidget, QListWidgetItem,
    QProgressBar, QFileDialog, QComboBox, QButtonGroup,
    QAbstractItemView, QDoubleSpinBox,
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

BG    = QColor("#1e1e1e")
PAPER = QColor("#fafaf8")
GRID  = QColor("#e0e4ea")
INK   = QColor("#1a1a1a")
LIVE  = QColor("#2680eb")
PAD   = 28

TOOLS = [
    ("pen",     "Pen — drag to draw freehand  (P)"),
    ("polyline","Polyline — click points, dbl-click to finish  (L)"),
    ("rect",    "Rectangle — drag, Shift = square  (R)"),
    ("ellipse", "Ellipse — drag, Shift = circle  (E)"),
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


# ── icon renderers ────────────────────────────────────────────────────────────

def _tool_icon(tool: str, size: int = 20) -> QIcon:
    pix = QPixmap(size, size)
    pix.fill(QColor(0, 0, 0, 0))
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing)
    c = QColor("#b8bec8")
    pen = QPen(c, 1.5, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    m, s = 3, size

    if tool == "pen":
        path = QPainterPath()
        path.moveTo(m, s - m)
        path.cubicTo(m + 1, s * 0.4, s - m - 1, s * 0.6, s - m, m)
        p.drawPath(path)
        p.setBrush(QBrush(c)); p.setPen(Qt.NoPen)
        p.drawEllipse(s - m - 2, m - 1, 3, 3)

    elif tool == "polyline":
        pts = [(m, s-m), (m+3, s//2-1), (s-m-3, s//2+2), (s-m, m)]
        for i in range(1, len(pts)):
            p.drawLine(pts[i-1][0], pts[i-1][1], pts[i][0], pts[i][1])
        p.setBrush(QBrush(c)); p.setPen(Qt.NoPen)
        for x, y in pts:
            p.drawEllipse(x - 2, y - 2, 4, 4)

    elif tool == "rect":
        p.drawRect(m, m, s - m*2, s - m*2)

    elif tool == "ellipse":
        p.drawEllipse(m, m + 2, s - m*2, s - m*2 - 4)

    p.end()
    return QIcon(pix)


def _preset_dot(char: str, color: str, size: int = 22) -> QIcon:
    pix = QPixmap(size, size)
    pix.fill(QColor(0, 0, 0, 0))
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing)
    bg = QColor(color); bg.setAlpha(35)
    p.setBrush(QBrush(bg)); p.setPen(Qt.NoPen)
    p.drawRoundedRect(2, 2, size-4, size-4, 4, 4)
    p.setPen(QPen(QColor(color)))
    p.setFont(QFont("Arial", int(size * 0.46), QFont.Bold))
    p.drawText(QRectF(0, 0, size, size), Qt.AlignCenter, char)
    p.end()
    return QIcon(pix)


# ── narrow tool column ────────────────────────────────────────────────────────

class ToolColumn(QWidget):
    tool_changed = Signal(str)

    def __init__(self):
        super().__init__()
        self.setFixedWidth(44)
        self.setStyleSheet(
            "background: #252525; border-right: 1px solid #111;"
        )

        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 14, 4, 14)
        lay.setSpacing(3)

        group = QButtonGroup(self)
        self._btns: dict[str, QPushButton] = {}

        for key, tip in TOOLS:
            btn = QPushButton()
            btn.setCheckable(True)
            btn.setFixedSize(36, 36)
            btn.setIcon(_tool_icon(key, size=20))
            btn.setIconSize(QSize(20, 20))
            btn.setToolTip(tip)
            btn.setStyleSheet("""
                QPushButton {
                    border: none;
                    border-radius: 4px;
                    background: transparent;
                    padding: 0;
                }
                QPushButton:hover   { background: #353535; }
                QPushButton:checked { background: #1a3a5a; border: 1px solid #2680eb; }
            """)
            btn.clicked.connect(lambda _, t=key: self.tool_changed.emit(t))
            group.addButton(btn)
            lay.addWidget(btn, alignment=Qt.AlignHCenter)
            self._btns[key] = btn

        self._btns["pen"].setChecked(True)
        lay.addStretch()

    def select_tool(self, tool: str):
        if tool in self._btns:
            self._btns[tool].setChecked(True)


# ── right panel: patterns + stats + plot ─────────────────────────────────────

class RightPanel(QWidget):
    pattern_selected = Signal(int)
    plot_requested   = Signal()
    cancel_requested = Signal()

    def __init__(self, plotter=None):
        super().__init__()
        self._plotter = plotter
        self.setFixedWidth(230)
        self.setStyleSheet(
            "background: #252525; border-left: 1px solid #111;"
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Patterns ─────────────────────────────────────────────────────────
        root.addWidget(self._section_hdr("PATTERNS"))

        self._patt_list = QListWidget()
        self._patt_list.setStyleSheet("""
            QListWidget { background: transparent; border: none; outline: none; }
            QListWidget::item { padding: 0; border-bottom: 1px solid #1a1a1a; }
            QListWidget::item:selected { background: #1a3a5c; border-left: 2px solid #2680eb; }
            QListWidget::item:hover:!selected { background: #2a2a2a; }
        """)
        self._patt_list.setSelectionMode(QAbstractItemView.SingleSelection)
        self._patt_list.setFocusPolicy(Qt.NoFocus)

        for name, ch, color, _ in PRESETS:
            item = QListWidgetItem()
            item.setSizeHint(QSize(230, 38))
            item.setIcon(_preset_dot(ch, color, size=22))
            item.setText(f"  {name}")
            item.setFont(QFont("Arial", 11))
            self._patt_list.addItem(item)

        self._patt_list.itemClicked.connect(
            lambda item: self.pattern_selected.emit(self._patt_list.row(item))
        )
        root.addWidget(self._patt_list, stretch=1)

        hint = QLabel("  click to add to canvas")
        hint.setStyleSheet("color: #333; font-size: 10px; padding: 3px 0;")
        root.addWidget(hint)

        # ── separator ─────────────────────────────────────────────────────────
        root.addWidget(self._hsep())

        # ── Stats ─────────────────────────────────────────────────────────────
        root.addWidget(self._section_hdr("STATS"))

        stats_w = QWidget()
        stats_w.setStyleSheet("background: transparent;")
        sl = QVBoxLayout(stats_w)
        sl.setContentsMargins(14, 6, 14, 8)
        sl.setSpacing(4)

        self.lbl_paths    = QLabel("Paths     —")
        self.lbl_distance = QLabel("Distance  —")
        self.lbl_time     = QLabel("Est. time —")
        for l in (self.lbl_paths, self.lbl_distance, self.lbl_time):
            l.setStyleSheet(
                "color: #c0c0c0; font-size: 11px; font-family: monospace;"
            )
            sl.addWidget(l)
        root.addWidget(stats_w)

        # ── Plot ──────────────────────────────────────────────────────────────
        root.addWidget(self._hsep())

        plot_w = QWidget()
        plot_w.setStyleSheet("background: transparent;")
        pl = QVBoxLayout(plot_w)
        pl.setContentsMargins(10, 8, 10, 12)

        self.btn_plot = QPushButton("▶  Plot")
        self.btn_plot.setStyleSheet(
            "QPushButton { background: #2680eb; color: white; font-weight: bold;"
            "  border: none; border-radius: 4px; padding: 11px 0; }"
            "QPushButton:hover { background: #1473e6; }"
            "QPushButton:disabled { background: #252525; color: #484848; border: 1px solid #2a2a2a; }"
        )
        self.btn_plot.setToolTip("Switch to Plotter tab and start plotting with preview")
        self.btn_plot.clicked.connect(self.plot_requested)
        pl.addWidget(self.btn_plot)

        root.addWidget(plot_w)

    @staticmethod
    def _section_hdr(text: str) -> QLabel:
        lbl = QLabel(f"  {text}")
        lbl.setFixedHeight(32)
        lbl.setStyleSheet(
            "font-size: 10px; font-weight: bold; color: #606060; letter-spacing: 1.5px;"
            "background: #222; border-bottom: 1px solid #111;"
        )
        return lbl

    @staticmethod
    def _hsep() -> QFrame:
        f = QFrame()
        f.setFrameShape(QFrame.HLine)
        f.setFixedHeight(1)
        f.setStyleSheet("background: #111;")
        return f

    def update_stats(self, canvas: "DrawCanvas"):
        s = canvas.stats()
        n, d = s["paths"], s["distance_mm"]
        self.lbl_paths.setText(   f"Paths     {n:,}")
        self.lbl_distance.setText(f"Distance  {d/1000:.2f} m")
        if self._plotter and n > 0:
            feed   = self._plotter.settings.get("feed_draw", 1500)
            settle = self._plotter.settings.get("servo_settle_ms", 150) / 1000
            secs   = int(d / (feed / 60) + n * settle * 2)
            m_, s_ = divmod(secs, 60)
            self.lbl_time.setText(f"Est. time {m_}m {s_:02d}s")
        else:
            self.lbl_time.setText("Est. time —")


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
        self.tool = t; self._cancel()

    def undo(self):
        if self._drawing and self.tool == "polyline" and len(self._pts) > 1:
            self._pts.pop()
        elif self._drawing:
            self._cancel(); return
        elif self.paths:
            self.paths.pop()
        self.update()

    def clear(self):
        self.paths.clear(); self._cancel()

    def add_paths_mm(self, paths_mm: list, bed_mm: float = 220.0):
        for path in paths_mm:
            if len(path) >= 2:
                self.paths.append([(x/bed_mm, 1.0 - y/bed_mm) for x, y in path])
        self.update()

    def add_paths_norm(self, paths: list):
        self.paths.extend(p for p in paths if len(p) >= 2)
        self.update()

    def get_plotter_paths(self) -> list:
        if self._plotter:
            s = self._plotter.settings
            bx = s.get("_paper_x", s["x_max"] - s.get("x_min", 0))
            by = s.get("_paper_y", s["y_max"] - s.get("y_min", 0))
            ox = s.get("x_min", 0)
            oy = s.get("y_min", 0)
        else:
            bx, by, ox, oy = 220.0, 220.0, 0.0, 0.0
        return [[(ox + nx*bx, oy + (1-ny)*by) for nx, ny in p]
                for p in self.paths if len(p) >= 2]

    def to_json(self) -> dict:
        return {"version": 1, "paths": self.paths}

    def load_json(self, data: dict):
        self.paths = [list(map(tuple, p)) for p in data.get("paths", [])]
        self._cancel(); self.update()

    def stats(self) -> dict:
        n = len(self.paths)
        d = sum(math.hypot(p[i][0]-p[i-1][0], p[i][1]-p[i-1][1])
                for p in self.paths for i in range(1, len(p)))
        bed = self._plotter.settings["x_max"] if self._plotter else 220.0
        return {"paths": n, "distance_mm": d * bed}

    # ── coords ────────────────────────────────────────────────────────────────

    def _paper_rect(self) -> QRectF:
        return QRectF(PAD, PAD, self.width()-PAD*2, self.height()-PAD*2)

    def _norm(self, qp) -> tuple:
        pr = self._paper_rect()
        return (max(0., min(1., (qp.x()-pr.x())/pr.width())),
                max(0., min(1., (qp.y()-pr.y())/pr.height())))

    def _px(self, nx: float, ny: float) -> tuple:
        pr = self._paper_rect()
        return int(pr.x()+nx*pr.width()), int(pr.y()+ny*pr.height())

    @staticmethod
    def _c45(o, t):
        dx, dy = t[0]-o[0], t[1]-o[1]; d = math.hypot(dx, dy)
        a = round(math.atan2(dy, dx)/(math.pi/4))*(math.pi/4)
        return o[0]+d*math.cos(a), o[1]+d*math.sin(a)

    @staticmethod
    def _csq(o, t):
        dx, dy = t[0]-o[0], t[1]-o[1]; s = max(abs(dx), abs(dy))
        return o[0]+math.copysign(s, dx), o[1]+math.copysign(s, dy)

    # ── transform ─────────────────────────────────────────────────────────────

    def scale_by(self, factor: float):
        """Scale all paths around their collective centroid."""
        if not self.paths or factor <= 0:
            return
        all_pts = [p for path in self.paths for p in path]
        cx = sum(p[0] for p in all_pts) / len(all_pts)
        cy = sum(p[1] for p in all_pts) / len(all_pts)
        self.paths = [[(cx + (p[0]-cx)*factor, cy + (p[1]-cy)*factor)
                       for p in path]
                      for path in self.paths]
        self.update()

    def fit_to_paper(self, margin: float = 0.05):
        """Scale and centre all paths to fill the paper with a margin."""
        if not self.paths:
            return
        all_pts = [p for path in self.paths for p in path]
        min_x = min(p[0] for p in all_pts); max_x = max(p[0] for p in all_pts)
        min_y = min(p[1] for p in all_pts); max_y = max(p[1] for p in all_pts)
        span_x = max_x - min_x or 1
        span_y = max_y - min_y or 1
        factor = min((1 - 2*margin) / span_x, (1 - 2*margin) / span_y)
        new_w = span_x * factor
        new_h = span_y * factor
        ox = margin + (1 - 2*margin - new_w) / 2
        oy = margin + (1 - 2*margin - new_h) / 2
        self.paths = [[(ox + (p[0]-min_x)*factor, oy + (p[1]-min_y)*factor)
                       for p in path]
                      for path in self.paths]
        self.update()

    def _cancel(self):
        self._drawing = False; self._pts = []; self._start = None; self.update()

    def _finish_polyline(self):
        if len(self._pts) >= 2: self.paths.append(list(self._pts))
        self._cancel()

    @staticmethod
    def _rect_path(x0, y0, x1, y1):
        a, b, c, d = min(x0,x1), min(y0,y1), max(x0,x1), max(y0,y1)
        return [(a,b),(c,b),(c,d),(a,d),(a,b)]

    @staticmethod
    def _ellipse_path(x0, y0, x1, y1, n=64):
        cx, cy = (x0+x1)/2, (y0+y1)/2; rx, ry = abs(x1-x0)/2, abs(y1-y0)/2
        if rx < 1e-6 or ry < 1e-6: return []
        return [(cx+rx*math.cos(2*math.pi*i/n), cy+ry*math.sin(2*math.pi*i/n))
                for i in range(n+1)]

    # ── events ────────────────────────────────────────────────────────────────

    def resizeEvent(self, _e): super().resizeEvent(_e); self._bg = None

    def keyPressEvent(self, e):
        self._shift = bool(e.modifiers() & Qt.ShiftModifier)
        k = e.key()
        if k == Qt.Key_Escape: self._cancel()
        elif k in (Qt.Key_Return, Qt.Key_Enter) and self.tool == "polyline": self._finish_polyline()
        elif e.modifiers() & Qt.ControlModifier and k == Qt.Key_Z: self.undo()
        super().keyPressEvent(e)

    def keyReleaseEvent(self, e):
        self._shift = bool(e.modifiers() & Qt.ShiftModifier); self.update()
        super().keyReleaseEvent(e)

    def mousePressEvent(self, e):
        if e.button() != Qt.LeftButton: return
        self.setFocus(); pos = self._norm(e.pos())
        if self.tool == "pen": self._drawing = True; self._pts = [pos]
        elif self.tool == "polyline":
            if not self._drawing: self._drawing = True; self._pts = [pos]
            else: self._pts.append(self._c45(self._pts[-1], pos) if self._shift else pos)
        elif self.tool in ("rect","ellipse"): self._drawing = True; self._start = pos

    def mouseMoveEvent(self, e):
        self._shift = bool(e.modifiers() & Qt.ShiftModifier)
        self._mouse = self._norm(e.pos())
        if self._drawing and self.tool == "pen": self._pts.append(self._mouse)
        self.update()

    def mouseReleaseEvent(self, e):
        if e.button() != Qt.LeftButton: return
        pos = self._norm(e.pos())
        if self.tool == "pen" and self._drawing:
            if len(self._pts) >= 2: self.paths.append(list(self._pts))
            self._cancel()
        elif self.tool in ("rect","ellipse") and self._drawing:
            end = self._csq(self._start, pos) if self._shift else pos
            path = (self._rect_path(*self._start, *end) if self.tool == "rect"
                    else self._ellipse_path(*self._start, *end))
            if path: self.paths.append(path)
            self._drawing = False; self._start = None

    def mouseDoubleClickEvent(self, e):
        if e.button() == Qt.LeftButton and self.tool == "polyline" and self._drawing:
            self._finish_polyline()

    # ── background ────────────────────────────────────────────────────────────

    def _get_bg(self) -> QPixmap:
        if self._bg is None: self._bg = self._render_bg()
        return self._bg

    def _render_bg(self) -> QPixmap:
        w, h = self.width(), self.height()
        if w <= 0 or h <= 0: return QPixmap(1, 1)
        pix = QPixmap(w, h); pix.fill(BG)
        pr = self._paper_rect()
        p = QPainter(pix); p.setRenderHint(QPainter.Antialiasing)
        # Subtle shadow
        for i in range(8, 0, -1):
            p.setBrush(QColor(0, 0, 0, int(60*(1-i/8))))
            p.setPen(Qt.NoPen)
            p.drawRoundedRect(QRectF(pr.x()+i*.5, pr.y()+i*.6, pr.width(), pr.height()), 3, 3)
        # Paper
        p.setBrush(PAPER); p.setPen(Qt.NoPen)
        p.drawRoundedRect(pr, 3, 3)
        # Subtle dot grid
        p.setPen(Qt.NoPen); p.setBrush(QBrush(GRID))
        sp, ox, oy = 24, int(pr.x()), int(pr.y())
        for gx in range(ox+sp, ox+int(pr.width()), sp):
            for gy in range(oy+sp, oy+int(pr.height()), sp):
                p.drawEllipse(gx-1, gy-1, 2, 2)
        p.end(); return pix

    # ── paint ─────────────────────────────────────────────────────────────────

    def paintEvent(self, _e):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        pr = self._paper_rect()
        painter.drawPixmap(0, 0, self._get_bg())

        clip = QPainterPath()
        clip.addRoundedRect(pr, 3, 3)
        painter.setClipPath(clip)

        painter.setPen(QPen(INK, 1.5, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        painter.setBrush(Qt.NoBrush)
        for path in self.paths: self._draw_pts(painter, path)

        if self._drawing:
            painter.setPen(QPen(LIVE, 1.5, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            m = self._mouse
            if self.tool in ("pen","polyline") and self._pts:
                self._draw_pts(painter, self._pts)
                if self.tool == "polyline" and m:
                    end = self._c45(self._pts[-1], m) if self._shift else m
                    painter.setPen(QPen(LIVE, 1, Qt.DashLine))
                    x1, y1 = self._px(*self._pts[-1]); x2, y2 = self._px(*end)
                    painter.drawLine(x1, y1, x2, y2)
                    painter.setBrush(QBrush(LIVE)); painter.setPen(Qt.NoPen)
                    for pt in self._pts:
                        px_, py_ = self._px(*pt); painter.drawEllipse(px_-3, py_-3, 6, 6)
            elif self.tool in ("rect","ellipse") and self._start and m:
                end = self._csq(self._start, m) if self._shift else m
                painter.setPen(QPen(LIVE, 1.5, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
                painter.setBrush(Qt.NoBrush)
                path = (self._rect_path(*self._start, *end) if self.tool == "rect"
                        else self._ellipse_path(*self._start, *end, n=64))
                if path: self._draw_pts(painter, path)

        painter.setClipping(False)
        if self._mouse:
            mx, my = self._px(*self._mouse)
            painter.setBrush(QBrush(LIVE)); painter.setPen(Qt.NoPen)
            painter.drawEllipse(mx-3, my-3, 6, 6)

    def _draw_pts(self, painter, pts):
        for i in range(1, len(pts)):
            x1, y1 = self._px(*pts[i-1]); x2, y2 = self._px(*pts[i])
            painter.drawLine(x1, y1, x2, y2)


# ── main panel ────────────────────────────────────────────────────────────────

class DrawPanel(QWidget):
    # Emitted when the user clicks Plot — app switches to Plotter tab
    plot_navigate = Signal(list)   # carries the mm-coord paths

    def __init__(self, plotter=None):
        super().__init__()
        self._plotter = plotter

        self._canvas = DrawCanvas(plotter)
        self._tools  = ToolColumn()
        self._right  = RightPanel(plotter)

        self._tools.tool_changed.connect(self._canvas.set_tool)
        self._right.pattern_selected.connect(self._add_pattern)
        self._right.plot_requested.connect(self._start_plot)

        self._build_ui()

        QShortcut(QKeySequence("Ctrl+Z"), self, self._canvas.undo)
        QShortcut(QKeySequence("Ctrl+S"), self, self._save)
        QShortcut(QKeySequence("Ctrl+O"), self, self._load)

        t = QTimer(self); t.setInterval(1000)
        t.timeout.connect(lambda: self._right.update_stats(self._canvas))
        t.start()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._build_toolbar())

        body = QWidget()
        bl = QHBoxLayout(body)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.setSpacing(0)
        bl.addWidget(self._tools)
        bl.addWidget(self._canvas, stretch=1)
        bl.addWidget(self._right)
        root.addWidget(body, stretch=1)

    def _build_toolbar(self) -> QWidget:
        bar = QWidget()
        bar.setFixedHeight(40)
        bar.setStyleSheet("background: #2c2c2c; border-bottom: 1px solid #111;")
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(10, 0, 10, 0)
        lay.setSpacing(4)

        def btn(txt: str, tip: str = "") -> QPushButton:
            b = QPushButton(txt)
            if tip: b.setToolTip(tip)
            return b

        b_undo  = btn("Undo",  "Ctrl+Z"); b_undo.clicked.connect(self._canvas.undo)
        b_clear = btn("Clear");           b_clear.clicked.connect(self._canvas.clear)
        lay.addWidget(b_undo)
        lay.addWidget(b_clear)

        lay.addWidget(self._vsep())

        # Paper size — includes "From Soft Limits" as first item
        lay.addWidget(QLabel("Paper:"))
        self._paper_combo = QComboBox()
        self._paper_combo.setFixedWidth(148)
        self._paper_combo.addItem("From Soft Limits")   # index 0 — dynamic
        for name, *_ in PAPER_PRESETS:
            self._paper_combo.addItem(name)
        self._paper_combo.currentIndexChanged.connect(self._apply_paper)
        lay.addWidget(self._paper_combo)

        lay.addWidget(self._vsep())

        # Scale controls
        lay.addWidget(QLabel("Scale:"))
        self._scale_spin = QDoubleSpinBox()
        self._scale_spin.setRange(0.05, 10.0)
        self._scale_spin.setValue(1.0)
        self._scale_spin.setSingleStep(0.25)
        self._scale_spin.setSuffix(" ×")
        self._scale_spin.setFixedWidth(72)
        self._scale_spin.setToolTip("Scale factor (1.0 = no change)")
        lay.addWidget(self._scale_spin)

        btn_scale = btn("Scale", "Scale drawing by the factor above")
        btn_scale.clicked.connect(
            lambda: self._canvas.scale_by(self._scale_spin.value())
        )
        lay.addWidget(btn_scale)

        btn_fit = btn("Fit", "Scale and centre to fill the paper")
        btn_fit.clicked.connect(self._canvas.fit_to_paper)
        lay.addWidget(btn_fit)

        lay.addWidget(self._vsep())

        for txt, fn, tip in [
            ("Save",   self._save,       "Ctrl+S"),
            ("Load",   self._load,       "Ctrl+O"),
            ("SVG…",   self._import_svg, "Import SVG file"),
        ]:
            b = btn(txt, tip); b.clicked.connect(fn); lay.addWidget(b)

        lay.addStretch()

        self._status_lbl = QLabel("Ready")
        self._status_lbl.setStyleSheet("color: #555; font-size: 11px;")
        lay.addWidget(self._status_lbl)

        lay.addWidget(self._vsep())

        # Plot button — always visible, prominent, far right
        btn_plot_tb = QPushButton("▶  Plot")
        btn_plot_tb.setFixedHeight(30)
        btn_plot_tb.setMinimumWidth(80)
        btn_plot_tb.setToolTip("Switch to Plotter tab and start plotting with preview")
        btn_plot_tb.setStyleSheet(
            "QPushButton{background:#2680eb;color:white;font-weight:bold;"
            "border:none;border-radius:3px;padding:0 16px;}"
            "QPushButton:hover{background:#1473e6;}"
        )
        btn_plot_tb.clicked.connect(self._start_plot)
        lay.addWidget(btn_plot_tb)

        return bar

    @staticmethod
    def _vsep() -> QWidget:
        f = QWidget(); f.setFixedSize(1, 20)
        f.setStyleSheet("background: #333;")
        return f

    # ── paper ─────────────────────────────────────────────────────────────────

    def _apply_paper(self, idx: int):
        if not self._plotter:
            return
        if idx == 0:
            # "From Soft Limits" — use the range defined by x_min/x_max/y_min/y_max
            s = self._plotter.settings
            span_x = s["x_max"] - s["x_min"]
            span_y = s["y_max"] - s["y_min"]
            # Store the effective paper span so get_plotter_paths can use it
            s["_paper_x"] = span_x
            s["_paper_y"] = span_y
            label = (f"Soft limits  {abs(span_x):.0f} × {abs(span_y):.0f} mm")
            self._canvas._bg = None; self._canvas.update()
            self._set_status(label)
        else:
            preset_idx = idx - 1          # offset for the extra "From Soft Limits" item
            if preset_idx >= len(PAPER_PRESETS):
                return
            _, xmax, ymax = PAPER_PRESETS[preset_idx]
            s = self._plotter.settings
            s["x_max"] = xmax; s["y_max"] = ymax
            s.pop("_paper_x", None); s.pop("_paper_y", None)  # clear override
            self._canvas._bg = None; self._canvas.update()
            self._set_status(PAPER_PRESETS[preset_idx][0])

    # ── patterns ──────────────────────────────────────────────────────────────

    def _add_pattern(self, row: int):
        if 0 <= row < len(PRESETS):
            name, _, _, gen = PRESETS[row]
            self._canvas.add_paths_mm(gen(), bed_mm=220.0)
            self._set_status(f"Added {name}")
            self._right._patt_list.clearSelection()

    # ── file I/O ──────────────────────────────────────────────────────────────

    def _save(self):
        path, _ = QFileDialog.getSaveFileName(self, "Save", "", "Plot (*.plot);;JSON (*.json)")
        if path:
            Path(path).write_text(json.dumps(self._canvas.to_json(), indent=2))
            self._set_status(f"Saved  {Path(path).name}")

    def _load(self):
        path, _ = QFileDialog.getOpenFileName(self, "Load", "", "Plot (*.plot);;JSON (*.json)")
        if path:
            try:
                self._canvas.load_json(json.loads(Path(path).read_text()))
                self._set_status(f"Loaded  {Path(path).name}")
            except Exception as exc:
                self._set_status(f"Error: {exc}")

    def _import_svg(self):
        path, _ = QFileDialog.getOpenFileName(self, "Import SVG", "", "SVG (*.svg)")
        if path:
            try:
                paths = parse_svg(path)
                if paths:
                    self._canvas.add_paths_norm(paths)
                    self._set_status(f"Imported {len(paths)} paths")
                else:
                    self._set_status("No paths in SVG")
            except Exception as exc:
                self._set_status(f"SVG error: {exc}")

    # ── plot ──────────────────────────────────────────────────────────────────

    def _start_plot(self):
        paths = self._canvas.get_plotter_paths()
        if not paths:
            self._set_status("Nothing to plot — draw something first")
            return
        self._set_status(f"Sending {len(paths)} paths to Plotter…")
        self.plot_navigate.emit(paths)

    def receive_strokes(self, strokes: list):
        self._canvas.add_paths_norm(strokes)
        self._set_status(f"Received {len(strokes)} stroke(s) from Track")

    def _set_status(self, msg: str):
        self._status_lbl.setText(msg)
