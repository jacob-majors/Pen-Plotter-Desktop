import cv2
import numpy as np
import json
import os
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QComboBox, QFrame, QMessageBox
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QImage, QPixmap
from core.vision import calibrate_camera, undistort_frame

class CameraPanel(QWidget):
    def __init__(self):
        super().__init__()
        self.calib_data = self.load_calibration()
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(40, 20, 40, 20)

        title = QLabel("Camera Station")
        title.setStyleSheet("font-size: 28px; font-weight: bold; color: #60a5fa; margin-bottom: 10px;")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        subtitle = QLabel("Single-Lens Plotter Workspace")
        subtitle.setStyleSheet("font-size: 14px; color: #9ca3af; margin-bottom: 30px;")
        subtitle.setAlignment(Qt.AlignCenter)
        layout.addWidget(subtitle)

        # Single Camera Card
        main_container = QHBoxLayout()
        main_container.addStretch()
        
        self.cam_card = self.create_camera_card("Active Plotter Camera", "0", "crosshair")
        main_container.addLayout(self.cam_card)
        
        main_container.addStretch()
        layout.addLayout(main_container)
        layout.addStretch()

        self.caps = {}
        self.timers = {}

    def load_calibration(self):
        if os.path.exists("calibration.json"):
            try:
                with open("calibration.json", "r") as f:
                    data = json.load(f)
                    return {
                        "mtx": np.array(data["mtx"]),
                        "dist": np.array(data["dist"])
                    }
            except: pass
        return {"mtx": None, "dist": None}

    def save_calibration(self, mtx, dist):
        data = {
            "mtx": mtx.tolist(),
            "dist": dist.tolist()
        }
        with open("calibration.json", "w") as f:
            json.dump(data, f)
        self.calib_data = {"mtx": mtx, "dist": dist}

    def create_camera_card(self, title, default_port, overlay_type):
        card_layout = QVBoxLayout()
        
        lbl_title = QLabel(title)
        lbl_title.setStyleSheet("font-weight: bold; font-size: 18px; color: #d1d5db; margin-bottom: 10px;")
        lbl_title.setAlignment(Qt.AlignCenter)
        card_layout.addWidget(lbl_title)

        # Settings bar
        settings_bar = QHBoxLayout()
        self.port_selector = QComboBox()
        for i in range(6):
            self.port_selector.addItem(f"Camera Port {i}", i)
        self.port_selector.setCurrentIndex(int(default_port))
        settings_bar.addWidget(self.port_selector)
        
        self.btn_calib = QPushButton("Calibrate Lens")
        self.btn_calib.clicked.connect(self.run_calibration)
        settings_bar.addWidget(self.btn_calib)
        card_layout.addLayout(settings_bar)

        self.display_label = QLabel()
        self.display_label.setFixedSize(640, 480)
        self.display_label.setStyleSheet("background-color: #000; border: 2px solid #333; border-radius: 12px;")
        self.display_label.setAlignment(Qt.AlignCenter)
        card_layout.addWidget(self.display_label)

        self.btn_toggle = QPushButton("Connect Camera Feed")
        self.btn_toggle.setObjectName("btnPrimary")
        self.btn_toggle.setFixedHeight(50)
        self.btn_toggle.setProperty("active", False)
        
        def toggle():
            active = self.btn_toggle.property("active")
            port = self.port_selector.currentData()
            if not active:
                if self.start_cam(port, self.display_label, overlay_type):
                    self.btn_toggle.setProperty("active", True)
                    self.btn_toggle.setText("Disconnect Camera")
                    self.btn_toggle.setStyleSheet("background-color: #7f1d1d; color: #f87171;")
            else:
                self.stop_cam(port)
                self.btn_toggle.setProperty("active", False)
                self.btn_toggle.setText("Connect Camera Feed")
                self.btn_toggle.setStyleSheet("")
                self.display_label.clear()
                self.display_label.setStyleSheet("background-color: #000; border: 2px solid #333; border-radius: 12px;")

        self.btn_toggle.clicked.connect(toggle)
        card_layout.addWidget(self.btn_toggle)
        
        return card_layout

    def run_calibration(self):
        port = self.port_selector.currentData()
        if port not in self.caps:
            QMessageBox.warning(self, "Error", "Start the camera feed first!")
            return
            
        ret, frame = self.caps[port].read()
        if ret:
            success, mtx, dist = calibrate_camera(frame)
            if success:
                self.save_calibration(mtx, dist)
                QMessageBox.information(self, "Success", "Lens calibration complete! Real-time correction is now active.")
            else:
                QMessageBox.warning(self, "Failure", "Could not find pattern. Ensure grid/chessboard is visible.")

    def start_cam(self, port, label_widget, overlay):
        cap = cv2.VideoCapture(port)
        if not cap.isOpened():
            return False
            
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

        self.caps[port] = cap
        timer = QTimer(self)
        timer.timeout.connect(lambda: self.update_frame(port, label_widget, overlay))
        timer.start(33)
        self.timers[port] = timer
        return True

    def stop_cam(self, port):
        if port in self.caps:
            self.timers[port].stop()
            self.caps[port].release()
            del self.timers[port]
            del self.caps[port]

    def update_frame(self, port, label_widget, overlay):
        cap = self.caps.get(port)
        if not cap or not cap.isOpened():
            return
        
        ret, frame = cap.read()
        if ret:
            if self.calib_data["mtx"] is not None:
                frame = undistort_frame(frame, self.calib_data["mtx"], self.calib_data["dist"])

            frame_resized = cv2.resize(frame, (640, 480))
            h, w = frame_resized.shape[:2]
            
            if overlay == "crosshair":
                cx, cy = w//2, h//2
                cv2.line(frame_resized, (cx-30, cy), (cx+30, cy), (244, 63, 94), 2)
                cv2.line(frame_resized, (cx, cy-30), (cx, cy+30), (244, 63, 94), 2)

            rgb_image = cv2.cvtColor(frame_resized, cv2.COLOR_BGR2RGB)
            qt_image = QImage(rgb_image.data, w, h, w * 3, QImage.Format_RGB888)
            label_widget.setPixmap(QPixmap.fromImage(qt_image))
