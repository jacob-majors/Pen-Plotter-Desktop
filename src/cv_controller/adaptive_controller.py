from __future__ import annotations
import json
import threading

import serial
import serial.tools.list_ports
from PySide6.QtCore import QObject, Signal

from cv_controller.core.tracker import SERIAL_CHANNELS

NUM_CHANNELS = len(SERIAL_CHANNELS)

ARDUINO_SKETCH = r"""// Adaptive Controller — Arduino Leonardo
// Reads 2 buttons (D2, D3) and 4 jack sockets (D4–D7), sends JSON at 9600 baud.
// Wiring: switch/jack connects pin to GND; INPUT_PULLUP inverts to active-HIGH logic.

const int PINS[6] = {2, 3, 4, 5, 6, 7};

void setup() {
  Serial.begin(9600);
  for (int i = 0; i < 6; i++) {
    pinMode(PINS[i], INPUT_PULLUP);
  }
}

void loop() {
  int v[6];
  for (int i = 0; i < 6; i++) v[i] = !digitalRead(PINS[i]);

  Serial.print("{");
  Serial.print("\"b0\":"); Serial.print(v[0]); Serial.print(",");
  Serial.print("\"b1\":"); Serial.print(v[1]); Serial.print(",");
  Serial.print("\"j0\":"); Serial.print(v[2]); Serial.print(",");
  Serial.print("\"j1\":"); Serial.print(v[3]); Serial.print(",");
  Serial.print("\"j2\":"); Serial.print(v[4]); Serial.print(",");
  Serial.print("\"j3\":"); Serial.print(v[5]);
  Serial.println("}");
  delay(20);
}
"""


class SerialThread(QObject):
    button_pressed = Signal(int)         # channel index 0-5 on rising edge
    connected_changed = Signal(bool)
    error = Signal(str)

    def __init__(self, executor):
        super().__init__()
        self._executor = executor
        self._serial: serial.Serial | None = None
        self._thread: threading.Thread | None = None
        self._running = False
        self._last_state = [0] * NUM_CHANNELS

    @staticmethod
    def available_ports() -> list[str]:
        return [p.device for p in serial.tools.list_ports.comports()]

    def connect(self, port: str, baud: int = 9600) -> bool:
        try:
            self._serial = serial.Serial(port, baud, timeout=1)
            self._running = True
            self._last_state = [0] * NUM_CHANNELS
            self._thread = threading.Thread(target=self._read_loop, daemon=True)
            self._thread.start()
            self.connected_changed.emit(True)
            return True
        except serial.SerialException as exc:
            self.error.emit(str(exc))
            return False

    def disconnect(self):
        self._running = False
        if self._serial and self._serial.is_open:
            self._serial.close()
        if self._thread:
            self._thread.join(timeout=2)
        self._serial = None
        self._thread = None
        self.connected_changed.emit(False)

    def _read_loop(self):
        while self._running:
            try:
                raw = self._serial.readline()
                if not raw:
                    continue
                data = json.loads(raw.decode("utf-8").strip())
                current = [
                    int(data.get("b0", 0)),
                    int(data.get("b1", 0)),
                    int(data.get("j0", 0)),
                    int(data.get("j1", 0)),
                    int(data.get("j2", 0)),
                    int(data.get("j3", 0)),
                ]
                for i, (prev, curr) in enumerate(zip(self._last_state, current)):
                    if prev == 0 and curr == 1:
                        self.button_pressed.emit(i)
                        self._executor.execute_serial(i)
                self._last_state = current
            except json.JSONDecodeError:
                pass
            except serial.SerialException as exc:
                self.error.emit(str(exc))
                self._running = False
            except Exception:
                pass
