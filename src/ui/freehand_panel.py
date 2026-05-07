from __future__ import annotations
import math

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QButtonGroup, QFrame,
    QLineEdit, QSpinBox,
)
from PySide6.QtCore import Qt, QRectF, QPointF
from PySide6.QtGui import (
    QPainter, QPen, QColor, QBrush, QPixmap, QFont, QPainterPath,
)

BG = QColor("#18181b")
PAPER = QColor("#fafaf8")
GRID = QColor("#dce1e8")
INK = QColor("#1e293b")
LIVE = QColor("#3b82f6")
PAD = 24

# ── Custom Tool Button ────────────────────────────────────────────────────────

class ToolButton(QPushButton):
    def __init__(self, tool_type: str, tip: str, parent=None):
        super().__init__(parent)
        self.tool_type = tool_type
        self.setToolTip(tip)
        self.setCheckable(True)
        self.setFixedSize(36, 36)

    def paintEvent(self, _e):
        # We draw the background via stylesheet (QPushButton:checked etc.)
        # so we call super().paintEvent(None) or just let the style handle it.
        # Actually, for custom drawing on top of a styled button:
        super().paintEvent(_e)
        
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        is_active = self.isChecked() or self.underMouse()
        color = QColor("white") if is_active else QColor("#a1a1aa")
        painter.setPen(QPen(color, 2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        painter.setBrush(Qt.NoBrush)
        
        w, h = self.width(), self.height()
        m = 10 # margin for the icon
        
        if self.tool_type == "select":
            # Arrow icon
            painter.drawLine(m+2, h-m-2, w-m-2, m+2)
            painter.drawLine(w-m-2, m+2, w-m-8, m+2)
            painter.drawLine(w-m-2, m+2, w-m-2, m+8)
        elif self.tool_type == "pen":
            painter.drawLine(m+2, h-m-2, w-m-2, m+2)
            painter.setBrush(QBrush(color))
            painter.drawEllipse(w-m-4, m, 4, 4)
        elif self.tool_type == "line":
            painter.drawLine(m, h-m, w-m, m)
        elif self.tool_type == "rect":
            painter.drawRect(m, m, w-m*2, h-m*2)
        elif self.tool_type == "round_rect":
            painter.drawRoundedRect(m, m, w-m*2, h-m*2, 4, 4)
        elif self.tool_type == "ellipse":
            painter.drawEllipse(m, m, w-m*2, h-m*2)
        elif self.tool_type == "text":
            painter.setFont(QFont("Inter", 20, QFont.Bold))
            painter.drawText(self.rect(), Qt.AlignCenter, "T")
        elif self.tool_type == "triangle":
            path = QPainterPath()
            path.moveTo(w/2, m)
            path.lineTo(w-m, h-m)
            path.lineTo(m, h-m)
            path.closeSubpath()
            painter.drawPath(path)
        elif self.tool_type == "eraser":
            painter.drawRect(m, m+4, w-m*2, h-m*2-8)
            painter.drawLine(m, m+4, m+8, m)
            painter.drawLine(w-m, m+4, w-m-8, m)
            painter.drawLine(m+8, m, w-m-8, m)


# ── Drawing canvas ────────────────────────────────────────────────────────────

class DrawingCanvas(QWidget):

    def __init__(self, plotter):
        super().__init__()
        self.plotter = plotter
        self.setMinimumSize(500, 400)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setCursor(Qt.CrossCursor)

        self.tool = "pen"    # pen | line | rect | ellipse
        self.shapes: list[dict] = []

        self._drawing = False
        self._pts: list[tuple] = []    # pen / polyline in-progress
        self._start: tuple | None = None
        self._mouse: tuple | None = None
        self._selected_idx: int = -1
        self._shift = False

        self._bg: QPixmap | None = None

    # ── public API ────────────────────────────────────────────────────────────

    def set_tool(self, tool: str):
        if self._drawing:
            self._commit_in_progress()
        self.tool = tool
        self._cancel()

    def _commit_in_progress(self):
        # Called when switching tools to save what was being drawn
        if self.tool == "pen" and len(self._pts) > 1:
            self.shapes.append({"type": "pen", "pts": list(self._pts)})
        elif self.tool == "line" and self._mouse:
            end = self._constrain45(self._pts[0], self._mouse) if self._shift else self._mouse
            self.shapes.append({"type": "line", "pts": [self._pts[0], end]})
        elif self.tool in ("rect", "round_rect", "ellipse", "triangle") and self._start and self._mouse:
            end = self._constrainSquare(self._start, self._mouse) if self._shift else self._mouse
            x0, y0 = self._start
            x1, y1 = end
            self.shapes.append({
                "type": self.tool,
                "x": min(x0, x1), "y": min(y0, y1),
                "w": abs(x1 - x0), "h": abs(y1 - y0),
            })

    def undo(self):
        if self._drawing and self.tool == "line" and len(self._pts) > 1:
            self._pts.pop()
        elif self._drawing:
            self._cancel()
        elif self.shapes:
            self.shapes.pop()
        self.update()

    def clear(self):
        self.shapes.clear()
        self._cancel()

    def shapes_as_paths(self) -> list:
        """Return shapes as list of (x,y) paths in plotter mm coords (0–220)."""
        pr = self._paper_rect()
        W, H = pr.width(), pr.height()
        BED = 220.0

        paths = []
        for s in self.shapes:
            t = s["type"]
            if t in ("pen", "line"):
                path = [(nx * BED, (1.0 - ny) * BED) for nx, ny in s["pts"]]
                if len(path) >= 2:
                    paths.append(path)
            elif t in ("rect", "round_rect"):
                x, y, w, h = s["x"], s["y"], s["w"], s["h"]
                corners = [(x, y), (x+w, y), (x+w, y+h), (x, y+h), (x, y)]
                paths.append([(nx * BED, (1-ny) * BED) for nx, ny in corners])
            elif t == "ellipse":
                cx = (s["x"] + s["w"] / 2) * BED
                cy = (1 - s["y"] - s["h"] / 2) * BED
                rx, ry = s["w"] * BED / 2, s["h"] * BED / 2
                n = max(48, int(2 * math.pi * max(rx, ry) / 2))
                pts = [(cx + rx * math.cos(2*math.pi*i/n),
                        cy + ry * math.sin(2*math.pi*i/n)) for i in range(n+1)]
                paths.append(pts)
            elif t == "triangle":
                x, y, w, h = s["x"], s["y"], s["w"], s["h"]
                pts = [(x + w/2, y), (x+w, y+h), (x, y+h), (x + w/2, y)]
                paths.append([(nx * BED, (1-ny) * BED) for nx, ny in pts])
            elif t == "text":
                # Convert font to path
                font = QFont("Arial", s["size"])
                font.setBold(s["bold"])
                font.setItalic(s["italic"])
                path = QPainterPath()
                path.addText(s["x"] * BED, (1-s["y"]) * BED, font, s["text"])
                # Extract points from path
                for poly in path.toSubpathPolygons():
                    p_list = []
                    for i in range(poly.count()):
                        pt = poly.at(i)
                        p_list.append((pt.x(), pt.y()))
                    if p_list:
                        paths.append(p_list)
        return paths

    # ── coordinate helpers ────────────────────────────────────────────────────

    def _paper_rect(self) -> QRectF:
        return QRectF(PAD, PAD, self.width() - PAD*2, self.height() - PAD*2)

    def _norm(self, qpoint) -> tuple:
        pr = self._paper_rect()
        return (max(0.0, min(1.0, (qpoint.x() - pr.x()) / pr.width())),
                max(0.0, min(1.0, (qpoint.y() - pr.y()) / pr.height())))

    def _px(self, nx: float, ny: float) -> tuple:
        pr = self._paper_rect()
        return int(pr.x() + nx * pr.width()), int(pr.y() + ny * pr.height())

    @staticmethod
    def _constrain45(origin: tuple, target: tuple) -> tuple:
        dx, dy = target[0] - origin[0], target[1] - origin[1]
        dist = math.hypot(dx, dy)
        angle = round(math.atan2(dy, dx) / (math.pi / 4)) * (math.pi / 4)
        return origin[0] + dist * math.cos(angle), origin[1] + dist * math.sin(angle)

    @staticmethod
    def _constrainSquare(origin: tuple, target: tuple) -> tuple:
        dx, dy = target[0] - origin[0], target[1] - origin[1]
        s = max(abs(dx), abs(dy))
        return origin[0] + math.copysign(s, dx), origin[1] + math.copysign(s, dy)

    # ── internal ──────────────────────────────────────────────────────────────

    def _cancel(self):
        self._drawing = False
        self._pts = []
        self._start = None
        self._selected_idx = -1
        self.update()

    def _hit_test(self, nx, ny):
        # Return index of topmost shape containing point
        for i in range(len(self.shapes)-1, -1, -1):
            s = self.shapes[i]
            t = s["type"]
            if t in ("rect", "round_rect", "ellipse", "triangle"):
                if s["x"] <= nx <= s["x"] + s["w"] and s["y"] <= ny <= s["y"] + s["h"]:
                    return i
            elif t == "text":
                # Simple box hit test for text
                if s["x"] <= nx <= s["x"] + 0.2 and s["y"] - 0.05 <= ny <= s["y"]:
                    return i
            else:
                # For pen/line, check proximity to any point
                for px, py in s["pts"]:
                    if math.hypot(px - nx, py - ny) < 0.02:
                        return i
        return -1

    def _finish_line(self):
        if len(self._pts) >= 2:
            self.shapes.append({"type": "line", "pts": list(self._pts)})
        self._cancel()

    # ── events ────────────────────────────────────────────────────────────────

    def resizeEvent(self, _e):
        super().resizeEvent(_e)
        self._bg = None

    def keyPressEvent(self, e):
        self._shift = bool(e.modifiers() & Qt.ShiftModifier)
        k = e.key()
        if k == Qt.Key_Escape:
            self._cancel()
        elif k in (Qt.Key_Return, Qt.Key_Enter) and self.tool == "line":
            self._finish_line()
        elif e.modifiers() & Qt.ControlModifier and k == Qt.Key_Z:
            self.undo()
        super().keyPressEvent(e)

    def keyReleaseEvent(self, e):
        self._shift = bool(e.modifiers() & Qt.ShiftModifier)
        self.update()
        super().keyReleaseEvent(e)

    def mousePressEvent(self, e):
        if e.button() != Qt.LeftButton:
            return
        self.setFocus()
        pos = self._norm(e.pos())

        if self.tool == "select":
            idx = self._hit_test(*pos)
            if idx != -1:
                self._drawing = True
                self._selected_idx = idx
                self._start = pos # for relative movement
        elif self.tool == "text":
            self.shapes.append({
                "type": "text",
                "x": pos[0], "y": pos[1],
                "text": self.parent()._text_bar.input.text(),
                "size": self.parent()._text_bar.size.value(),
                "bold": self.parent()._text_bar.btn_bold.isChecked(),
                "italic": self.parent()._text_bar.btn_italic.isChecked(),
            })
            self.update()
        elif self.tool == "eraser":
            idx = self._hit_test(*pos)
            if idx != -1:
                self.shapes.pop(idx)
                self.update()
        elif self.tool == "pen":
            self._drawing = True
            self._pts = [pos]
        elif self.tool == "line":
            self._drawing = True
            self._start = pos
            self._pts = [pos]
        elif self.tool in ("rect", "round_rect", "ellipse", "triangle"):
            self._drawing = True
            self._start = pos

    def mouseMoveEvent(self, e):
        self._shift = bool(e.modifiers() & Qt.ShiftModifier)
        self._mouse = self._norm(e.pos())
        if self._drawing:
            if self.tool == "select" and self._selected_idx != -1:
                dx = self._mouse[0] - self._start[0]
                dy = self._mouse[1] - self._start[1]
                s = self.shapes[self._selected_idx]
                if "pts" in s:
                    s["pts"] = [(px + dx, py + dy) for px, py in s["pts"]]
                else:
                    s["x"] += dx
                    s["y"] += dy
                self._start = self._mouse # reset for next relative move
            elif self.tool == "pen":
                self._pts.append(self._mouse)
        self.update()

    def mouseReleaseEvent(self, e):
        if self.tool == "select" and self._drawing:
            self._drawing = False
            self._selected_idx = -1
        elif self.tool == "pen" and self._drawing:
            self.shapes.append({"type": "pen", "pts": list(self._pts)})
            self._cancel()
        elif self.tool == "line" and self._drawing:
            end = self._constrain45(self._pts[0], pos) if self._shift else pos
            self.shapes.append({"type": "line", "pts": [self._pts[0], end]})
            self._cancel()
        elif self.tool in ("rect", "round_rect", "ellipse", "triangle") and self._drawing:
            end = self._constrainSquare(self._start, pos) if self._shift else pos
            x0, y0 = self._start
            x1, y1 = end
            self.shapes.append({
                "type": self.tool,
                "x": min(x0, x1), "y": min(y0, y1),
                "w": abs(x1 - x0), "h": abs(y1 - y0),
            })
            self._drawing = False
            self._start = None

    def mouseDoubleClickEvent(self, e):
        if e.button() == Qt.LeftButton and self.tool == "line" and self._drawing:
            self._finish_line()

    # ── background cache ──────────────────────────────────────────────────────

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
            p.drawRoundedRect(QRectF(pr.x() + i*.5, pr.y() + i*.7, pr.width(), pr.height()), 4, 4)
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

    # ── paint ─────────────────────────────────────────────────────────────────

    def paintEvent(self, _e):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        pr = self._paper_rect()

        painter.drawPixmap(0, 0, self._get_bg())

        # ── Draw Soft Limits ──────────────────────────────────────────────────
        s = self.plotter.settings
        if s.get("soft_limits", True):
            # Normal bed is 0-220
            BED = 220.0
            lx, rx = s["x_min"] / BED, s["x_max"] / BED
            ty, by = s["y_min"] / BED, s["y_max"] / BED
            
            px, py = self._px(lx, ty)
            pw = int((rx - lx) * pr.width())
            ph = int((by - ty) * pr.height())
            
            limit_pen = QPen(QColor("#3b82f6"), 1, Qt.DashLine)
            painter.setPen(limit_pen)
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(px, py, pw, ph)
            
            painter.setFont(QFont("Inter", 8))
            painter.drawText(px + 4, py + ph - 4, "SOFT LIMITS ACTIVE")

        clip = QPainterPath()
        clip.addRoundedRect(pr, 4, 4)
        painter.setClipPath(clip)

        ink_pen = QPen(INK, 2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
        painter.setPen(ink_pen)
        painter.setBrush(Qt.NoBrush)
        for s in self.shapes:
            self._draw_shape(painter, s, pr)

        live_pen = QPen(LIVE, 2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
        painter.setPen(live_pen)

        if self._drawing:
            m = self._mouse

            if self.tool in ("pen", "line") and self._pts:
                self._draw_polyline(painter, self._pts)
                if self.tool == "line" and m:
                    end = self._constrain45(self._pts[0], m) if self._shift else m
                    dash = QPen(LIVE, 1.5, Qt.DashLine)
                    painter.setPen(dash)
                    x1, y1 = self._px(*self._pts[0])
                    x2, y2 = self._px(*end)
                    painter.drawLine(x1, y1, x2, y2)
                    painter.setPen(live_pen)
                    painter.setBrush(QBrush(LIVE))
                    painter.setPen(Qt.NoPen)
                    # Start point dot
                    px, py = self._px(*self._pts[0])
                    painter.drawEllipse(px - 3, py - 3, 6, 6)
                    painter.setBrush(Qt.NoBrush)
                    painter.setPen(live_pen)

            elif self.tool in ("rect", "round_rect", "ellipse", "triangle") and self._start and m:
                end = self._constrainSquare(self._start, m) if self._shift else m
                x0, y0, x1, y1 = self._start[0], self._start[1], end[0], end[1]
                px0, py0 = self._px(min(x0, x1), min(y0, y1))
                pw = int(abs(x1 - x0) * pr.width())
                ph = int(abs(y1 - y0) * pr.height())
                if self.tool in ("rect", "round_rect"):
                    painter.drawRoundedRect(px0, py0, pw, ph, 8 if self.tool=="round_rect" else 0, 8 if self.tool=="round_rect" else 0)
                elif self.tool == "ellipse":
                    painter.drawEllipse(px0, py0, pw, ph)
                elif self.tool == "triangle":
                    path = QPainterPath()
                    path.moveTo(px0 + pw/2, py0)
                    path.lineTo(px0 + pw, py0 + ph)
                    path.lineTo(px0, py0 + ph)
                    path.closeSubpath()
                    painter.drawPath(path)

        painter.setClipping(False)

        # Tool cursor dot at mouse position
        if self._mouse:
            mx, my = self._px(*self._mouse)
            painter.setBrush(QBrush(LIVE))
            painter.setPen(Qt.NoPen)
            painter.drawEllipse(mx - 3, my - 3, 6, 6)

    def _draw_shape(self, painter, s, pr):
        t = s["type"]
        if t in ("pen", "line"):
            self._draw_polyline(painter, s["pts"])
        elif t in ("rect", "round_rect"):
            x, y = self._px(s["x"], s["y"])
            painter.drawRoundedRect(x, y, int(s["w"] * pr.width()), int(s["h"] * pr.height()), 
                                    8 if t=="round_rect" else 0, 8 if t=="round_rect" else 0)
        elif t == "ellipse":
            x, y = self._px(s["x"], s["y"])
            painter.drawEllipse(x, y, int(s["w"] * pr.width()), int(s["h"] * pr.height()))
        elif t == "triangle":
            x, y = self._px(s["x"], s["y"])
            w, h = int(s["w"] * pr.width()), int(s["h"] * pr.height())
            path = QPainterPath()
            path.moveTo(x + w/2, y)
            path.lineTo(x + w, y + h)
            path.lineTo(x, y + h)
            path.closeSubpath()
            painter.drawPath(path)
        elif t == "text":
            font = QFont("Arial", s["size"] * (pr.width() / 220.0))
            font.setBold(s["bold"])
            font.setItalic(s["italic"])
            painter.setFont(font)
            painter.drawText(self._px(s["x"], s["y"])[0], self._px(s["x"], s["y"])[1], s["text"])

    def _draw_polyline(self, painter, pts):
        for i in range(1, len(pts)):
            x1, y1 = self._px(*pts[i-1])
            x2, y2 = self._px(*pts[i])
            painter.drawLine(x1, y1, x2, y2)


# ── Text Settings Bar ──────────────────────────────────────────────────────────

class TextSettingsBar(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(48)
        self.setStyleSheet("background: #1e293b; border-bottom: 1px solid #334155;")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 0, 10, 0)
        
        lay.addWidget(QLabel("Text:"))
        self.input = QLineEdit("Hello Plotter")
        self.input.setFixedWidth(150)
        self.input.setStyleSheet("background: #0f172a; color: white; border: 1px solid #334155; border-radius: 4px; padding: 4px 8px;")
        lay.addWidget(self.input)
        
        lay.addWidget(QLabel("Size:"))
        self.size = QSpinBox()
        self.size.setRange(5, 100)
        self.size.setValue(20)
        self.size.setFixedWidth(60)
        lay.addWidget(self.size)
        
        self.btn_bold = QPushButton("B")
        self.btn_bold.setCheckable(True)
        self.btn_bold.setFixedSize(28, 28)
        self.btn_bold.setStyleSheet("QPushButton { background: #334155; font-weight: bold; border-radius: 4px; } QPushButton:checked { background: #3b82f6; color: white; }")
        lay.addWidget(self.btn_bold)
        
        self.btn_italic = QPushButton("I")
        self.btn_italic.setCheckable(True)
        self.btn_italic.setFixedSize(32, 32)
        self.btn_italic.setStyleSheet("QPushButton { background: #334155; font-style: italic; border-radius: 4px; } QPushButton:checked { background: #3b82f6; color: white; }")
        lay.addWidget(self.btn_italic)
        
        lay.addStretch()

# ── Panel ─────────────────────────────────────────────────────────────────────

class FreehandPanel(QWidget):
    def __init__(self, plotter):
        super().__init__()
        self.plotter = plotter
        self._canvas = DrawingCanvas(plotter)
        self._text_bar = TextSettingsBar()
        self._text_bar.hide()
        self._build_ui()

    def _set_tool(self, tool):
        self._canvas.set_tool(tool)
        self._text_bar.setVisible(tool == "text")

    def _build_ui(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Illustrator-style sidebar ─────────────────────────────────────────
        sidebar = QFrame()
        sidebar.setFixedWidth(50)
        sidebar.setStyleSheet("""
            QFrame { background: #1e293b; border-right: 1px solid #334155; }
            QPushButton { 
                background: transparent; border: 1px solid transparent; border-radius: 6px; 
                margin: 4px;
            }
            QPushButton:hover { background: #334155; border-color: #475569; }
            QPushButton:checked { background: #3b82f6; border-color: #60a5fa; }
        """)
        slay = QVBoxLayout(sidebar)
        slay.setContentsMargins(4, 10, 4, 10)
        slay.setSpacing(8)

        group = QButtonGroup(self)
        tools = [
            ("select",  "Select / Move (V)"),
            ("pen",     "Pen Tool (P)"),
            ("line",    "Line Tool (L)"),
            ("text",    "Text Tool (T)"),
            ("rect",    "Rectangle Tool (M)"),
            ("round_rect", "Rounded Rectangle"),
            ("ellipse", "Ellipse Tool (L)"),
            ("triangle", "Triangle Tool"),
            ("eraser",  "Eraser Tool"),
        ]
        for tool, tip in tools:
            b = ToolButton(tool, tip)
            if tool == "select": b.setChecked(True)
            b.clicked.connect(lambda _, t=tool: self._set_tool(t))
            group.addButton(b)
            slay.addWidget(b)
        
        # Set initial tool to select
        self._set_tool("select")

        slay.addStretch()

        root.addWidget(sidebar)

        # ── central area ──────────────────────────────────────────────────────
        center = QWidget()
        clay = QVBoxLayout(center)
        clay.setContentsMargins(0, 0, 0, 0)
        clay.setSpacing(0)

        # ── top toolbar ───────────────────────────────────────────────────────
        header = QFrame()
        header.setFixedHeight(54)
        header.setStyleSheet("background: #0f172a; border-bottom: 1px solid #1e293b;")
        hlay = QHBoxLayout(header)
        hlay.setContentsMargins(14, 0, 14, 0)
        hlay.setSpacing(8)
        
        # Undo / Clear on top again
        for label, slot in [("↩ Undo", self._canvas.undo), ("× Clear", self._canvas.clear)]:
            b = QPushButton(label)
            b.setStyleSheet("""
                QPushButton { background: #1e293b; border: 1px solid #334155; border-radius: 4px; padding: 6px 14px; font-size: 12px; }
                QPushButton:hover { background: #334155; border-color: #475569; }
            """)
            b.clicked.connect(slot)
            hlay.addWidget(b)

        hlay.addStretch()
        
        self.lbl_hint = QLabel("Pen: drag  ·  Line: drag  ·  Shift=constrain  ·  Ctrl+Z=undo")
        self.lbl_hint.setStyleSheet("color: #64748b; font-size: 11px; font-weight: 500;")
        hlay.addWidget(self.lbl_hint)
        hlay.addStretch()

        btn_plot = QPushButton("▶  Plot Pattern")
        btn_plot.setObjectName("btnPrimary")
        btn_plot.setStyleSheet("""
            QPushButton { 
                padding: 8px 24px;
                font-size: 13px;
            }
        """)
        btn_plot.clicked.connect(self._plot)
        hlay.addWidget(btn_plot)

        clay.addWidget(header)
        clay.addWidget(self._text_bar)
        clay.addWidget(self._canvas, stretch=1)

        root.addWidget(center)

    def _plot(self):
        if not self.plotter.connected:
            return
        for path in self._canvas.shapes_as_paths():
            if not path:
                continue
            self.plotter.send_gcode("G90")
            self.plotter.send_gcode("G0 Z5")
            self.plotter.send_gcode(f"G0 X{path[0][0]:.2f} Y{path[0][1]:.2f} F3000")
            self.plotter.send_gcode("G0 Z-2")
            for x, y in path[1:]:
                self.plotter.send_gcode(f"G1 X{x:.2f} Y{y:.2f} F1500")
        self.plotter.send_gcode("G0 Z5")
