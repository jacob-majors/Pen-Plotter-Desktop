import cv2
import numpy as np
import queue
import threading
import time
import urllib.request
from pathlib import Path

from PySide6.QtCore import QObject, Signal

MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/"
    "face_landmarker/face_landmarker/float16/1/face_landmarker.task"
)
MODEL_PATH = Path(__file__).resolve().parent.parent.parent.parent / "models" / "face_landmarker.task"

MAX_ANGLE = 30.0

GESTURE_THRESHOLDS = {
    "eyeBlinkLeft": 0.35,
    "eyeBlinkRight": 0.35,
    "jawOpen": 0.55,
}

SERIAL_CHANNELS = ["btn0", "btn1", "jack0", "jack1", "jack2", "jack3"]

AVAILABLE_ACTIONS = [
    "none",
    "left_click", "right_click", "middle_click",
    "scroll_up", "scroll_down",
    "key:space", "key:return", "key:escape", "key:tab",
    "toggle_tracking", "speed_up", "speed_down",
]

DEFAULT_GESTURE_ACTIONS = {
    "eyeBlinkLeft": "left_click",
    "eyeBlinkRight": "right_click",
    "jawOpen": "scroll_up",
}


class ActionExecutor:
    def __init__(self):
        self._mouse = None
        self._keyboard = None
        self.gesture_actions: dict = dict(DEFAULT_GESTURE_ACTIONS)
        self.serial_actions: dict = {ch: "none" for ch in SERIAL_CHANNELS}
        self.tracker_ref = None

    def _controllers(self):
        if self._mouse is None:
            from pynput import mouse as _m, keyboard as _k
            self._mouse = _m.Controller()
            self._keyboard = _k.Controller()
        return self._mouse, self._keyboard

    def execute(self, action: str):
        if not action or action == "none":
            return
        try:
            from pynput import mouse as _m, keyboard as _k
            mouse_ctrl, kbd_ctrl = self._controllers()
            if action == "left_click":
                mouse_ctrl.click(_m.Button.left)
            elif action == "right_click":
                mouse_ctrl.click(_m.Button.right)
            elif action == "middle_click":
                mouse_ctrl.click(_m.Button.middle)
            elif action == "scroll_up":
                mouse_ctrl.scroll(0, 3)
            elif action == "scroll_down":
                mouse_ctrl.scroll(0, -3)
            elif action.startswith("key:"):
                key_map = {
                    "space": _k.Key.space,
                    "return": _k.Key.enter,
                    "escape": _k.Key.esc,
                    "tab": _k.Key.tab,
                }
                name = action[4:]
                key = key_map.get(name) or (name[0] if len(name) == 1 else None)
                if key:
                    kbd_ctrl.tap(key)
            elif action == "toggle_tracking" and self.tracker_ref:
                t = self.tracker_ref
                t.disable_tracking() if t._tracking_enabled else t.enable_tracking()
            elif action == "speed_up" and self.tracker_ref:
                self.tracker_ref.cursor_speed = min(30, self.tracker_ref.cursor_speed + 2)
            elif action == "speed_down" and self.tracker_ref:
                self.tracker_ref.cursor_speed = max(1, self.tracker_ref.cursor_speed - 2)
        except Exception:
            pass

    def execute_gesture(self, gesture: str):
        self.execute(self.gesture_actions.get(gesture, "none"))

    def execute_serial(self, channel: int):
        name = SERIAL_CHANNELS[channel] if channel < len(SERIAL_CHANNELS) else str(channel)
        self.execute(self.serial_actions.get(name, "none"))


