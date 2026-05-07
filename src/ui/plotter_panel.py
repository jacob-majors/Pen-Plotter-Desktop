from __future__ import annotations
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QComboBox, QGridLayout, QSizePolicy, QTabWidget, QFrame,
    QDoubleSpinBox, QSpinBox, QCheckBox, QGroupBox, QTextEdit,
)
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QPainter, QColor, QPen, QBrush, QFont
from core.arduino_controller import ArduinoController, ARDUINO_SKETCH
BG = QColor("#18181b")
PAPER = QColor("#fafaf8")


# ── tiny plotter-bed position indicator ───────────────────────────────────────

class BedWidget(QWidget):
    def __init__(self, plotter):
        super().__init__()
        self.plotter = plotter
        self.setMinimumSize(300, 300)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        s = self.plotter.settings
        bed_w = s["x_max"] - s["x_min"]
        bed_h = s["y_max"] - s["y_min"]

        # Background
        p.fillRect(0, 0, w, h, QColor("#111"))

        # Bed area
        pad = 16
        bw, bh = w - pad * 2, h - pad * 2
        p.setPen(QPen(QColor("#333"), 1))
        p.setBrush(QBrush(QColor("#1c1c1e")))
        p.drawRoundedRect(pad, pad, bw, bh, 3, 3)

        # Soft-limit boundary (if different from bed)
        xl = s["x_min"] / bed_w if bed_w else 0
        xr = s["x_max"] / bed_w if bed_w else 1
        yt = s["y_min"] / bed_h if bed_h else 0
        yb = s["y_max"] / bed_h if bed_h else 1
        lx = int(pad + xl * bw)
        ly = int(pad + (1 - yb) * bh)
        lw = int((xr - xl) * bw)
        lh = int((yb - yt) * bh)
        p.setPen(QPen(QColor("#3b82f6"), 1, Qt.DashLine))
        p.setBrush(Qt.NoBrush)
        p.drawRect(lx, ly, lw, lh)

        # Current position indicator
        pos = self.plotter.position
        if bed_w > 0 and bed_h > 0:
            nx = (pos["x"] - s["x_min"]) / bed_w
            ny = (pos["y"] - s["y_min"]) / bed_h
            px = int(pad + nx * bw)
            py = int(pad + (1 - ny) * bh)
            
            # Crosshair
            p.setPen(QPen(QColor("#3b82f6"), 1))
            p.drawLine(px, pad, px, pad + bh)
            p.drawLine(pad, py, pad + bw, py)
            
            # Dot
            p.setPen(Qt.NoPen)
            p.setBrush(QBrush(QColor("#ef4444")))
            p.drawEllipse(px - 6, py - 6, 12, 12)
            p.setBrush(QBrush(QColor("white")))
            p.drawEllipse(px - 2, py - 2, 4, 4)

        p.setPen(QColor("#a1a1aa"))
        p.setFont(QFont("Inter", 10, QFont.Bold))
        p.drawText(pad + 8, h - pad - 8, f"{pos['x']:.1f}, {pos['y']:.1f} mm")


# ── panel ─────────────────────────────────────────────────────────────────────

