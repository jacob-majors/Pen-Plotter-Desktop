from __future__ import annotations
import json
import re
import serial
import serial.tools.list_ports
import threading
import time
from pathlib import Path

SETTINGS_FILE = Path(__file__).resolve().parent.parent.parent / "settings.json"

DEFAULT_SETTINGS: dict = {
    "x_min": 0.0,
    "x_max": 220.0,
    "y_min": 0.0,
    "y_max": 220.0,
    "z_up": 5.0,
    "z_down": -2.0,
    "feed_travel": 5000,
    "feed_draw": 1500,
    "soft_limits": True,
    "servo_settle_ms":  150,  # ms to wait after pen_up/pen_down before next move
    "servo_up_angle":    35,  # degrees — pen lifted
    "servo_down_angle":  100, # degrees — pen on paper
}

# Matches X or Y coordinate values inside a G-code line
_COORD_RE = re.compile(r"([XY])\s*(-?\d+\.?\d*)", re.IGNORECASE)
# Matches G0 / G00 / G1 / G01 at the start of a (stripped) command
_MOVE_RE = re.compile(r"^G0?[01]\b", re.IGNORECASE)


class MarlinPlotter:
    def __init__(self):
        self.ser = None
        self.connected = False
        self.lock = threading.Lock()
        self.position = {"x": 0.0, "y": 0.0, "z": 0.0}
        self.settings: dict = self._load_settings()

        # E-stop state — set() means stopped, clear() means running
        self._estop = threading.Event()
        # Track whether we last sent G90 (absolute) or G91 (relative)
        self._relative_mode = False

        # Optional ArduinoController for servo pen lift + E-stop button
        # Set externally:  plotter.arduino = arduino_controller_instance
        self.arduino = None

    # ── settings ──────────────────────────────────────────────────────────────

    def _load_settings(self) -> dict:
        base = dict(DEFAULT_SETTINGS)
        if SETTINGS_FILE.exists():
            try:
                base.update(json.loads(SETTINGS_FILE.read_text()))
            except Exception:
                pass
        return base

    def save_settings(self):
        SETTINGS_FILE.write_text(json.dumps(self.settings, indent=2))

    # ── soft-limit helpers ────────────────────────────────────────────────────

    def clamp(self, x: float, y: float) -> tuple[float, float]:
        if not self.settings.get("soft_limits", True):
            return x, y
        return (
            max(self.settings["x_min"], min(self.settings["x_max"], x)),
            max(self.settings["y_min"], min(self.settings["y_max"], y)),
        )

    def _clamp_gcode(self, cmd: str) -> str:
        """Clamp X/Y values in an absolute G0/G1 command."""
        if not _MOVE_RE.match(cmd.strip()):
            return cmd
        if self._relative_mode:
            return cmd  # relative moves can't be clamped without tracking

        def _replace(m: re.Match) -> str:
            axis = m.group(1).upper()
            val = float(m.group(2))
            if axis == "X":
                val = max(self.settings["x_min"], min(self.settings["x_max"], val))
            elif axis == "Y":
                val = max(self.settings["y_min"], min(self.settings["y_max"], val))
            return f"{axis}{val:.3f}"

        return _COORD_RE.sub(_replace, cmd)

    # ── connection ────────────────────────────────────────────────────────────

    @staticmethod
    def get_ports() -> list[str]:
        return [p.device for p in serial.tools.list_ports.comports()]

    def connect(self, port: str, baudrate: int = 115200) -> bool:
        if self.connected:
            self.disconnect()
        try:
            ser = serial.Serial()
            ser.port = port
            ser.baudrate = baudrate
            ser.timeout = 2
            ser.dtr = False
            ser.rts = False
            ser.open()
            self.ser = ser
            time.sleep(1) # wait for firmware to breathe
            self.ser.flushInput()
            self.connected = True
            return True
        except Exception as e:
            print(f"Connection error: {e}")
            return False

    def disconnect(self):
        with self.lock:
            if self.ser:
                self.ser.close()
            self.connected = False

    # ── E-stop ────────────────────────────────────────────────────────────────

    @property
    def estop_active(self) -> bool:
        return self._estop.is_set()

    def emergency_stop(self):
        """Halt immediately: set flag so queued commands are dropped, send M112."""
        self._estop.set()
        # Send M112 directly, bypassing the normal lock+check so it fires ASAP
        if self.connected and self.ser:
            try:
                self.ser.write(b"M112\n")
                self.ser.flush()
            except Exception:
                pass

    def reset_estop(self):
        """Clear E-stop and send M999 to re-enable the firmware."""
        self._estop.clear()
        if self.connected:
            self._send_raw("M999")

    # ── G-code sending ────────────────────────────────────────────────────────

    def _send_raw(self, command: str) -> bool:
        """Low-level send — no E-stop or limit checks."""
        with self.lock:
            try:
                self.ser.write((command + "\n").encode("utf-8"))
                while True:
                    resp = self.ser.readline().decode("utf-8").strip()
                    if resp.startswith("X:"):
                        for part in resp.split():
                            try:
                                if part.startswith("X:"):
                                    self.position["x"] = float(part[2:])
                                elif part.startswith("Y:"):
                                    self.position["y"] = float(part[2:])
                                elif part.startswith("Z:"):
                                    self.position["z"] = float(part[2:])
                            except ValueError:
                                pass
                    if resp.startswith("ok") or resp.startswith("Error") or not resp:
                        break
                return True
            except Exception as e:
                print(f"GCode error: {e}")
                return False

    def send_gcode(self, command: str) -> bool:
        # ① Bail immediately if E-stop is active
        if self._estop.is_set():
            return False
        if not self.connected:
            return False

        # ② Track absolute/relative mode
        stripped = command.strip().upper()
        if stripped.startswith("G91"):
            self._relative_mode = True
        elif stripped.startswith("G90"):
            self._relative_mode = False

        # ③ Clamp coordinates in absolute move commands
        if self.settings.get("soft_limits", True) and not self._relative_mode:
            command = self._clamp_gcode(command)

        return self._send_raw(command)

    # ── motion helpers ────────────────────────────────────────────────────────

    def jog(self, x: float = 0, y: float = 0, z: float = 0):
        self.send_gcode("G91")
        self.send_gcode(f"G0 X{x} Y{y} Z{z} F{self.settings['feed_travel']}")
        self.send_gcode("G90")

    def jog_continuous(self, dx: float, dy: float):
        if self.connected:
            self.send_gcode("G91")
            self.send_gcode(f"G1 X{dx} Y{dy} F{self.settings['feed_travel']}")
            self.send_gcode("G90")

    def move_to(self, x: float, y: float, feed: int | None = None):
        """Absolute move — coordinates are also clamped via send_gcode."""
        f = feed or self.settings["feed_travel"]
        self.send_gcode("G90")
        self.send_gcode(f"G0 X{x:.3f} Y{y:.3f} F{f}")

    def pen_up(self):
        """Lift pen — servo via Arduino (+ settle delay) or Z-axis G-code."""
        if self.arduino and self.arduino.is_connected:
            self.arduino.pen_up()
            # Wait for servo to reach the up position before the next move
            settle = self.settings.get("servo_settle_ms", 150) / 1000.0
            if settle > 0:
                time.sleep(settle)
        else:
            self.send_gcode(f"G0 Z{self.settings['z_up']:.2f} F3000")

    def pen_down(self):
        """Lower pen — servo via Arduino (+ settle delay) or Z-axis G-code."""
        if self.arduino and self.arduino.is_connected:
            self.arduino.pen_down()
            settle = self.settings.get("servo_settle_ms", 150) / 1000.0
            if settle > 0:
                time.sleep(settle)
        else:
            self.send_gcode(f"G0 Z{self.settings['z_down']:.2f} F1000")

    def request_position(self):
        if self.connected:
            self.send_gcode("M114")

    def home(self):
        self.send_gcode("G28 X Y")
