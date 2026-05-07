from __future__ import annotations
import threading
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QComboBox, QGridLayout, QSizePolicy, QTabWidget, QFrame,
    QDoubleSpinBox, QSpinBox, QCheckBox, QGroupBox, QTextEdit,
    QProgressBar,
)
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QPainter, QColor, QPen, QBrush, QFont
from core.arduino_controller import ArduinoController, ARDUINO_SKETCH


# ── bed position widget ───────────────────────────────────────────────────────

class BedWidget(QWidget):
    def __init__(self, plotter):
        super().__init__()
        self.plotter = plotter
        self.setMinimumSize(240, 240)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        # Set by start_plot_preview — list of mm-coord paths
        self.preview_paths: list = []
        self.preview_done: int = 0   # how many paths are fully plotted

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        s = self.plotter.settings
        bed_w = s["x_max"] - s["x_min"] or 1
        bed_h = s["y_max"] - s["y_min"] or 1
        pad = 20
        
        # Calculate scale to fit bed in widget while keeping aspect ratio
        ratio_bed = bed_w / bed_h
        ratio_widget = w / h
        
        if ratio_bed > ratio_widget:
            draw_w = w - pad * 2
            draw_h = draw_w / ratio_bed
        else:
            draw_h = h - pad * 2
            draw_w = draw_h * ratio_bed
            
        dx = (w - draw_w) / 2
        dy = (h - draw_h) / 2
        
        p.setPen(QPen(QColor("#2a2a2a"), 1))
        p.setBrush(QBrush(QColor("#1e1e1e")))
        p.drawRect(dx, dy, draw_w, draw_h)
        
        # Grid dots
        p.setPen(QPen(QColor("#2d2d2d"), 1))
        steps = 10
        for i in range(1, steps):
            gx = dx + (i / steps) * draw_w
            gy = dy + (i / steps) * draw_h
            p.drawLine(int(gx), int(dy), int(gx), int(dy + draw_h))
            p.drawLine(int(dx), int(gy), int(dx + draw_w), int(gy))

        # ── Drawing preview ───────────────────────────────────────────────────
        if self.preview_paths:
            def _mm_to_px(x_mm, y_mm):
                nx = (x_mm - s["x_min"]) / bed_w
                ny = (y_mm - s["y_min"]) / bed_h
                return int(dx + nx * draw_w), int(dy + (1 - ny) * draw_h)

            # Pending paths (very faint)
            p.setPen(QPen(QColor("#303030"), 1))
            for path in self.preview_paths[self.preview_done:]:
                for i in range(1, len(path)):
                    x1, y1 = _mm_to_px(*path[i-1])
                    x2, y2 = _mm_to_px(*path[i])
                    p.drawLine(x1, y1, x2, y2)

            # Completed paths (bright ink blue)
            p.setPen(QPen(QColor("#1a5fa8"), 1.5))
            for path in self.preview_paths[:self.preview_done]:
                for i in range(1, len(path)):
                    x1, y1 = _mm_to_px(*path[i-1])
                    x2, y2 = _mm_to_px(*path[i])
                    p.drawLine(x1, y1, x2, y2)

        # ── Current position ──────────────────────────────────────────────────
        pos = self.plotter.position
        nx = (pos["x"] - s["x_min"]) / bed_w
        ny = (pos["y"] - s["y_min"]) / bed_h
        px = int(dx + nx * draw_w)
        py = int(dy + (1-ny) * draw_h)
        
        p.setPen(QPen(QColor(38, 128, 235, 55), 1))
        p.drawLine(px, int(dy), px, int(dy + draw_h))
        p.drawLine(int(dx), py, int(dx + draw_w), py)
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(QColor("#ef4444")))
        p.drawEllipse(px-5, py-5, 10, 10)
        p.setBrush(QBrush(QColor("white")))
        p.drawEllipse(px-2, py-2, 4, 4)
        p.setPen(QColor("#555"))
        p.setFont(QFont("Arial", 9))
        p.drawText(int(dx + 6), int(dy + draw_h - 4), f"{pos['x']:.1f}, {pos['y']:.1f} mm")


# ── panel ─────────────────────────────────────────────────────────────────────

