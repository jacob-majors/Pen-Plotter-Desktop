from __future__ import annotations
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QPushButton, QStackedWidget, QLabel, QFrame, QButtonGroup,
)
from PySide6.QtCore import Qt, QTimer

from ui.draw_panel import DrawPanel
from ui.ai_panel import AIPanel
from ui.plotter_panel import PlotterPanel
from ui.cv_controller_panel import CvControllerPanel
from core.marlin_serial import MarlinPlotter
from core.arduino_controller import ArduinoController


class PlotterApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PlotterOS Desktop")
        self.resize(1280, 800)

        self.plotter = MarlinPlotter()
        self.arduino = ArduinoController()
        self.plotter.arduino = self.arduino
        self.arduino.estop_triggered.connect(self._trigger_estop)

        self.active_keys: set = set()
        self.jog_timer = QTimer(self)
        self.jog_timer.timeout.connect(self._process_jog)
        self.jog_timer.start(100)

        root = QWidget()
        self.setCentralWidget(root)
        self._root_layout = QVBoxLayout(root)
        self._root_layout.setContentsMargins(0, 0, 0, 0)
        self._root_layout.setSpacing(0)

        self._root_layout.addWidget(self._build_topbar())
        self._root_layout.addWidget(self._build_estop_banner())
        self._root_layout.addWidget(self._build_body(), stretch=1)

        self.cv_controller_panel.strokes_sent.connect(self.draw_panel.receive_strokes)

    def _build_topbar(self) -> QFrame:
        bar = QFrame()
        bar.setObjectName("TopBar")
        bar.setFixedHeight(50)
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(16, 0, 16, 0)
        lay.setSpacing(4)
        nav_group = QButtonGroup(self)
        for i, (text, idx) in enumerate([("Draw",0),("AI",1),("Plotter",2),("Track",3)]):
            btn = QPushButton(text)
            btn.setObjectName("BtnTopNav")
            btn.setCheckable(True)
            btn.setChecked(i == 0)
            btn.clicked.connect(lambda _, ix=idx: self.stack.setCurrentIndex(ix))
            nav_group.addButton(btn)
            lay.addWidget(btn)
        lay.addStretch()
        self._btn_estop = QPushButton("⏹  E-STOP")
        self._btn_estop.setFixedHeight(34)
        self._btn_estop.setStyleSheet(
            "QPushButton{background:#7f1d1d;color:#fca5a5;border:2px solid #ef4444;"
            "border-radius:5px;padding:0 18px;font-weight:bold;font-size:13px;}"
            "QPushButton:hover{background:#991b1b;}"
        )
        self._btn_estop.clicked.connect(self._trigger_estop)
        lay.addWidget(self._btn_estop)
        return bar

    def _build_estop_banner(self) -> QFrame:
        self._estop_banner = QFrame()
        self._estop_banner.setFixedHeight(46)
        self._estop_banner.setStyleSheet("background:#450a0a;border-bottom:2px solid #ef4444;")
        lay = QHBoxLayout(self._estop_banner)
        lay.setContentsMargins(16, 0, 16, 0)
        lay.addWidget(QLabel("⛔", styleSheet="font-size:18px;"))
        msg = QLabel("E-STOP ACTIVE — All motion halted.  Resolve the stop condition before resetting.")
        msg.setStyleSheet("color:#fca5a5;font-weight:bold;font-size:13px;")
        lay.addWidget(msg)
        lay.addStretch()
        btn_reset = QPushButton("Reset  (M999)")
        btn_reset.setStyleSheet("background:#ef4444;color:white;font-weight:bold;border-radius:4px;padding:5px 18px;")
        btn_reset.clicked.connect(self._reset_estop)
        lay.addWidget(btn_reset)
        self._estop_banner.setVisible(False)
        return self._estop_banner

    def _build_body(self) -> QWidget:
        body = QWidget()
        lay = QHBoxLayout(body)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.stack = QStackedWidget()
        lay.addWidget(self.stack)
        self.draw_panel          = DrawPanel(self.plotter)
        self.ai_panel            = AIPanel(self.plotter)
        self.plotter_panel       = PlotterPanel(self.plotter, self.arduino)
        self.cv_controller_panel = CvControllerPanel(self.plotter)
        for p in (self.draw_panel, self.ai_panel, self.plotter_panel, self.cv_controller_panel):
            self.stack.addWidget(p)
        return body

    def _trigger_estop(self):
        self.plotter.emergency_stop()
        self._estop_banner.setVisible(True)
        self._btn_estop.setStyleSheet(
            "QPushButton{background:#450a0a;color:#fca5a5;border:2px solid #ef4444;"
            "border-radius:5px;padding:0 18px;font-weight:bold;font-size:13px;}"
        )
        self._btn_estop.setEnabled(False)

    def _reset_estop(self):
        self.plotter.reset_estop()
        self._estop_banner.setVisible(False)
        self._btn_estop.setEnabled(True)
        self._btn_estop.setStyleSheet(
            "QPushButton{background:#7f1d1d;color:#fca5a5;border:2px solid #ef4444;"
            "border-radius:5px;padding:0 18px;font-weight:bold;font-size:13px;}"
            "QPushButton:hover{background:#991b1b;}"
        )

    def keyPressEvent(self, event):
        if event.isAutoRepeat(): return
        if event.key() in (Qt.Key_Up, Qt.Key_Down, Qt.Key_Left, Qt.Key_Right):
            self.active_keys.add(event.key())
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event):
        if event.isAutoRepeat(): return
        if event.key() in (Qt.Key_Up, Qt.Key_Down, Qt.Key_Left, Qt.Key_Right):
            self.active_keys.discard(event.key())
        super().keyReleaseEvent(event)

    def _process_jog(self):
        if not self.active_keys or not self.plotter.connected or self.plotter.estop_active:
            return
        dx = dy = 0
        if Qt.Key_Up    in self.active_keys: dy =  5
        if Qt.Key_Down  in self.active_keys: dy = -5
        if Qt.Key_Right in self.active_keys: dx =  5
        if Qt.Key_Left  in self.active_keys: dx = -5
        if dx or dy:
            self.plotter.jog_continuous(dx, dy)
