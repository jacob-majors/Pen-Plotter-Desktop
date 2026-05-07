from __future__ import annotations
import cv2
import json
import threading
from pathlib import Path

import numpy as np
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QSplitter,
    QPushButton, QLabel, QLineEdit, QTextEdit,
    QSpinBox, QDoubleSpinBox, QSlider, QComboBox,
    QFrame, QProgressBar, QButtonGroup,
)
from PySide6.QtCore import Qt, QRectF, QTimer, Signal
from PySide6.QtGui import (
    QPainter, QColor, QImage, QPixmap, QFont, QPen, QBrush,
)

from core.vision import detect_and_warp, trace_to_paths, draw_trace_preview, VisionScanner
from core.handwriting import text_to_paths as text_to_handwriting

CONFIG_FILE = Path(__file__).resolve().parent.parent.parent / "config.json"
BG = QColor("#18181b")


# ── image display widget ──────────────────────────────────────────────────────

class ImageDisplay(QWidget):
    """Displays a BGR numpy frame or a placeholder, with rounded corners."""

    def __init__(self):
        super().__init__()
        self.setMinimumSize(320, 240)
        self._pixmap: QPixmap | None = None
        self._label = ""
        self.setStyleSheet("background: #09090b;")

    def set_frame(self, frame: np.ndarray, label: str = ""):
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        h, w, ch = rgb.shape
        self._pixmap = QPixmap.fromImage(QImage(rgb.tobytes(), w, h, ch * w, QImage.Format_RGB888))
        self._label = label
        self.update()

    def clear(self, label: str = ""):
        self._pixmap = None
        self._label = label
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        w, h = self.width(), self.height()
        p.fillRect(0, 0, w, h, QColor("#09090b"))

        if self._pixmap:
            scaled = self._pixmap.scaled(w, h, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            x = (w - scaled.width()) // 2
            y = (h - scaled.height()) // 2
            p.drawPixmap(x, y, scaled)
        else:
            p.setPen(QColor("#3f3f46"))
            p.setFont(QFont("Arial", 11))
            p.drawText(QRectF(0, 0, w, h), Qt.AlignCenter,
                       self._label or "No image")

        if self._label and self._pixmap:
            p.fillRect(0, h - 24, w, 24, QColor(0, 0, 0, 120))
            p.setPen(QColor("#a1a1aa"))
            p.setFont(QFont("Arial", 9))
            p.drawText(QRectF(6, h - 24, w - 12, 24), Qt.AlignVCenter, self._label)


# ── panel ─────────────────────────────────────────────────────────────────────

class AIPanel(QWidget):
    # cross-thread signals
    _frame_sig    = Signal(object)   # (frame, label)
    _progress_sig = Signal(int, int) # (current, total)
    _status_sig   = Signal(str)
    _gemini_sig   = Signal(str)      # response text

    def __init__(self, plotter, _camera_panel=None):
        super().__init__()
        self.plotter = plotter
        self._scanner = VisionScanner(plotter)

        # State
        self._cap: cv2.VideoCapture | None = None
        self._live_timer = QTimer(self)
        self._live_timer.timeout.connect(self._tick_live)
        self._captured: np.ndarray | None = None
        self._warped: np.ndarray | None = None
        self._trace_paths: list = []

        # Cross-thread
        self._frame_sig.connect(self._on_frame)
        self._progress_sig.connect(self._on_progress)
        self._status_sig.connect(self._set_status)
        self._gemini_sig.connect(self._on_gemini_response)

        self._build_ui()

    # ── UI construction ───────────────────────────────────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # toolbar
        toolbar = QWidget()
        toolbar.setFixedHeight(48)
        toolbar.setStyleSheet("background:#1e1e1e;border-bottom:1px solid #2d2d2d;")
        tlay = QHBoxLayout(toolbar)
        tlay.setContentsMargins(14, 0, 14, 0)
        tlay.setSpacing(8)

        tlay.addWidget(QLabel("Camera:"))
        self._port_combo = QComboBox()
        for i in range(6):
            self._port_combo.addItem(f"Port {i}", i)
        self._port_combo.setFixedWidth(90)
        tlay.addWidget(self._port_combo)

        self._btn_cam = QPushButton("Connect")
        self._btn_cam.setCheckable(True)
        self._btn_cam.setStyleSheet(
            "QPushButton{border:1px solid #444;border-radius:4px;padding:5px 10px;}"
            "QPushButton:checked{background:#166534;color:white;border-color:#166534;}"
        )
        self._btn_cam.clicked.connect(self._toggle_camera)
        tlay.addWidget(self._btn_cam)

        def vsep():
            f = QFrame()
            f.setFrameShape(QFrame.VLine)
            f.setFixedWidth(1)
            f.setStyleSheet("background:#333;")
            return f

        tlay.addWidget(vsep())

        self._btn_capture = QPushButton("Capture")
        self._btn_capture.setStyleSheet(
            "QPushButton{border:1px solid #444;border-radius:4px;padding:5px 12px;}"
            "QPushButton:hover{background:#2d2d2d;}"
        )
        self._btn_capture.clicked.connect(self._capture)
        tlay.addWidget(self._btn_capture)

        self._btn_smart = QPushButton("✨ Smart Scan & Solve")
        self._btn_smart.setStyleSheet(
            "QPushButton{background:#4338ca;color:white;border-radius:4px;padding:6px 14px;font-weight:bold;}"
            "QPushButton:hover{background:#4f46e5;}"
        )
        self._btn_smart.clicked.connect(self._start_smart_workflow)
        tlay.addWidget(self._btn_smart)

        tlay.addStretch()

        self._status_lbl = QLabel("Idle")
        self._status_lbl.setStyleSheet("color:#71717a;font-size:12px;")
        tlay.addWidget(self._status_lbl)

        root.addWidget(toolbar)

        # body splitter
        splitter = QSplitter(Qt.Horizontal)

        splitter.addWidget(self._build_left())
        splitter.addWidget(self._build_center())
        splitter.addWidget(self._build_right())
        splitter.setSizes([230, 600, 300])

        root.addWidget(splitter, stretch=1)

    def _build_left(self) -> QWidget:
        w = QWidget()
        w.setStyleSheet("background:#1a1a1a;")
        lay = QVBoxLayout(w)
        lay.setContentsMargins(12, 14, 12, 14)
        lay.setSpacing(10)

        def hdr(text):
            lbl = QLabel(text)
            lbl.setStyleSheet(
                "font-size:10px;font-weight:bold;color:#6b7280;letter-spacing:1.5px;"
            )
            lay.addWidget(lbl)
            sep = QFrame()
            sep.setFrameShape(QFrame.HLine)
            sep.setFixedHeight(1)
            sep.setStyleSheet("background:#2d2d2d;")
            lay.addWidget(sep)

        # Scan config
        hdr("GRID SCAN")

        row = QHBoxLayout()
        row.addWidget(QLabel("Grid:"))
        self._spin_rows = QSpinBox()
        self._spin_rows.setRange(1, 8)
        self._spin_rows.setValue(3)
        self._spin_cols = QSpinBox()
        self._spin_cols.setRange(1, 8)
        self._spin_cols.setValue(3)
        row.addWidget(self._spin_rows)
        lbl_x = QLabel("×")
        lbl_x.setAlignment(Qt.AlignCenter)
        row.addWidget(lbl_x)
        row.addWidget(self._spin_cols)
        lay.addLayout(row)

        wait_row = QHBoxLayout()
        wait_row.addWidget(QLabel("Stabilize:"))
        self._spin_wait = QDoubleSpinBox()
        self._spin_wait.setRange(0.3, 10.0)
        self._spin_wait.setValue(1.5)
        self._spin_wait.setSuffix(" s")
        wait_row.addWidget(self._spin_wait)
        lay.addLayout(wait_row)

        # Detect
        hdr("DETECT")

        self._btn_detect = QPushButton("Detect & Warp")
        self._btn_detect.setStyleSheet(
            "QPushButton{border:1px solid #444;border-radius:4px;padding:6px;}"
            "QPushButton:hover{background:#2d2d2d;}"
        )
        self._btn_detect.clicked.connect(self._detect)
        lay.addWidget(self._btn_detect)

        # Trace
        hdr("EDGE TRACE")
        lay.addWidget(QLabel("Threshold:"))

        thresh_row = QHBoxLayout()
        self._sld_thresh = QSlider(Qt.Horizontal)
        self._sld_thresh.setRange(10, 200)
        self._sld_thresh.setValue(50)
        self._thresh_lbl = QLabel("50")
        self._thresh_lbl.setFixedWidth(28)
        self._sld_thresh.valueChanged.connect(lambda v: self._thresh_lbl.setText(str(v)))
        thresh_row.addWidget(self._sld_thresh)
        thresh_row.addWidget(self._thresh_lbl)
        lay.addLayout(thresh_row)

        self._btn_trace = QPushButton("Trace Edges")
        self._btn_trace.setStyleSheet(
            "QPushButton{border:1px solid #444;border-radius:4px;padding:6px;}"
            "QPushButton:hover{background:#2d2d2d;}"
        )
        self._btn_trace.clicked.connect(self._trace)
        lay.addWidget(self._btn_trace)

        self._btn_plot_trace = QPushButton("Plot Trace")
        self._btn_plot_trace.setEnabled(False)
        self._btn_plot_trace.setStyleSheet(
            "QPushButton{background:#1e3a8a;color:#93c5fd;border:1px solid #1e40af;"
            "border-radius:4px;padding:6px;font-weight:bold;}"
            "QPushButton:disabled{opacity:0.4;}"
        )
        self._btn_plot_trace.clicked.connect(self._plot_trace)
        lay.addWidget(self._btn_plot_trace)

        lay.addStretch()
        return w

    def _build_center(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        # Tab bar
        tab_bar = QWidget()
        tab_bar.setFixedHeight(36)
        tab_bar.setStyleSheet("background:#1e1e1e;border-bottom:1px solid #2d2d2d;")
        tbl = QHBoxLayout(tab_bar)
        tbl.setContentsMargins(8, 0, 8, 0)
        tbl.setSpacing(2)

        self._tab_group = QButtonGroup(self)
        for i, name in enumerate(["Live", "Captured", "Detected", "Trace"]):
            btn = QPushButton(name)
            btn.setCheckable(True)
            btn.setChecked(i == 0)
            btn.setFixedHeight(28)
            btn.setStyleSheet(
                "QPushButton{border:none;border-radius:4px;padding:0 12px;color:#71717a;}"
                "QPushButton:checked{background:#262626;color:white;}"
                "QPushButton:hover{color:#d4d4d4;}"
            )
            self._tab_group.addButton(btn, i)
            tbl.addWidget(btn)
        tbl.addStretch()
        self._tab_group.idClicked.connect(self._switch_tab)

        lay.addWidget(tab_bar)

        self._img_display = ImageDisplay()
        self._img_display.clear("Connect a camera and click Capture")
        lay.addWidget(self._img_display, stretch=1)

        return w

    def _build_right(self) -> QWidget:
        w = QWidget()
        w.setStyleSheet("background:#1a1a1a;")
        lay = QVBoxLayout(w)
        lay.setContentsMargins(12, 14, 12, 14)
        lay.setSpacing(10)

        def hdr(text):
            lbl = QLabel(text)
            lbl.setStyleSheet(
                "font-size:10px;font-weight:bold;color:#6b7280;letter-spacing:1.5px;"
            )
            lay.addWidget(lbl)
            sep = QFrame()
            sep.setFrameShape(QFrame.HLine)
            sep.setFixedHeight(1)
            sep.setStyleSheet("background:#2d2d2d;")
            lay.addWidget(sep)

        hdr("GEMINI API")

        self._api_key = QLineEdit()
        self._api_key.setEchoMode(QLineEdit.Password)
        self._api_key.setPlaceholderText("Paste Gemini API Key here...")
        self._api_key.setText(self._load_api_key())
        
        btn_save_key = QPushButton("Save Key")
        btn_save_key.setStyleSheet("background: #334155; padding: 4px; font-size: 11px;")
        btn_save_key.clicked.connect(self._save_api_key)
        
        key_lay = QHBoxLayout()
        key_lay.addWidget(self._api_key)
        key_lay.addWidget(btn_save_key)
        lay.addLayout(key_lay)

        lay.addWidget(QLabel("Prompt:"))
        self._prompt = QTextEdit()
        self._prompt.setFixedHeight(80)
        self._prompt.setPlainText(
            "Describe what you see in this plotter camera image. "
            "Focus on shapes, lines, and any text or drawings visible."
        )
        self._prompt.setStyleSheet(
            "background:#262626;border:1px solid #404040;"
            "border-radius:4px;color:#d1d5db;font-size:12px;"
        )
        lay.addWidget(self._prompt)

        self._btn_analyze = QPushButton("Analyze with Gemini")
        self._btn_analyze.setStyleSheet(
            "QPushButton{background:#4c1d95;color:#c4b5fd;font-weight:bold;"
            "border:1px solid #5b21b6;border-radius:4px;padding:8px;}"
            "QPushButton:hover{background:#5b21b6;}"
        )
        self._btn_analyze.clicked.connect(self._analyze_gemini)
        lay.addWidget(self._btn_analyze)

        hdr("RESPONSE")

        self._response_box = QTextEdit()
        self._response_box.setReadOnly(True)
        self._response_box.setPlaceholderText("Gemini response will appear here…")
        self._response_box.setStyleSheet(
            "background:#0a0a0a;border:1px solid #27272a;"
            "border-radius:4px;color:#d1d5db;font-size:12px;"
        )
        lay.addWidget(self._response_box, stretch=1)

        self._btn_plot_response = QPushButton("Plot Solution Paths")
        self._btn_plot_response.setEnabled(False)
        self._btn_plot_response.setObjectName("btnPrimary")
        self._btn_plot_response.clicked.connect(self._plot_response_paths)
        lay.addWidget(self._btn_plot_response)

        return w

    # ── camera ────────────────────────────────────────────────────────────────

    def _toggle_camera(self, checked: bool):
        if checked:
            port = self._port_combo.currentData()
            cap = cv2.VideoCapture(port)
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
            if not cap.isOpened():
                self._btn_cam.setChecked(False)
                self._set_status("Could not open camera")
                return
            self._cap = cap
            self._live_timer.start(50)
            self._btn_cam.setText("Disconnect")
            self._set_status("Camera live")
        else:
            self._live_timer.stop()
            if self._cap:
                self._cap.release()
                self._cap = None
            self._btn_cam.setText("Connect")
            self._img_display.clear("Camera disconnected")
            self._set_status("Idle")

    def _tick_live(self):
        if not self._cap or not self._cap.isOpened():
            return
        # only update if on the Live tab
        if self._tab_group.checkedId() != 0:
            return
        ret, frame = self._cap.read()
        if ret:
            self._img_display.set_frame(frame, "Live Feed")

    # ── capture ───────────────────────────────────────────────────────────────

    def _capture(self):
        if not self._cap or not self._cap.isOpened():
            self._set_status("No camera — connect first")
            return
        ret, frame = self._cap.read()
        if not ret:
            self._set_status("Capture failed")
            return
        self._captured = frame.copy()
        self._warped = None
        self._trace_paths = []
        self._btn_plot_trace.setEnabled(False)
        self._switch_tab(1)
        self._tab_group.button(1).setChecked(True)
        self._img_display.set_frame(frame, "Captured")
        self._set_status("Captured — click Detect & Warp or Trace Edges")

    # ── smart workflow ────────────────────────────────────────────────────────
    
    def _start_smart_workflow(self):
        if not self._cap or not self._cap.isOpened():
            self._set_status("No camera — connect first")
            return
        if not self.plotter.connected:
            self._set_status("Plotter not connected")
            return
        key = self._api_key.text().strip()
        if not key:
            self._set_status("Enter Gemini API key first")
            return
            
        self._btn_smart.setEnabled(False)
        self._status_lbl.setText("Starting Smart Scan...")
        threading.Thread(target=self._run_smart_workflow, daemon=True).start()

    def _run_smart_workflow(self):
        try:
            # 1. Grid Scan
            rows, cols = self._spin_rows.value(), self._spin_cols.value()
            wait = self._spin_wait.value()
            self._status_sig.emit("Scanning bed...")
            images, grid_size = self._scanner.start_grid_scan(
                self._cap, grid_size=(rows, cols), wait_time=wait,
                status_cb=lambda msg: self._status_sig.emit(msg)
            )
            
            # 2. Stitch
            self._status_sig.emit("Stitching images...")
            stitched = self._scanner.stitch_scan(images, grid_size=grid_size)
            if stitched is None:
                self._status_sig.emit("Stitching failed")
                self._btn_smart.setEnabled(True)
                return
            self._captured = stitched
            self._frame_sig.emit((stitched, "Stitched Worksheet"))
            
            # 3. Gemini Analysis
            self._status_sig.emit("Analyzing with Gemini...")
            key = self._api_key.text().strip()
            prompt = (
                "This is a high-resolution scan of a worksheet on a plotter bed. "
                "Extract all questions and provide short answers. "
                "Return the result ONLY as a JSON array of objects: "
                "[{\"text\": \"Answer text\", \"x_mm\": 100, \"y_mm\": 50}]. "
                "The coordinates (x_mm, y_mm) should be estimates in millimeters on a 220x220mm bed. "
                "Place answers near the original questions."
            )
            
            import google.generativeai as genai
            from PIL import Image as PILImage
            genai.configure(api_key=key)
            model = genai.GenerativeModel("gemini-1.5-flash")
            rgb = cv2.cvtColor(stitched, cv2.COLOR_BGR2RGB)
            pil_img = PILImage.fromarray(rgb)
            response = model.generate_content([prompt, pil_img])
            
            # 4. Process Response
            self._gemini_sig.emit(response.text)
            self._status_sig.emit("Processing solution paths...")
            
        except Exception as e:
            self._status_sig.emit(f"Workflow error: {e}")
        finally:
            self._btn_smart.setEnabled(True)

    # ── grid scan ─────────────────────────────────────────────────────────────

    def _start_scan(self):
        if not self._cap or not self._cap.isOpened():
            self._set_status("No camera — connect first")
            return
        if not self.plotter.connected:
            self._set_status("Plotter not connected")
            return
        self._btn_scan.setEnabled(False)
        self._progress.setVisible(True)
        rows = self._spin_rows.value()
        cols = self._spin_cols.value()
        self._progress.setRange(0, rows * cols)
        self._progress.setValue(0)
        threading.Thread(target=self._run_scan, daemon=True).start()

    def _run_scan(self):
        rows = self._spin_rows.value()
        cols = self._spin_cols.value()
        wait = self._spin_wait.value()
        cap = self._cap

        images, grid_size = self._scanner.start_grid_scan(
            cap,
            grid_size=(rows, cols),
            wait_time=wait,
            progress_cb=lambda cur, tot: self._progress_sig.emit(cur, tot),
            status_cb=lambda msg: self._status_sig.emit(msg),
        )
        stitched = self._scanner.stitch_scan(images, grid_size=grid_size)
        if stitched is not None:
            self._captured = stitched
            self._frame_sig.emit((stitched, f"Scan {rows}×{cols}"))
        self._status_sig.emit("Scan complete" if stitched is not None else "Scan failed")

    # ── detect / warp ─────────────────────────────────────────────────────────

    def _detect(self):
        src = self._warped if self._warped is not None else self._captured
        if src is None:
            self._set_status("Capture an image first")
            return
        annotated, warped, found = detect_and_warp(src)
        if found:
            self._warped = warped
        self._switch_tab(2)
        self._tab_group.button(2).setChecked(True)
        label = "Detected & Warped" if found else "Detection failed"
        self._img_display.set_frame(annotated, label)
        self._set_status(label)

    # ── edge trace ────────────────────────────────────────────────────────────

    def _trace(self):
        src = self._warped if self._warped is not None else self._captured
        if src is None:
            self._set_status("Capture or detect first")
            return
        t = self._sld_thresh.value()
        self._trace_paths = trace_to_paths(src, thresh1=t, thresh2=t * 2)
        preview = draw_trace_preview(src, self._trace_paths)
        self._switch_tab(3)
        self._tab_group.button(3).setChecked(True)
        self._img_display.set_frame(preview, f"Trace — {len(self._trace_paths)} paths")
        self._btn_plot_trace.setEnabled(bool(self._trace_paths) and self.plotter.connected)
        self._set_status(f"Traced {len(self._trace_paths)} paths")

    def _plot_trace(self):
        if not self._trace_paths or not self.plotter.connected:
            return
        threading.Thread(target=self._run_plot, args=(self._trace_paths,), daemon=True).start()

    def _run_plot(self, paths: list):
        self._status_sig.emit("Plotting…")
        s = self.plotter.settings
        for path in paths:
            if len(path) < 2:
                continue
            self.plotter.send_gcode("G90")
            self.plotter.pen_up()
            x0, y0 = self.plotter.clamp(path[0][0], path[0][1])
            self.plotter.send_gcode(f"G0 X{x0:.2f} Y{y0:.2f} F{s['feed_travel']}")
            self.plotter.pen_down()
            for x, y in path[1:]:
                cx, cy = self.plotter.clamp(x, y)
                self.plotter.send_gcode(f"G1 X{cx:.2f} Y{cy:.2f} F{s['feed_draw']}")
        self.plotter.pen_up()
        self._status_sig.emit("Plot complete")

    # ── Gemini ────────────────────────────────────────────────────────────────

    def _analyze_gemini(self):
        src = self._warped if self._warped is not None else self._captured
        if src is None:
            self._set_status("Capture an image first")
            return
        key = self._api_key.text().strip()
        if not key:
            self._set_status("Enter a Gemini API key")
            return
        self._btn_analyze.setEnabled(False)
        self._response_box.setPlainText("Analyzing…")
        prompt = self._prompt.toPlainText()
        frame = src.copy()
        threading.Thread(target=self._run_gemini, args=(key, frame, prompt), daemon=True).start()

    def _run_gemini(self, api_key: str, frame: np.ndarray, prompt: str):
        try:
            import google.generativeai as genai
            from PIL import Image as PILImage

            genai.configure(api_key=api_key)
            model = genai.GenerativeModel("gemini-1.5-flash")
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            pil_img = PILImage.fromarray(rgb)
            response = model.generate_content([prompt, pil_img])
            self._gemini_sig.emit(response.text)
        except Exception as exc:
            self._gemini_sig.emit(f"Error: {exc}")

    # ── slots ─────────────────────────────────────────────────────────────────

    def _on_frame(self, payload):
        frame, label = payload
        self._img_display.set_frame(frame, label)
        self._btn_scan.setEnabled(True)
        self._progress.setVisible(False)

    def _on_progress(self, cur: int, tot: int):
        self._progress.setRange(0, tot)
        self._progress.setValue(cur)

    def _set_status(self, msg: str):
        self._status_lbl.setText(msg)

    def _on_gemini_response(self, text: str):
        self._response_box.setPlainText(text)
        self._btn_analyze.setEnabled(True)
        self._set_status("Gemini response received")
        
        # Clean up text if Gemini wrapped it in markdown code blocks
        clean_json = text.strip()
        if clean_json.startswith("```json"):
            clean_json = clean_json[7:]
        if clean_json.endswith("```"):
            clean_json = clean_json[:-3]
        clean_json = clean_json.strip()

        try:
            data = json.loads(clean_json)
            if isinstance(data, list):
                self._gemini_paths = []
                for item in data:
                    txt = item.get("text", "")
                    tx = float(item.get("x_mm", 110))
                    ty = float(item.get("y_mm", 110))
                    # Convert text to handwriting paths
                    h_paths = text_to_handwriting(txt, tx, ty, size=6.0)
                    self._gemini_paths.extend(h_paths)
                
                if self._gemini_paths:
                    self._btn_plot_response.setEnabled(self.plotter.connected)
                    self._set_status(f"Generated {len(data)} answers as handwriting paths")
        except Exception as e:
            print(f"JSON Parse Error: {e}")
            self._gemini_paths = []

    def _plot_response_paths(self):
        paths = getattr(self, "_gemini_paths", [])
        if not paths:
            return
        # Expect: [ [[x,y], ...], ... ]  or  [{"pts": [[x,y],...]}]
        plot_paths = []
        for item in paths:
            if isinstance(item, list):
                plot_paths.append([(p[0], p[1]) for p in item if len(p) >= 2])
            elif isinstance(item, dict) and "pts" in item:
                plot_paths.append([(p[0], p[1]) for p in item["pts"] if len(p) >= 2])
        threading.Thread(target=self._run_plot, args=(plot_paths,), daemon=True).start()

    def _switch_tab(self, idx: int):
        frames = {
            1: (self._captured, "Captured"),
            2: (self._warped, "Detected / Warped"),
        }
        if idx == 0:
            # Live feed will update itself via timer
            self._img_display.clear("Live Feed — connect camera")
        elif idx in frames:
            frame, label = frames[idx]
            if frame is not None:
                self._img_display.set_frame(frame, label)
            else:
                self._img_display.clear(f"No {label.lower()} yet")
        elif idx == 3:
            if self._trace_paths:
                src = self._warped or self._captured
                if src is not None:
                    preview = draw_trace_preview(src, self._trace_paths)
                    self._img_display.set_frame(preview, f"Trace — {len(self._trace_paths)} paths")
                    return
            self._img_display.clear("Run Trace Edges first")

    # ── config persistence ────────────────────────────────────────────────────

    def _load_api_key(self) -> str:
        if CONFIG_FILE.exists():
            try:
                return json.loads(CONFIG_FILE.read_text()).get("gemini_api_key", "")
            except Exception:
                pass
        return ""

    def _save_api_key(self):
        data: dict = {}
        if CONFIG_FILE.exists():
            try:
                data = json.loads(CONFIG_FILE.read_text())
            except Exception:
                pass
        data["gemini_api_key"] = self._api_key.text().strip()
        CONFIG_FILE.write_text(json.dumps(data, indent=2))
