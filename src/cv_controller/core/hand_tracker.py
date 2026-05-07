import cv2
import math
import numpy as np
import queue
import threading
import urllib.request
from pathlib import Path

from PySide6.QtCore import QObject, Signal

MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/"
    "hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task"
)
MODEL_PATH = Path(__file__).resolve().parent.parent.parent.parent / "models" / "hand_landmarker.task"

WRIST = 0
THUMB_TIP = 4
INDEX_TIP = 8
MIDDLE_MCP = 9


class HandTracker(QObject):
    frame_ready = Signal(object)          # raw (mirrored) BGR frame — no ML delay
    status_changed = Signal(str)
    hand_position = Signal(float, float)  # (nx, ny) normalised palm position
    gesture_fired = Signal(str)           # "pinch_down" | "pinch_up"
    hand_landmarks = Signal(dict)         # {"landmarks": [(nx,ny)…], "pinch": bool}
    download_progress = Signal(int)

    PINCH_THRESHOLD = 0.25

    def __init__(self):
        super().__init__()
        self._queue: queue.Queue = queue.Queue(maxsize=1)
        self._running = False
        self._tracking_enabled = True
        self._cap = None
        self._capture_thread = None
        self._thread = None
        self._landmarker = None
        self._pinch_active = False

    # ── model ───────────────────────────────────────────────────��─────────────

    def model_ready(self) -> bool:
        return MODEL_PATH.exists()

    def ensure_model(self):
        MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
        if MODEL_PATH.exists():
            return

        def _dl():
            try:
                self.status_changed.emit("Downloading hand_landmarker.task (~25 MB)…")

                def _progress(count, block, total):
                    if total > 0:
                        self.download_progress.emit(min(99, int(count * block * 100 / total)))

                urllib.request.urlretrieve(MODEL_URL, MODEL_PATH, _progress)
                self.download_progress.emit(100)
                self.status_changed.emit("Model ready — click Start Tracking.")
            except Exception as exc:
                self.status_changed.emit(f"Download failed: {exc}")

        threading.Thread(target=_dl, daemon=True).start()

    # ── lifecycle ────────────────────────────────────────────────��────────────

    def start(self):
        if self._running:
            return
        if not MODEL_PATH.exists():
            self.ensure_model()
            self.status_changed.emit("Downloading model — click Start again when done.")
            return

        self._cap = cv2.VideoCapture(0)
        self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        self._cap.set(cv2.CAP_PROP_FPS, 30)

        if not self._cap.isOpened():
            self.status_changed.emit("Could not open camera.")
            return

        self._running = True
        self._capture_thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._capture_thread.start()
        self._thread = threading.Thread(target=self._process_loop, daemon=True)
        self._thread.start()
        self.status_changed.emit("Initialising hand model…")

    def stop(self):
        self._running = False
        if self._capture_thread:
            self._capture_thread.join(timeout=2)
            self._capture_thread = None
        if self._thread:
            self._thread.join(timeout=2)
            self._thread = None
        if self._cap:
            self._cap.release()
            self._cap = None
        if self._landmarker:
            self._landmarker.close()
            self._landmarker = None
        self.status_changed.emit("Stopped.")

    def enable_tracking(self):
        self._tracking_enabled = True

    def disable_tracking(self):
        self._tracking_enabled = False

    # ── frame capture — background thread ────────────────────────────────────

    def _capture_loop(self):
        while self._running:
            if not self._cap or not self._cap.isOpened():
                break
            ret, frame = self._cap.read()
            if not ret:
                import time
                time.sleep(0.001)
                continue
            frame = cv2.flip(frame, 1)
            fc = frame.copy()
            self.frame_ready.emit(fc)
            try:
                self._queue.put_nowait(fc)
            except queue.Full:
                pass

    # ── processing — background thread ───────────────────────────────────────

    def _init_landmarker(self):
        import mediapipe as mp
        from mediapipe.tasks.python import vision as mp_vision
        from mediapipe.tasks.python.core.base_options import BaseOptions

        options = mp_vision.HandLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=str(MODEL_PATH)),
            num_hands=1,
            running_mode=mp_vision.RunningMode.IMAGE,
        )
        self._landmarker = mp_vision.HandLandmarker.create_from_options(options)
        self.status_changed.emit("Tracking active.")

    def _process_loop(self):
        try:
            self._init_landmarker()
        except Exception as exc:
            self.status_changed.emit(f"MediaPipe init error: {exc}")
            self._running = False
            return

        while self._running:
            try:
                frame = self._queue.get(timeout=0.1)
            except queue.Empty:
                continue
            try:
                self._process_frame(frame)
            except Exception as exc:
                self.status_changed.emit(f"Frame error: {exc}")

    def _process_frame(self, frame: np.ndarray):
        if not self._landmarker or not self._running:
            return
        import mediapipe as mp

        # Frame is already mirrored from _grab_frame
        rgb = np.require(
            cv2.cvtColor(frame, cv2.COLOR_BGR2RGB),
            dtype=np.uint8,
            requirements=["C_CONTIGUOUS", "WRITEABLE", "OWNDATA"],
        )
        mp_img = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
        result = self._landmarker.detect(mp_img)

        if not result.hand_landmarks:
            return

        lms = result.hand_landmarks[0]
        points = [(lm.x, lm.y) for lm in lms]

        if self._tracking_enabled:
            palm = lms[MIDDLE_MCP]
            self.hand_position.emit(float(palm.x), float(palm.y))

            thumb = lms[THUMB_TIP]
            index = lms[INDEX_TIP]
            wrist = lms[WRIST]
            ref = lms[MIDDLE_MCP]

            hand_span = math.hypot(ref.x - wrist.x, ref.y - wrist.y) or 0.001
            pinch_dist = math.hypot(thumb.x - index.x, thumb.y - index.y)
            ratio = pinch_dist / hand_span

            if ratio < self.PINCH_THRESHOLD and not self._pinch_active:
                self._pinch_active = True
                self.gesture_fired.emit("pinch_down")
            elif ratio >= self.PINCH_THRESHOLD and self._pinch_active:
                self._pinch_active = False
                self.gesture_fired.emit("pinch_up")

        self.hand_landmarks.emit({"landmarks": points, "pinch": self._pinch_active})
