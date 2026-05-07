import os
from PySide6.QtCore import Qt, QTimer, QByteArray
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import QWidget, QVBoxLayout
from PySide6.QtSvg import QSvgRenderer

class SvgPlotWidget(QWidget):
    """Widget that renders an SVG representation of the plotter bed.
    It draws a static rectangle (the bed) and a moving circle that follows the
    live X/Y coordinates reported by the MarlinPlotter.
    """
    def __init__(self, plotter, bed_width=220, bed_height=220, parent=None):
        super().__init__(parent)
        self.plotter = plotter
        self.bed_width = bed_width
        self.bed_height = bed_height
        self.svg_renderer = QSvgRenderer(self)
        self.setMinimumSize(400, 400)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        self.setLayout(layout)
        
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh_svg)
        self.timer.start(100) # Faster updates for smoother motion
        self.refresh_svg()

    def generate_svg(self, x, y):
        # Scale the live coordinates to the widget size
        # We'll use a coordinate system where (0,0) is bottom-left
        w = self.width() - 20
        h = self.height() - 20
        
        # Calculate scaling to fit the bed
        scale = min(w / self.bed_width, h / self.bed_height)
        
        plot_w = self.bed_width * scale
        plot_h = self.bed_height * scale
        
        # Offset to center
        off_x = (w + 20 - plot_w) / 2
        off_y = (h + 20 - plot_h) / 2
        
        # Current position in pixels (flipped Y for SVG coords)
        cur_x = off_x + (x * scale)
        cur_y = off_y + (plot_h - (y * scale))
        
        # Gantry Y (horizontal beam)
        gantry_y = cur_y
        
        # SVG Content
        svg = f"""
        <svg xmlns='http://www.w3.org/2000/svg' width='{self.width()}' height='{self.height()}' viewBox='0 0 {self.width()} {self.height()}'>
            <!-- OUTER FRAME -->
            <rect x='{off_x - 10}' y='{off_y - 10}' width='{plot_w + 20}' height='{plot_h + 20}' fill='#2a2a2a' rx='5'/>
            
            <!-- BED AREA -->
            <rect x='{off_x}' y='{off_y}' width='{plot_w}' height='{plot_h}' fill='#1a1a1a' stroke='#444' stroke-width='1'/>
            
            <!-- GRID LINES -->
            <line x1='{off_x}' y1='{off_y + plot_h/2}' x2='{off_x + plot_w}' y2='{off_y + plot_h/2}' stroke='#333' stroke-width='0.5'/>
            <line x1='{off_x + plot_w/2}' y1='{off_y}' x2='{off_x + plot_w/2}' y2='{off_y + plot_h}' stroke='#333' stroke-width='0.5'/>

            <!-- Y GANTRY (Horizontal Beam moving up/down) -->
            <rect x='{off_x - 5}' y='{gantry_y - 5}' width='{plot_w + 10}' height='10' fill='#444' rx='2' opacity='0.8'/>
            <rect x='{off_x - 5}' y='{gantry_y - 2}' width='{plot_w + 10}' height='4' fill='#222' rx='1'/>

            <!-- X CARRIAGE (Moving left/right on the gantry) -->
            <rect x='{cur_x - 15}' y='{gantry_y - 15}' width='30' height='30' fill='#555' rx='3' stroke='#777' stroke-width='1'/>
            
            <!-- PEN / TOOL -->
            <circle cx='{cur_x}' cy='{gantry_y}' r='4' fill='#3b82f6' stroke='white' stroke-width='1.5'/>
            
            <!-- POSITION LABEL -->
            <text x='{off_x}' y='{off_y - 15}' fill='#60a5fa' font-family='monospace' font-size='12'>X: {x:.1f} Y: {y:.1f}</text>
        </svg>
        """
        return svg.encode('utf-8')

    def refresh_svg(self):
        if self.plotter.connected:
            # Position is updated by the main poll in plotter_panel, 
            # but we can also check here if needed.
            pos = self.plotter.position
        else:
            pos = {"x": 0, "y": 0}
            
        svg_data = self.generate_svg(pos.get('x', 0), pos.get('y', 0))
        self.svg_renderer.load(svg_data)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        if self.svg_renderer.isValid():
            self.svg_renderer.render(painter)
        else:
            painter.fillRect(self.rect(), Qt.black)
