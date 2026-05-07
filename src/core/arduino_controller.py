from __future__ import annotations
import threading
import serial
import serial.tools.list_ports
from PySide6.QtCore import QObject, Signal

ARDUINO_SKETCH = r"""
// PlotterOS — Arduino Leonardo controller
// Handles:  pen servo  +  E-stop button
//
// Wiring
//   Servo signal → D9      (+ 5 V / GND)
//   E-stop button → D2 to GND   (uses INPUT_PULLUP — active LOW)
//
// Serial: 9600 baud
// Commands from PC  →  "PEN_UP\n" | "PEN_DOWN\n"
// Reports to PC     →  "OK\n"     | "ESTOP\n"

#include <Servo.h>

Servo penServo;

const int SERVO_PIN    = 9;
const int ESTOP_PIN    = 2;
const int PEN_UP_DEG   = 90;   // ← adjust to your servo / plotter
const int PEN_DOWN_DEG = 30;   // ← adjust to your servo / plotter

void setup() {
  Serial.begin(9600);
  penServo.attach(SERVO_PIN);
  penServo.write(PEN_UP_DEG);
  pinMode(ESTOP_PIN, INPUT_PULLUP);
}

void loop() {
  // Commands from PC
  if (Serial.available()) {
    String cmd = Serial.readStringUntil('\n');
    cmd.trim();
    if (cmd == "PEN_UP") {
      penServo.write(PEN_UP_DEG);
      Serial.println("OK");
    } else if (cmd == "PEN_DOWN") {
      penServo.write(PEN_DOWN_DEG);
      Serial.println("OK");
    }
  }

  // E-stop button (active LOW)
  if (digitalRead(ESTOP_PIN) == LOW) {
    Serial.println("ESTOP");
    // Wait for button release before continuing
    while (digitalRead(ESTOP_PIN) == LOW) delay(10);
    delay(50);   // debounce
  }

  delay(5);
}
"""


class ArduinoController(QObject):
    """Manages the Arduino Leonardo serial link.

    Dual role on a single serial port:
    * Outgoing: PEN_UP / PEN_DOWN commands → servo
    * Incoming: ESTOP string → triggers estop_triggered signal
    """

    estop_triggered = Signal()
    connected_changed = Signal(bool)
    status_changed = Signal(str)

    def __init__(self):
        super().__init__()
        self._ser: serial.Serial | None = None
        self._thread: threading.Thread | None = None
        self._running = False

    # ── ports ──────────────────────────────────────────────────────────────────

    @staticmethod
    def available_ports() -> list[str]:
        return [p.device for p in serial.tools.list_ports.comports()]

    # ── lifecycle ──────────────────────────────────────────────────────────────

    def connect(self, port: str, baud: int = 9600) -> bool:
        if self._running:
            self.disconnect()
        try:
            self._ser = serial.Serial(port, baud, timeout=1)
            self._running = True
            self._thread = threading.Thread(target=self._read_loop, daemon=True)
            self._thread.start()
            self.connected_changed.emit(True)
            self.status_changed.emit("Connected")
            return True
        except serial.SerialException as exc:
            self.status_changed.emit(f"Error: {exc}")
            return False

    def disconnect(self):
        self._running = False
        if self._ser and self._ser.is_open:
            self._ser.close()
        if self._thread:
            self._thread.join(timeout=2)
        self._ser = None
        self._thread = None
        self.connected_changed.emit(False)
        self.status_changed.emit("Disconnected")

    @property
    def is_connected(self) -> bool:
        return self._running and self._ser is not None and self._ser.is_open

    # ── commands ───────────────────────────────────────────────────────────────

    def pen_up(self) -> bool:
        return self._send("PEN_UP")

    def pen_down(self) -> bool:
        return self._send("PEN_DOWN")

    def set_up_angle(self, angle: int) -> bool:
        """Send SET_UP:<angle> — saved to EEPROM on the Leonardo."""
        return self._send(f"SET_UP:{int(angle)}")

    def set_down_angle(self, angle: int) -> bool:
        """Send SET_DOWN:<angle> — saved to EEPROM on the Leonardo."""
        return self._send(f"SET_DOWN:{int(angle)}")

    def _send(self, cmd: str) -> bool:
        if not self.is_connected:
            return False
        try:
            self._ser.write((cmd + "\n").encode())
            return True
        except Exception:
            return False

    # ── read loop ──────────────────────────────────────────────────────────────

    def _read_loop(self):
        while self._running:
            try:
                raw = self._ser.readline()
                if not raw:
                    continue
                line = raw.decode("utf-8", errors="ignore").strip()
                if line == "ESTOP":
                    self.estop_triggered.emit()
            except serial.SerialException as exc:
                self.status_changed.emit(f"Serial error: {exc}")
                self._running = False
                self.connected_changed.emit(False)
            except Exception:
                pass