class PlotterPanel(QWidget):
    # Cross-thread plot-progress signals
    _plot_prog = Signal(int, int)   # (current, total)
    _plot_done = Signal(bool)       # success / cancelled

    def __init__(self, plotter, arduino: ArduinoController | None = None):
        super().__init__()
        self.plotter  = plotter
        self.arduino  = arduino
        self._polling = False
        self._plot_cancel = threading.Event()

        self._plot_prog.connect(self._on_plot_prog)
        self._plot_done.connect(self._on_plot_done)

        if arduino:
            arduino.connected_changed.connect(self._on_arduino_connected)
            arduino.status_changed.connect(self._on_arduino_status)

        self.setFocusPolicy(Qt.StrongFocus)
        self._pen_down_active = False

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        tabs = QTabWidget()
        tabs.addTab(self._controls_tab(), "Controls")
        tabs.addTab(self._settings_tab(), "Settings")
        # Refresh all port dropdowns whenever Settings tab is opened
        tabs.currentChanged.connect(self._on_tab_changed)
        root.addWidget(tabs)

        # Poll every 500 ms — UI update is instant (cached), serial is background
        self._pos_timer = QTimer(self)
        self._pos_timer.timeout.connect(self._poll_position)
        self._pos_timer.start(500)

        # Auto-connect timer (every 3 seconds)
        self._auto_timer = QTimer(self)
        self._auto_timer.timeout.connect(self._auto_connect)
        self._auto_timer.start(3000)

    # ── Controls tab ──────────────────────────────────────────────────────────

    def _controls_tab(self) -> QWidget:
        w = QWidget()
        lay = QHBoxLayout(w)
        lay.setContentsMargins(20, 20, 20, 20)
        lay.setSpacing(24)

        left = QVBoxLayout()
        left.setSpacing(14)

        # Connection
        conn = QGroupBox("CONNECTION")
        cl = QVBoxLayout(conn)
        cr = QHBoxLayout()
        self._port_menu = QComboBox()
        self._refresh_ports()
        cr.addWidget(self._port_menu, 1)
        btn_ref = QPushButton("⟳")
        btn_ref.setFixedWidth(30)
        btn_ref.clicked.connect(self._refresh_ports)
        cr.addWidget(btn_ref)
        cl.addLayout(cr)
        self._btn_connect = QPushButton("Connect")
        self._btn_connect.setStyleSheet(
            "QPushButton{background:#2d6a3f;color:white;font-weight:bold;"
            "border:none;border-radius:3px;padding:7px;}"
            "QPushButton:hover{background:#38854f;}"
        )
        self._btn_connect.clicked.connect(self._toggle_connect)
        cl.addWidget(self._btn_connect)
        self._lbl_status = QLabel("Disconnected")
        self._lbl_status.setAlignment(Qt.AlignCenter)
        self._lbl_status.setStyleSheet("color:#606060;font-size:11px;")
        cl.addWidget(self._lbl_status)
        left.addWidget(conn)

        # Movement
        mov = QGroupBox("MOVEMENT")
        ml = QHBoxLayout(mov)
        ml.setSpacing(12)
        grid = QGridLayout()
        grid.setSpacing(4)

        def jbtn(text, dx, dy):
            b = QPushButton(text)
            b.setFixedSize(46, 38)
            b.clicked.connect(lambda: self.plotter.jog(dx, dy))
            return b

        grid.addWidget(jbtn("Y+", 0, 10), 0, 1)
        grid.addWidget(jbtn("X−", -10, 0), 1, 0)
        home_btn = QPushButton("⌂")
        home_btn.setFixedSize(46, 38)
        home_btn.setStyleSheet(
            "QPushButton{border:1px solid #2680eb;color:#2680eb;border-radius:3px;}"
            "QPushButton:hover{background:#1a3a5a;color:white;}"
        )
        home_btn.clicked.connect(self.plotter.home)
        grid.addWidget(home_btn, 1, 1)
        grid.addWidget(jbtn("X+", 10, 0), 1, 2)
        grid.addWidget(jbtn("Y−", 0, -10), 2, 1)
        ml.addLayout(grid)

        z = QVBoxLayout()
        z.setSpacing(3)
        for text, action in [
            ("↑ Up",   self._toggle_pen_ui_up),
            ("↓ Dn",   self._toggle_pen_ui_down),
        ]:
            b = QPushButton(text)
            b.setFixedSize(46, 38)
            b.setStyleSheet("font-size:11px; font-weight:bold;")
            b.clicked.connect(action)
            z.addWidget(b)
        ml.addLayout(z)
        left.addWidget(mov)

        # Coordinates
        coord = QGroupBox("COORDINATES")
        coordl = QVBoxLayout(coord)
        self._lbl_pos = QLabel("X:  0.00   Y:  0.00   Z:  0.00")
        self._lbl_pos.setStyleSheet(
            "font-family:monospace;font-size:14px;color:#4ade80;padding:8px 0;"
        )
        self._lbl_pos.setAlignment(Qt.AlignCenter)
        coordl.addWidget(self._lbl_pos)
        left.addWidget(coord)

        # ── Plot progress (hidden when idle) ──────────────────────────────────
        self._prog_bar = QProgressBar()
        self._prog_bar.setVisible(False)
        self._prog_bar.setMaximumHeight(4)
        left.addWidget(self._prog_bar)

        self._prog_lbl = QLabel("")
        self._prog_lbl.setStyleSheet("color:#787878;font-size:10px;")
        self._prog_lbl.setVisible(False)
        left.addWidget(self._prog_lbl)

        btn_row = QHBoxLayout()
        self._btn_cancel_plot = QPushButton("Cancel Plot")
        self._btn_cancel_plot.setVisible(False)
        self._btn_cancel_plot.setStyleSheet(
            "QPushButton{border:1px solid #ef4444;color:#ef4444;border-radius:3px;padding:4px 10px;}"
            "QPushButton:hover{background:#7f1d1d;color:white;}"
        )
        self._btn_cancel_plot.clicked.connect(lambda: self._plot_cancel.set())
        btn_row.addWidget(self._btn_cancel_plot)
        btn_row.addStretch()
        left.addLayout(btn_row)

        left.addStretch()
        
        # Arduino Leonardo controls moved here
        if self.arduino:
            ard_grp = QGroupBox("PEN LIFT / ARDUINO")
            al = QVBoxLayout(ard_grp)
            
            ap = QHBoxLayout()
            self._ard_port_controls = QComboBox()
            self._refresh_ard_ports_controls()
            ap.addWidget(self._ard_port_controls, 1)
            btn_ref_ard = QPushButton("⟳")
            btn_ref_ard.setFixedWidth(30)
            btn_ref_ard.clicked.connect(self._refresh_ard_ports_controls)
            ap.addWidget(btn_ref_ard)
            al.addLayout(ap)
            
            self._btn_ard_connect_controls = QPushButton("Connect Arduino")
            self._btn_ard_connect_controls.setCheckable(True)
            self._btn_ard_connect_controls.setStyleSheet(
                "QPushButton{background:#334155;color:white;font-weight:bold;padding:6px;border-radius:3px;}"
                "QPushButton:checked{background:#3b82f6;}"
            )
            self._btn_ard_connect_controls.clicked.connect(self._toggle_arduino_controls)
            al.addWidget(self._btn_ard_connect_controls)
            
            self._ard_status_controls = QLabel("Arduino not connected")
            self._ard_status_controls.setStyleSheet("color:#606060;font-size:10px;")
            al.addWidget(self._ard_status_controls)
            
            left.addWidget(ard_grp)

        lay.addLayout(left, 0)

        right = QVBoxLayout()
        bed_grp = QGroupBox("BED PREVIEW")
        bed_l = QVBoxLayout(bed_grp)
        self._bed = BedWidget(self.plotter)
        bed_l.addWidget(self._bed)
        right.addWidget(bed_grp)
        lay.addLayout(right, 1)
        return w

    # ── Settings tab ──────────────────────────────────────────────────────────

    def _settings_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(20, 16, 20, 16)
        lay.setSpacing(14)

        s = self.plotter.settings

        def grp(title): return QGroupBox(title)

        def dbl(val, lo, hi, step=0.5, suffix=" mm"):
            sb = QDoubleSpinBox()
            sb.setRange(lo, hi); sb.setValue(val)
            sb.setSingleStep(step); sb.setSuffix(suffix)
            sb.setFixedWidth(108)
            return sb

        def spin(val, lo, hi, suffix=""):
            sb = QSpinBox()
            sb.setRange(lo, hi); sb.setValue(val)
            if suffix: sb.setSuffix(suffix)
            sb.setFixedWidth(108)
            return sb

        # ── Soft limits — capture-from-position ───────────────────────────────
        g_lim = grp("SOFT LIMITS")
        gl = QVBoxLayout(g_lim)
        gl.setSpacing(10)

        self._chk_limits = QCheckBox("Enable software clamping")
        self._chk_limits.setChecked(s.get("soft_limits", True))
        self._chk_limits.stateChanged.connect(
            lambda _: self._instant_save_limits()
        )
        gl.addWidget(self._chk_limits)

        tip = QLabel("Jog to a position, then click a button to capture it as a limit.")
        tip.setStyleSheet("color:#484848;font-size:10px;")
        tip.setWordWrap(True)
        gl.addWidget(tip)

        # Live "current position" readout inside this group
        self._lbl_lim_cur = QLabel("Current:  X 0.00   Y 0.00")
        self._lbl_lim_cur.setStyleSheet(
            "color:#888;font-family:monospace;font-size:11px;"
        )
        gl.addWidget(self._lbl_lim_cur)

        # X row
        xrow = QHBoxLayout()
        xrow.setSpacing(8)
        self._btn_xl = QPushButton("← Set X min")
        self._btn_xl.setToolTip("Capture current X as the left (minimum) limit")
        self._btn_xl.clicked.connect(lambda: self._capture_limit("x_min"))
        xrow.addWidget(self._btn_xl)

        self._lbl_xlim = QLabel()
        self._lbl_xlim.setStyleSheet(
            "color:#c0c0c0;font-family:monospace;font-size:11px;padding:0 6px;"
        )
        xrow.addWidget(self._lbl_xlim, stretch=1)

        self._btn_xr = QPushButton("Set X max →")
        self._btn_xr.setToolTip("Capture current X as the right (maximum) limit")
        self._btn_xr.clicked.connect(lambda: self._capture_limit("x_max"))
        xrow.addWidget(self._btn_xr)
        gl.addLayout(xrow)

        # Y row
        yrow = QHBoxLayout()
        yrow.setSpacing(8)
        self._btn_yd = QPushButton("↓ Set Y min")
        self._btn_yd.setToolTip("Capture current Y as the bottom (minimum) limit")
        self._btn_yd.clicked.connect(lambda: self._capture_limit("y_min"))
        yrow.addWidget(self._btn_yd)

        self._lbl_ylim = QLabel()
        self._lbl_ylim.setStyleSheet(
            "color:#c0c0c0;font-family:monospace;font-size:11px;padding:0 6px;"
        )
        yrow.addWidget(self._lbl_ylim, stretch=1)

        self._btn_yu = QPushButton("Set Y max ↑")
        self._btn_yu.setToolTip("Capture current Y as the top (maximum) limit")
        self._btn_yu.clicked.connect(lambda: self._capture_limit("y_max"))
        yrow.addWidget(self._btn_yu)
        gl.addLayout(yrow)

        self._update_limit_labels()
        lay.addWidget(g_lim)

        # ── Pen heights ───────────────────────────────────────────────────────
        g_pen = grp("PEN HEIGHTS")
        gp = QGridLayout(g_pen)
        gp.setSpacing(8)
        gp.addWidget(QLabel("Pen up (Z):"), 0, 0)
        self._sb_zup = dbl(s["z_up"], -20, 50, 0.5)
        gp.addWidget(self._sb_zup, 0, 1)
        gp.addWidget(QLabel("Pen down (Z):"), 0, 2)
        self._sb_zdown = dbl(s["z_down"], -20, 50, 0.5)
        gp.addWidget(self._sb_zdown, 0, 3)
        lay.addWidget(g_pen)

        # ── Feed rates ────────────────────────────────────────────────────────
        g_feed = grp("FEED RATES")
        gf = QGridLayout(g_feed)
        gf.setSpacing(8)
        gf.addWidget(QLabel("Travel:"), 0, 0)
        self._sb_feed_travel = spin(s["feed_travel"], 100, 20000, " mm/min")
        gf.addWidget(self._sb_feed_travel, 0, 1)
        gf.addWidget(QLabel("Draw:"), 0, 2)
        self._sb_feed_draw = spin(s["feed_draw"], 50, 10000, " mm/min")
        gf.addWidget(self._sb_feed_draw, 0, 3)
        lay.addWidget(g_feed)

        # ── Arduino Angles (Settings Only) ─────────────────────────────────────
        g_ard = grp("PEN LIFT ANGLES")
        ga = QVBoxLayout(g_ard)
        ga.setSpacing(10)

        ar = QHBoxLayout()
        ar.addWidget(QLabel("Pen up °:"))
        self._sb_up_angle = spin(s.get("servo_up_angle", 35), 0, 180)
        self._sb_up_angle.setFixedWidth(64)
        ar.addWidget(self._sb_up_angle)
        ar.addSpacing(20)
        ar.addWidget(QLabel("Pen down °:"))
        self._sb_down_angle = spin(s.get("servo_down_angle", 100), 0, 180)
        self._sb_down_angle.setFixedWidth(64)
        ar.addWidget(self._sb_down_angle)
        ar.addStretch()
        ga.addLayout(ar)

        sr = QHBoxLayout()
        sr.addWidget(QLabel("Servo settle delay:"))
        self._sb_settle = spin(s.get("servo_settle_ms", 150), 0, 1000, " ms")
        self._sb_settle.setFixedWidth(88)
        sr.addWidget(self._sb_settle)
        sr.addStretch()
        ga.addLayout(sr)
        
        lay.addWidget(g_ard)

        # Save / Send
        brow = QHBoxLayout()
        brow.addStretch()
        btn_apply = QPushButton("Apply & Save")
        btn_apply.setStyleSheet(
            "QPushButton{background:#2d6a3f;color:white;font-weight:bold;"
            "border:none;border-radius:3px;padding:7px 20px;}"
            "QPushButton:hover{background:#38854f;}"
        )
        btn_apply.clicked.connect(self._apply_settings)
        brow.addWidget(btn_apply)
        btn_send = QPushButton("Send to Machine")
        btn_send.setStyleSheet(
            "QPushButton{background:#2680eb;color:white;font-weight:bold;"
            "border:none;border-radius:3px;padding:7px 20px;}"
            "QPushButton:hover{background:#1473e6;}"
        )
        btn_send.clicked.connect(self._send_to_machine)
        brow.addWidget(btn_send)
        lay.addLayout(brow)

        note = QLabel(
            "Soft limits are saved instantly when you click a Set button.\n"
            "'Send to Machine' enables Marlin firmware endstops (M211 S1)."
        )
        note.setStyleSheet("color:#484848;font-size:11px;")
        note.setWordWrap(True)
        lay.addWidget(note)
        lay.addStretch()
        return w

    # ── soft limit capture ────────────────────────────────────────────────────

    def _capture_limit(self, key: str):
        pos = self.plotter.position
        val = round(pos["x"] if "x" in key else pos["y"], 2)
        self.plotter.settings[key] = val
        self.plotter.save_settings()
        self._update_limit_labels()
        self._bed.update()

    def _instant_save_limits(self):
        self.plotter.settings["soft_limits"] = self._chk_limits.isChecked()
        self.plotter.save_settings()

    def _update_limit_labels(self):
        s = self.plotter.settings
        self._lbl_xlim.setText(
            f"X min {s['x_min']:.1f}  ←→  {s['x_max']:.1f} X max"
        )
        self._lbl_ylim.setText(
            f"Y min {s['y_min']:.1f}  ↕  {s['y_max']:.1f} Y max"
        )

    # ── other settings ────────────────────────────────────────────────────────

    def _apply_settings(self):
        s = self.plotter.settings
        s["z_up"]             = self._sb_zup.value()
        s["z_down"]           = self._sb_zdown.value()
        s["feed_travel"]      = self._sb_feed_travel.value()
        s["feed_draw"]        = self._sb_feed_draw.value()
        s["servo_settle_ms"]  = self._sb_settle.value()
        s["servo_up_angle"]   = self._sb_up_angle.value()
        s["servo_down_angle"] = self._sb_down_angle.value()
        self.plotter.save_settings()
        self._bed.update()
        if self.arduino and self.arduino.is_connected:
            self.arduino.set_up_angle(s["servo_up_angle"])
            self.arduino.set_down_angle(s["servo_down_angle"])

    def _send_to_machine(self):
        self._apply_settings()
        if self.plotter.connected:
            self.plotter.send_gcode("M211 S1")

    # ── polling — non-blocking ────────────────────────────────────────────────

    def _poll_position(self):
        if not self.plotter.connected:
            return
        # 1. Update UI immediately from the last cached position (never blocks)
        pos = self.plotter.position
        self._lbl_pos.setText(
            f"X: {pos['x']:7.2f}   Y: {pos['y']:7.2f}   Z: {pos['z']:7.2f}"
        )
        if hasattr(self, "_lbl_lim_cur"):
            self._lbl_lim_cur.setText(
                f"Current:  X {pos['x']:.2f}   Y {pos['y']:.2f}"
            )
        self._bed.update()

        # 2. Fire a background M114 so the next tick gets fresh data
        if not self._polling:
            self._polling = True
            def _fetch():
                try:
                    self.plotter.request_position()
                finally:
                    self._polling = False
            threading.Thread(target=_fetch, daemon=True).start()

    # ── connection ────────────────────────────────────────────────────────────

    def keyPressEvent(self, e):
        if not self.plotter.connected:
            super().keyPressEvent(e)
            return
            
        k = e.key()
        step = 10
        if k == Qt.Key_Left:
            self.plotter.jog(-step, 0)
        elif k == Qt.Key_Right:
            self.plotter.jog(step, 0)
        elif k == Qt.Key_Up:
            self.plotter.jog(0, step)
        elif k == Qt.Key_Down:
            self.plotter.jog(0, -step)
        elif k == Qt.Key_Space:
            if self._pen_down_active:
                self._toggle_pen_ui_up()
            else:
                self._toggle_pen_ui_down()
        else:
            super().keyPressEvent(e)

    def _toggle_pen_ui_up(self):
        self.plotter.pen_up()
        self._pen_down_active = False

    def _toggle_pen_ui_down(self):
        self.plotter.pen_down()
        self._pen_down_active = True

    def _on_tab_changed(self, idx: int):
        self._refresh_ports()
        self._refresh_ard_ports_controls()

    def _auto_connect(self):
        # 1. Marlin (Ender 3)
        if not self.plotter.connected:
            ports = self.plotter.get_ports()
            for p in ports:
                lp = p.lower()
                # Common Ender 3 / Marlin keywords
                if any(k in lp for k in ["ch340", "cp2102", "usb-serial", "ender"]):
                    self.plotter.connect(p)
                    self._on_plotter_connected_ui(True)
                    break
        
        # 2. Arduino Leonardo (Pen Lift)
        if self.arduino and not self.arduino.is_connected:
            ports = ArduinoController.available_ports()
            for p in ports:
                lp = p.lower()
                # Prioritize "leonardo", fallback to generic usbmodem/com
                if "leonardo" in lp or ("usbmodem" in lp and "110" in lp):
                    # Safety check: don't steal Marlin's port
                    if self.plotter.connected and self.plotter.ser.port == p:
                        continue
                    if self.arduino.connect(p):
                        # Signal will trigger _on_arduino_connected to update UI
                        break

    def _refresh_ports(self):
        self._port_menu.clear()
        ports = self.plotter.get_ports()
        self._port_menu.addItems(ports if ports else ["No ports found"])

    def _on_plotter_connected_ui(self, connected: bool):
        if connected:
            self._btn_connect.setText("Disconnect")
            self._btn_connect.setStyleSheet(
                "QPushButton{background:#7f1d1d;color:white;font-weight:bold;border-radius:3px;padding:7px;}"
            )
            self._lbl_status.setText("Connected")
            self._lbl_status.setStyleSheet("color:#4ade80;font-size:11px;")
        else:
            self._btn_connect.setText("Connect")
            self._btn_connect.setStyleSheet(
                "QPushButton{background:#2d6a3f;color:white;font-weight:bold;border-radius:3px;padding:7px;}"
            )
            self._lbl_status.setText("Disconnected")
            self._lbl_status.setStyleSheet("color:#606060;font-size:11px;")

    def _toggle_connect(self):
        if not self.plotter.connected:
            port = self._port_menu.currentText()
            if port and port != "No ports found":
                if self.arduino and self.arduino.is_connected and self.arduino._ser.port == port:
                    self._lbl_status.setText("Error: Port busy (Arduino)")
                    return
                if self.plotter.connect(port):
                    self._on_plotter_connected_ui(True)
        else:
            self.plotter.disconnect()
            self._on_plotter_connected_ui(False)

    def _refresh_ard_ports_controls(self):
        if hasattr(self, "_ard_port_controls"):
            self._ard_port_controls.clear()
            ports = ArduinoController.available_ports()
            self._ard_port_controls.addItems(ports if ports else ["No ports found"])

    def _toggle_arduino_controls(self, checked: bool):
        if not self.arduino: return
        if checked:
            port = self._ard_port_controls.currentText()
            if port and port != "No ports found":
                if self.plotter.connected and self.plotter.ser.port == port:
                    self._on_arduino_status("Error: Port busy (Marlin)")
                    self._btn_ard_connect_controls.setChecked(False)
                    return
                if not self.arduino.connect(port):
                    self._btn_ard_connect_controls.setChecked(False)
        else:
            self.arduino.disconnect()

    def _on_arduino_connected(self, connected: bool):
        if hasattr(self, "_btn_ard_connect_controls"):
            self._btn_ard_connect_controls.setChecked(connected)
            self._btn_ard_connect_controls.setText("Disconnect Arduino" if connected else "Connect Arduino")

    def _on_arduino_status(self, msg: str):
        if hasattr(self, "_ard_status_controls"):
            self._ard_status_controls.setText(msg)
            col = "#4ade80" if self.arduino.is_connected else "#606060"
            self._ard_status_controls.setStyleSheet(f"color:{col};font-size:10px;")

    # ── plot-with-preview (called from Draw tab via app) ──────────────────────

    def start_plot_preview(self, paths: list):
        """Receive paths from the Draw tab, show preview, start plotting."""
        if not self.plotter.connected:
            self._prog_lbl.setText("Not connected — use the Connect button above")
            self._prog_lbl.setVisible(True)
            return

        # Load all paths into BedWidget so the full drawing is visible immediately
        self._bed.preview_paths = paths
        self._bed.preview_done  = 0
        self._bed.update()

        # Show progress UI
        self._plot_cancel.clear()
        self._prog_bar.setRange(0, len(paths))
        self._prog_bar.setValue(0)
        self._prog_bar.setVisible(True)
        self._prog_lbl.setText(f"Plotting  0 / {len(paths)}")
        self._prog_lbl.setVisible(True)
        self._btn_cancel_plot.setVisible(True)

        threading.Thread(
            target=self._run_plot, args=(paths,), daemon=True
        ).start()

    def _run_plot(self, paths: list):
        total = len(paths)
        for i, path in enumerate(paths):
            if self._plot_cancel.is_set():
                self.plotter.pen_up()
                self._plot_done.emit(False)
                return
            if len(path) < 2:
                continue
            self.plotter.pen_up()
            self.plotter.move_to(path[0][0], path[0][1])
            self.plotter.pen_down()
            for x, y in path[1:]:
                if self._plot_cancel.is_set():
                    self.plotter.pen_up()
                    self._plot_done.emit(False)
                    return
                self.plotter.move_to(x, y, self.plotter.settings.get("feed_draw", 1500))
            self._plot_prog.emit(i + 1, total)
        self.plotter.pen_up()
        self._plot_done.emit(True)

    def _on_plot_prog(self, current: int, total: int):
        self._bed.preview_done = current
        self._bed.update()
        self._prog_bar.setValue(current)
        self._prog_lbl.setText(f"Plotting  {current} / {total}")

    def _on_plot_done(self, ok: bool):
        self._prog_bar.setVisible(False)
        self._btn_cancel_plot.setVisible(False)
        self._prog_lbl.setText("Complete ✓" if ok else "Cancelled")
        # Clear preview after a short delay so the user can see the finished result
        QTimer.singleShot(4000, self._clear_preview)

    def _clear_preview(self):
        self._bed.preview_paths = []
        self._bed.preview_done  = 0
        self._bed.update()
        self._prog_lbl.setVisible(False)