class FaceTracker(QObject):
    frame_ready = Signal(object)      # raw BGR numpy array (emitted at camera FPS, no ML delay)
    status_changed = Signal(str)
    gesture_fired = Signal(str)
    head_delta = Signal(int, int)     # (dx, dy) per frame
    face_landmarks = Signal(list)     # list of (nx, ny) normalised — drawn in overlay
    download_progress = Signal(int)

    def __init__(self, executor: ActionExecutor = None):
        super().__init__()
        self._executor = executor
        if executor:
            executor.tracker_ref = self

        self._queue: queue.Queue = queue.Queue(maxsize=1)
        self._running = False
        self._tracking_enabled = True
        self._cap = None
        self._capture_thread = None
        self._thread = None
        self._landmarker = None

        self.deadzone: float = 0.15
        self.cursor_speed: int = 10
        self.hold_time_ms: int = 300
        self.move_os_cursor: bool = False  # disabled by default for canvas mode

        self._gesture_start: dict = {}
        self._gesture_fired_set: set = set()

    # ── model ─────────────────────────────────────────────────────────────────

    def model_ready(self) -> bool:
        return MODEL_PATH.exists()

    def ensure_model(self):
        MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
        if MODEL_PATH.exists():
            return

        def _dl():
            try:
                self.status_changed.emit("Downloading face_landmarker.task (~30 MB)…")

                def _progress(count, block, total):
                    if total > 0:
                        self.download_progress.emit(min(99, int(count * block * 100 / total)))

                urllib.request.urlretrieve(MODEL_URL, MODEL_PATH, _progress)
                self.download_progress.emit(100)
                self.status_changed.emit("Model ready — click Start Tracking.")
            except Exception as exc:
                self.status_changed.emit(f"Download failed: {exc}")

        threading.Thread(target=_dl, daemon=True).start()

    # ── lifecycle ─────────────────────────────────────────────────────────────

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
        self.status_changed.emit("Initialising face model…")

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
                time.sleep(0.001)
                continue
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

        options = mp_vision.FaceLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=str(MODEL_PATH)),
            output_face_blendshapes=True,
            output_facial_transformation_matrixes=True,
            num_faces=1,
            running_mode=mp_vision.RunningMode.IMAGE,
        )
        self._landmarker = mp_vision.FaceLandmarker.create_from_options(options)
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

        rgb = np.require(
            cv2.cvtColor(frame, cv2.COLOR_BGR2RGB),
            dtype=np.uint8,
            requirements=["C_CONTIGUOUS", "WRITEABLE", "OWNDATA"],
        )
        mp_img = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
        result = self._landmarker.detect(mp_img)

        if not result.face_landmarks:
            return

        # Emit landmark positions for the overlay to draw (fast, no OpenCV)
        lms = [(lm.x, lm.y) for lm in result.face_landmarks[0]]
        self.face_landmarks.emit(lms)

        if result.facial_transformation_matrixes:
            mat = np.array(list(result.facial_transformation_matrixes[0].data)).reshape(4, 4)
            yaw, pitch = self._euler_from_matrix(mat)
            if self._tracking_enabled:
                self._apply_movement(yaw, pitch)

        if result.face_blendshapes and self._tracking_enabled:
            shapes = {bs.category_name: bs.score for bs in result.face_blendshapes[0]}
            self._check_gestures(shapes)

    # ── pose ─────────────────────────────────────────────────────────────────

    def _euler_from_matrix(self, mat: np.ndarray):
        R = mat[:3, :3]
        sy = float(np.sqrt(R[0, 0] ** 2 + R[1, 0] ** 2))
        if sy > 1e-6:
            yaw = float(np.degrees(np.arctan2(R[1, 0], R[0, 0])))
            pitch = float(np.degrees(np.arctan2(-R[2, 0], sy)))
        else:
            yaw = 0.0
            pitch = float(np.degrees(np.arctan2(-R[2, 0], sy)))
        return yaw, pitch

    def _apply_movement(self, yaw: float, pitch: float):
        dz = self.deadzone * MAX_ANGLE
        span = max(1.0, MAX_ANGLE - dz)

        def _delta(angle: float) -> int:
            excess = abs(angle) - dz
            if excess <= 0:
                return 0
            t = min(1.0, excess / span)
            return int(np.sign(angle) * t * self.cursor_speed * 7)

        dx = _delta(yaw)
        dy = _delta(pitch)
        if dx != 0 or dy != 0:
            self.head_delta.emit(dx, dy)
            if self.move_os_cursor:
                try:
                    from pynput import mouse as _m
                    _m.Controller().move(dx, dy)
                except Exception:
                    pass

    def _draw_pose(self, frame: np.ndarray, yaw: float, pitch: float):
        dz = self.deadzone * MAX_ANGLE
        color = (0, 230, 230)
        h, w = frame.shape[:2]
        cv2.putText(frame, f"Y:{yaw:+.0f}  P:{pitch:+.0f}",
                    (10, h - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 230, 0), 1)
        if abs(yaw) > dz:
            cv2.putText(frame, "RIGHT" if yaw > 0 else "LEFT",
                        (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)
        if abs(pitch) > dz:
            cv2.putText(frame, "DOWN" if pitch > 0 else "UP",
                        (10, 55), cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)

    # ── gesture detection ─────────────────────────────────────────────────────

    def _check_gestures(self, shapes: dict):
        now = time.time()
        for gesture, threshold in GESTURE_THRESHOLDS.items():
            score = shapes.get(gesture, 0.0)
            if score >= threshold:
                if gesture not in self._gesture_start:
                    self._gesture_start[gesture] = now
                elif (now - self._gesture_start[gesture]) * 1000 >= self.hold_time_ms:
                    if gesture not in self._gesture_fired_set:
                        self._gesture_fired_set.add(gesture)
                        self.gesture_fired.emit(gesture)
                        if self._executor:
                            self._executor.execute_gesture(gesture)
            else:
                self._gesture_start.pop(gesture, None)
                self._gesture_fired_set.discard(gesture)