class PlotterPanel(QWidget):
    def __init__(self, plotter, arduino: ArduinoController | None = None):
        super().__init__()
        self.plotter = plotter
        self.arduino = arduino
        if arduino:
            arduino.connected_changed.connect(self._on_arduino_connected)
            arduino.status_changed.connect(self._on_arduino_status)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        tabs = QTabWidget()
        tabs.setStyleSheet("""
            QTabWidget::pane { border: none; }
            QTabBar::tab {
                background: #0f172a; color: #64748b;
                padding: 10px 24px; border: none;
                border-bottom: 2px solid transparent;
                font-weight: 600;
            }
            QTabBar::tab:selected { color: #3b82f6; border-bottom: 2px solid #3b82f6; }
            QTabBar::tab:hover:!selected { color: #94a3b8; background: #1e293b; }
        """)
        tabs.addTab(self._controls_tab(), "Controls")
        tabs.addTab(self._settings_tab(), "Settings")
        root.addWidget(tabs)

        self._pos_timer = QTimer(self)
        self._pos_timer.timeout.connect(self._poll_position)
        self._pos_timer.start(500)

    # ── Controls tab ──────────────────────────────────────────────────────────

    def _controls_tab(self) -> QWidget:
        w = QWidget()
        main_lay = QHBoxLayout(w)
        main_lay.setContentsMargins(20, 20, 20, 20)
        main_lay.setSpacing(24)

        # ── Left Column: Controls ──
        left_col = QVBoxLayout()
        left_col.setSpacing(16)

        # Connection Group
        conn_grp = QGroupBox("CONNECTION")
        conn_grp.setStyleSheet("QGroupBox{color:#94a3b8;font-size:10px;font-weight:800;letter-spacing:1.5px;border:1px solid #1e293b;border-radius:8px;margin-top:10px;padding-top:15px;background:#1e293b;}")
        clat = QVBoxLayout(conn_grp)
        
        conn_row = QHBoxLayout()
        self._port_menu = QComboBox()
        self._refresh_ports()
        conn_row.addWidget(self._port_menu, 1)
        btn_refresh = QPushButton("⟳")
        btn_refresh.setFixedWidth(32)
        btn_refresh.clicked.connect(self._refresh_ports)
        conn_row.addWidget(btn_refresh)
        clat.addLayout(conn_row)

        self._btn_connect = QPushButton("Connect Machine")
        self._btn_connect.setObjectName("btnSuccess")
        self._btn_connect.setStyleSheet("padding: 8px; font-weight: bold;")
        self._btn_connect.clicked.connect(self._toggle_connect)
        clat.addWidget(self._btn_connect)

        self._lbl_status = QLabel("Disconnected")
        self._lbl_status.setAlignment(Qt.AlignCenter)
        self._lbl_status.setStyleSheet("color:#6b7280;font-size:11px;")
        clat.addWidget(self._lbl_status)
        
        left_col.addWidget(conn_grp)

        # Jog Group
        jog_grp = QGroupBox("MOVEMENT")
        jog_grp.setStyleSheet("QGroupBox{color:#94a3b8;font-size:10px;font-weight:800;letter-spacing:1.5px;border:1px solid #1e293b;border-radius:8px;margin-top:10px;padding-top:15px;background:#1e293b;}")
        jlat = QHBoxLayout(jog_grp)
        
        grid = QGridLayout()
        grid.setSpacing(6)
        def jog_btn(text, dx, dy):
            b = QPushButton(text)
            b.setFixedSize(50, 40)
            b.setStyleSheet("QPushButton{border:1px solid #333;border-radius:4px;} QPushButton:hover{background:#2d2d2d;}")
            b.clicked.connect(lambda: self.plotter.jog(dx, dy))
            return b

        grid.addWidget(jog_btn("Y+", 0, 10), 0, 1)
        grid.addWidget(jog_btn("X−", -10, 0), 1, 0)
        btn_home = QPushButton("⌂")
        btn_home.setFixedSize(50, 40)
        btn_home.setStyleSheet("QPushButton{border:1px solid #3b82f6;border-radius:4px;color:#3b82f6;} QPushButton:hover{background:#1e3a8a;color:white;}")
        btn_home.clicked.connect(self.plotter.home)
        grid.addWidget(btn_home, 1, 1)
        grid.addWidget(jog_btn("X+", 10, 0), 1, 2)
        grid.addWidget(jog_btn("Y−", 0, -10), 2, 1)
        jlat.addLayout(grid)

        z_lay = QVBoxLayout()
        z_lay.setSpacing(4)
        for text, dz in [("Z+", 2), ("Z−", -2), ("UP", None), ("DOWN", None)]:
            b = QPushButton(text)
            b.setFixedSize(50, 28)
            b.setStyleSheet("QPushButton{background: #0f172a; border: 1px solid #334155; border-radius: 4px; font-size:10px;} QPushButton:hover{background:#1e293b; border-color: #475569;}")
            if dz is not None: b.clicked.connect(lambda _, d=dz: self.plotter.jog(0,0,d))
            elif text=="UP": b.clicked.connect(self.plotter.pen_up)
            else: b.clicked.connect(self.plotter.pen_down)
            z_lay.addWidget(b)
        jlat.addLayout(z_lay)
        left_col.addWidget(jog_grp)

        # Position display
        pos_grp = QGroupBox("COORDINATES")
        pos_grp.setStyleSheet("QGroupBox{color:#94a3b8;font-size:10px;font-weight:800;letter-spacing:1.5px;border:1px solid #1e293b;border-radius:8px;margin-top:10px;padding-top:15px;background:#1e293b;}")
        plat = QVBoxLayout(pos_grp)
        self._lbl_pos = QLabel("X: 0.00   Y: 0.00   Z: 0.00")
        self._lbl_pos.setStyleSheet("font-family:monospace;font-size:16px;color:#4ade80;padding:10px;")
        self._lbl_pos.setAlignment(Qt.AlignCenter)
        plat.addWidget(self._lbl_pos)
        left_col.addWidget(pos_grp)

        left_col.addStretch()
        main_lay.addLayout(left_col, 0)

        # ── Right Column: Preview ──
        right_col = QVBoxLayout()
        
        prev_grp = QGroupBox("BED PREVIEW")
        prev_grp.setStyleSheet("QGroupBox{color:#3b82f6;font-size:10px;font-weight:800;letter-spacing:1.5px;border:2px solid #3b82f6;border-radius:8px;margin-top:10px;padding:15px;background:#0f172a;}")
        plat = QVBoxLayout(prev_grp)
        
        self._bed = BedWidget(self.plotter)
        plat.addWidget(self._bed)
        
        right_col.addWidget(prev_grp)
        main_lay.addLayout(right_col, 1)

        return w

    # ── Settings tab ──────────────────────────────────────────────────────────

    def _settings_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(24, 16, 24, 16)
        lay.setSpacing(16)

        s = self.plotter.settings

        def section(title: str) -> QGroupBox:
            g = QGroupBox(title)
            g.setStyleSheet(
                "QGroupBox{color:#94a3b8;font-size:10px;font-weight:800;"
                "letter-spacing:1.5px;border:1px solid #1e293b;border-radius:8px;margin-top:12px;background:#1e293b;}"
                "QGroupBox::title{subcontrol-origin:margin;left:12px;padding:0 8px;}"
            )
            return g

        def dbl(val, lo, hi, step=0.5, suffix=" mm") -> QDoubleSpinBox:
            sb = QDoubleSpinBox()
            sb.setRange(lo, hi)
            sb.setValue(val)
            sb.setSingleStep(step)
            sb.setSuffix(suffix)
            sb.setFixedWidth(110)
            return sb

        def spin(val, lo, hi, suffix=" mm/min") -> QSpinBox:
            sb = QSpinBox()
            sb.setRange(lo, hi)
            sb.setValue(val)
            sb.setSuffix(suffix)
            sb.setFixedWidth(110)
            return sb

        # ── Soft limits ──────────────────────────────────────────────────────
        grp_limits = section("SOFT LIMITS")
        gl = QGridLayout(grp_limits)
        gl.setSpacing(8)
        gl.setColumnMinimumWidth(1, 115)
        gl.setColumnMinimumWidth(3, 115)

        self._chk_limits = QCheckBox("Enable software clamping")
        self._chk_limits.setChecked(s.get("soft_limits", True))
        gl.addWidget(self._chk_limits, 0, 0, 1, 4)

        gl.addWidget(QLabel("X min:"), 1, 0)
        self._sb_xmin = dbl(s["x_min"], -50, 500)
        gl.addWidget(self._sb_xmin, 1, 1)

        gl.addWidget(QLabel("X max:"), 1, 2)
        self._sb_xmax = dbl(s["x_max"], 0, 1000)
        gl.addWidget(self._sb_xmax, 1, 3)

        gl.addWidget(QLabel("Y min:"), 2, 0)
        self._sb_ymin = dbl(s["y_min"], -50, 500)
        gl.addWidget(self._sb_ymin, 2, 1)

        gl.addWidget(QLabel("Y max:"), 2, 2)
        self._sb_ymax = dbl(s["y_max"], 0, 1000)
        gl.addWidget(self._sb_ymax, 2, 3)

        lay.addWidget(grp_limits)

        # ── Pen heights ───────────────────────────────────────────────────────
        grp_pen = section("PEN HEIGHTS")
        gp = QGridLayout(grp_pen)
        gp.setSpacing(8)
        gp.setColumnMinimumWidth(1, 115)
        gp.setColumnMinimumWidth(3, 115)

        gp.addWidget(QLabel("Pen up (Z):"), 0, 0)
        self._sb_zup = dbl(s["z_up"], -20, 50, 0.5)
        gp.addWidget(self._sb_zup, 0, 1)

        gp.addWidget(QLabel("Pen down (Z):"), 0, 2)
        self._sb_zdown = dbl(s["z_down"], -20, 50, 0.5)
        gp.addWidget(self._sb_zdown, 0, 3)

        lay.addWidget(grp_pen)

        # ── Feed rates ────────────────────────────────────────────────────────
        grp_feed = section("FEED RATES")
        gf = QGridLayout(grp_feed)
        gf.setSpacing(8)
        gf.setColumnMinimumWidth(1, 115)
        gf.setColumnMinimumWidth(3, 115)

        gf.addWidget(QLabel("Travel:"), 0, 0)
        self._sb_feed_travel = spin(s["feed_travel"], 100, 20000)
        gf.addWidget(self._sb_feed_travel, 0, 1)

        gf.addWidget(QLabel("Draw:"), 0, 2)
        self._sb_feed_draw = spin(s["feed_draw"], 50, 10000)
        gf.addWidget(self._sb_feed_draw, 0, 3)

        lay.addWidget(grp_feed)

        # ── Arduino Leonardo (servo + E-stop) ─────────────────────────────────
        grp_ard = section("ARDUINO LEONARDO  —  SERVO + E-STOP")
        ga = QVBoxLayout(grp_ard)
        ga.setSpacing(8)

        port_row = QHBoxLayout()
        port_row.addWidget(QLabel("Port:"))
        self._ard_port = QComboBox()
        self._ard_port.setFixedWidth(160)
        self._refresh_ard_ports()
        port_row.addWidget(self._ard_port)

        btn_ard_refresh = QPushButton("⟳")
        btn_ard_refresh.setFixedWidth(30)
        btn_ard_refresh.clicked.connect(self._refresh_ard_ports)
        port_row.addWidget(btn_ard_refresh)

        self._btn_ard_connect = QPushButton("Connect")
        self._btn_ard_connect.setFixedWidth(90)
        self._btn_ard_connect.setStyleSheet(
            "QPushButton{background:#334155; border:1px solid #475569; border-radius:4px; padding:4px 8px;}"
            "QPushButton:checked{background:#059669; color:white; border-color:#059669;}"
            "QPushButton:hover:!checked{background:#475569;}"
        )
        self._btn_ard_connect.setCheckable(True)
        self._btn_ard_connect.clicked.connect(self._toggle_arduino)
        port_row.addWidget(self._btn_ard_connect)

        port_row.addStretch()
        ga.addLayout(port_row)

        self._ard_status = QLabel("Not connected")
        self._ard_status.setStyleSheet("color:#6b7280;font-size:12px;")
        ga.addWidget(self._ard_status)

        # Servo angles — sent to Leonardo over serial, saved to its EEPROM
        angle_row = QHBoxLayout()
        angle_row.addWidget(QLabel("Pen up °:"))
        self._sb_up_angle = QSpinBox()
        self._sb_up_angle.setRange(0, 180)
        self._sb_up_angle.setValue(self.plotter.settings.get("servo_up_angle", 90))
        self._sb_up_angle.setFixedWidth(64)
        self._sb_up_angle.setToolTip("Servo angle when pen is lifted (SET_UP command)")
        angle_row.addWidget(self._sb_up_angle)
        angle_row.addSpacing(12)
        angle_row.addWidget(QLabel("Pen down °:"))
        self._sb_down_angle = QSpinBox()
        self._sb_down_angle.setRange(0, 180)
        self._sb_down_angle.setValue(self.plotter.settings.get("servo_down_angle", 30))
        self._sb_down_angle.setFixedWidth(64)
        self._sb_down_angle.setToolTip("Servo angle when pen is lowered (SET_DOWN command)")
        angle_row.addWidget(self._sb_down_angle)
        angle_row.addStretch()
        ga.addLayout(angle_row)

        settle_row = QHBoxLayout()
        settle_row.addWidget(QLabel("Servo settle:"))
        self._sb_settle = QSpinBox()
        self._sb_settle.setRange(0, 1000)
        self._sb_settle.setValue(self.plotter.settings.get("servo_settle_ms", 150))
        self._sb_settle.setSuffix(" ms")
        self._sb_settle.setFixedWidth(90)
        self._sb_settle.setToolTip("Wait this long after pen up/down before the next move")
        settle_row.addWidget(self._sb_settle)
        settle_row.addStretch()
        ga.addLayout(settle_row)

        btn_pen_row = QHBoxLayout()
        for label, fn in [("Test Pen Up", lambda: self.plotter.pen_up()),
                          ("Test Pen Down", lambda: self.plotter.pen_down())]:
            b = QPushButton(label)
            b.setStyleSheet(
                "QPushButton{background:#334155; border:1px solid #475569; border-radius:4px; padding:5px 12px;}"
                "QPushButton:hover{background:#475569; border-color: #64748b;}"
            )
            b.clicked.connect(fn)
            btn_pen_row.addWidget(b)
        btn_pen_row.addStretch()
        ga.addLayout(btn_pen_row)

        sketch_lbl = QLabel("Arduino sketch  (upload once — angles are inside the sketch):")
        sketch_lbl.setStyleSheet("color:#6b7280;font-size:11px;")
        ga.addWidget(sketch_lbl)

        sketch_box = QTextEdit()
        sketch_box.setReadOnly(True)
        sketch_box.setFont(QFont("Menlo, Consolas, monospace", 9))
        sketch_box.setPlainText(ARDUINO_SKETCH.strip())
        sketch_box.setStyleSheet(
            "background:#0a0a0a;color:#d1d5db;border:1px solid #27272a;border-radius:4px;"
        )
        sketch_box.setFixedHeight(180)
        ga.addWidget(sketch_box)

        lay.addWidget(grp_ard)

        # ── Save / Apply ──────────────────────────────────────────────────────
        btn_row = QHBoxLayout()
        btn_row.addStretch()

        btn_apply = QPushButton("Apply & Save")
        btn_apply.setStyleSheet(
            "background:#166534;color:white;font-weight:bold;"
            "border-radius:4px;padding:8px 24px;"
        )
        btn_apply.clicked.connect(self._apply_settings)
        btn_row.addWidget(btn_apply)

        btn_send = QPushButton("Send to Machine")
        btn_send.setStyleSheet(
            "background:#1e3a8a;color:#93c5fd;font-weight:bold;"
            "border:1px solid #1e40af;border-radius:4px;padding:8px 24px;"
        )
        btn_send.clicked.connect(self._send_to_machine)
        btn_row.addWidget(btn_send)

        lay.addLayout(btn_row)

        note = QLabel(
            "Soft limits clamp all coordinates in software before sending G-code.\n"
            "'Send to Machine' enables Marlin firmware endstops (M211 S1)."
        )
        note.setStyleSheet("color:#52525b;font-size:11px;")
        note.setWordWrap(True)
        lay.addWidget(note)

        lay.addStretch()
        return w

    # ── settings actions ──────────────────────────────────────────────────────

    def _apply_settings(self):
        s = self.plotter.settings
        s["soft_limits"]     = self._chk_limits.isChecked()
        s["x_min"]           = self._sb_xmin.value()
        s["x_max"]           = self._sb_xmax.value()
        s["y_min"]           = self._sb_ymin.value()
        s["y_max"]           = self._sb_ymax.value()
        s["z_up"]            = self._sb_zup.value()
        s["z_down"]          = self._sb_zdown.value()
        s["feed_travel"]     = self._sb_feed_travel.value()
        s["feed_draw"]       = self._sb_feed_draw.value()
        s["servo_settle_ms"]  = self._sb_settle.value()
        s["servo_up_angle"]   = self._sb_up_angle.value()
        s["servo_down_angle"] = self._sb_down_angle.value()
        self.plotter.save_settings()
        self._bed.update()

        # Push angles to the Leonardo over serial (saved to its EEPROM)
        if self.arduino and self.arduino.is_connected:
            self.arduino.set_up_angle(s["servo_up_angle"])
            self.arduino.set_down_angle(s["servo_down_angle"])

    def _send_to_machine(self):
        self._apply_settings()
        if self.plotter.connected:
            self.plotter.send_gcode("M211 S1")  # enable firmware soft endstops
            s = self.plotter.settings
            # Report limits in terminal (Marlin doesn't accept runtime limit changes)
            self.plotter.send_gcode(
                f"; Soft limits: X[{s['x_min']},{s['x_max']}] "
                f"Y[{s['y_min']},{s['y_max']}]"
            )

    # ── polling ───────────────────────────────────────────────────────────────

    def _poll_position(self):
        if self.plotter.connected:
            self.plotter.request_position()
            pos = self.plotter.position
            self._lbl_pos.setText(
                f"X: {pos['x']:7.2f}   Y: {pos['y']:7.2f}   Z: {pos['z']:7.2f}"
            )
            self._bed.update()

    # ── connection ────────────────────────────────────────────────────────────

    def _refresh_ports(self):
        self._port_menu.clear()
        ports = self.plotter.get_ports()
        self._port_menu.addItems(ports if ports else ["No ports found"])

    def _toggle_connect(self):
        if not self.plotter.connected:
            port = self._port_menu.currentText()
            if port and port != "No ports found":
                if self.plotter.connect(port):
                    self._btn_connect.setText("Disconnect")
                    self._btn_connect.setStyleSheet(
                        "background:#7f1d1d;color:white;border-radius:4px;padding:6px 14px;font-weight:bold;"
                    )
                    self._lbl_status.setText("Connected")
                    self._lbl_status.setStyleSheet("color:#4ade80;font-size:12px;padding-left:6px;")
        else:
            self.plotter.disconnect()
            self._btn_connect.setText("Connect")
            self._btn_connect.setStyleSheet(
                "QPushButton{background:#166534;color:white;border-radius:4px;padding:6px 14px;font-weight:bold;}"
            )
            self._lbl_status.setText("Disconnected")
            self._lbl_status.setStyleSheet("color:#6b7280;font-size:12px;padding-left:6px;")

    # ── Arduino helpers ───────────────────────────────────────────────────────

    def _refresh_ard_ports(self):
        self._ard_port.clear()
        ports = ArduinoController.available_ports()
        self._ard_port.addItems(ports if ports else ["No ports found"])

    def _toggle_arduino(self, checked: bool):
        if not self.arduino:
            self._btn_ard_connect.setChecked(False)
            return
        if checked:
            port = self._ard_port.currentText()
            if port and port != "No ports found":
                if not self.arduino.connect(port):
                    self._btn_ard_connect.setChecked(False)
            else:
                self._btn_ard_connect.setChecked(False)
        else:
            self.arduino.disconnect()

    def _on_arduino_connected(self, connected: bool):
        if connected:
            self._btn_ard_connect.setText("Disconnect")
            self._btn_ard_connect.setChecked(True)
        else:
            self._btn_ard_connect.setText("Connect")
            self._btn_ard_connect.setChecked(False)

    def _on_arduino_status(self, msg: str):
        connected = self.arduino and self.arduino.is_connected
        self._ard_status.setText(msg)
        self._ard_status.setStyleSheet(
            f"color:{'#4ade80' if connected else '#6b7280'};font-size:12px;"
        )
