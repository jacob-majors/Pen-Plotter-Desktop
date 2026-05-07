/*
  PlotterOS — Arduino Leonardo Controller
  =========================================
  Handles servo pen lift and hardware E-stop on a single USB serial connection.

  WIRING
  ------
    Servo signal wire  →  D9   (+ 5V red, GND black)
    E-stop button      →  D2 to GND   (INPUT_PULLUP, active LOW)
    Status LED         →  D13  (built-in, optional)

  SERIAL PROTOCOL  (9600 baud, newline-terminated)
  ------------------------------------------------
  Computer → Arduino:
    PEN_UP            Lift pen (servo to up angle)
    PEN_DOWN          Lower pen (servo to down angle)
    SET_UP:<angle>    Set pen-up angle and save to EEPROM  e.g. SET_UP:90
    SET_DOWN:<angle>  Set pen-down angle and save to EEPROM  e.g. SET_DOWN:30
    STATUS            Report current state

  Arduino → Computer:
    OK                Command accepted
    ESTOP             E-stop button was pressed
    STATE:UP          (response to STATUS when pen is up)
    STATE:DOWN        (response to STATUS when pen is down)

  UPLOAD
  ------
  Board: Arduino Leonardo (or Micro)
  Port:  whichever COM/tty the Leonardo enumerates on
  Baud:  9600

  After uploading, configure the port in PlotterOS:
    Plotter tab → Settings → ARDUINO LEONARDO section
*/

#include <Servo.h>
#include <EEPROM.h>

// ── Pin assignments ──────────────────────────────────────────────────────────
const int SERVO_PIN  = 9;
const int ESTOP_PIN  = 2;
const int LED_PIN    = 13;

// ── EEPROM addresses for persistent angle storage ───────────────────────────
const int EEPROM_UP_ADDR   = 0;
const int EEPROM_DOWN_ADDR = 1;
const int EEPROM_MAGIC_ADDR = 2;   // 0xAB means angles have been saved
const byte EEPROM_MAGIC     = 0xAB;

// ── Default angles (degrees) — adjust to match your servo/arm geometry ───────
const int POSITION_1 = 35;  // Pen UP
const int POSITION_2 = 100; // Pen DOWN

// ── Runtime state ────────────────────────────────────────────────────────────
Servo penServo;
int penUpAngle;
int penDownAngle;
bool penIsDown = false;

// ── Setup ────────────────────────────────────────────────────────────────────
void setup() {
  Serial.begin(9600);

  // Load angles from EEPROM (or use defaults on first boot)
  if (EEPROM.read(EEPROM_MAGIC_ADDR) == EEPROM_MAGIC) {
    penUpAngle   = EEPROM.read(EEPROM_UP_ADDR);
    penDownAngle = EEPROM.read(EEPROM_DOWN_ADDR);
  } else {
    penUpAngle   = POSITION_1;
    penDownAngle = POSITION_2;
  }

  penServo.attach(SERVO_PIN);
  penServo.write(penUpAngle);   // start in the up position

  pinMode(ESTOP_PIN, INPUT_PULLUP);
  pinMode(LED_PIN, OUTPUT);
  digitalWrite(LED_PIN, LOW);

  // Brief flash to signal the board is ready
  for (int i = 0; i < 3; i++) {
    digitalWrite(LED_PIN, HIGH); delay(80);
    digitalWrite(LED_PIN, LOW);  delay(80);
  }
}

// ── Main loop ────────────────────────────────────────────────────────────────
void loop() {
  // ── 1. Process serial commands from the computer ──────────────────────────
  if (Serial.available()) {
    String cmd = Serial.readStringUntil('\n');
    cmd.trim();
    handleCommand(cmd);
  }

  // ── 2. Poll E-stop button (active LOW) ───────────────────────────────────
  if (digitalRead(ESTOP_PIN) == LOW) {
    Serial.println("ESTOP");
    digitalWrite(LED_PIN, HIGH);        // LED on while button held

    // Wait for release before reporting again
    while (digitalRead(ESTOP_PIN) == LOW) delay(10);
    delay(50);                          // debounce
    digitalWrite(LED_PIN, LOW);
  }

  delay(5);
}

// ── Command handler ──────────────────────────────────────────────────────────
void handleCommand(const String& cmd) {
  if (cmd == "PEN_UP") {
    penServo.write(penUpAngle);
    penIsDown = false;
    Serial.println("OK");

  } else if (cmd == "PEN_DOWN") {
    penServo.write(penDownAngle);
    penIsDown = true;
    Serial.println("OK");

  } else if (cmd.startsWith("SET_UP:")) {
    int angle = cmd.substring(7).toInt();
    if (angle >= 0 && angle <= 180) {
      penUpAngle = angle;
      EEPROM.write(EEPROM_UP_ADDR, (byte)angle);
      EEPROM.write(EEPROM_MAGIC_ADDR, EEPROM_MAGIC);
      if (!penIsDown) penServo.write(penUpAngle);
      Serial.println("OK");
    } else {
      Serial.println("ERR:angle out of range 0-180");
    }

  } else if (cmd.startsWith("SET_DOWN:")) {
    int angle = cmd.substring(9).toInt();
    if (angle >= 0 && angle <= 180) {
      penDownAngle = angle;
      EEPROM.write(EEPROM_DOWN_ADDR, (byte)angle);
      EEPROM.write(EEPROM_MAGIC_ADDR, EEPROM_MAGIC);
      if (penIsDown) penServo.write(penDownAngle);
      Serial.println("OK");
    } else {
      Serial.println("ERR:angle out of range 0-180");
    }

  } else if (cmd == "STATUS") {
    Serial.print("STATE:");
    Serial.println(penIsDown ? "DOWN" : "UP");
    Serial.print("UP_ANGLE:");
    Serial.println(penUpAngle);
    Serial.print("DOWN_ANGLE:");
    Serial.println(penDownAngle);

  } else if (cmd.length() > 0) {
    Serial.println("ERR:unknown command");
  }
}
