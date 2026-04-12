#include <Wire.h>
#include <NintendoExtensionCtrl.h>
#include "USB.h"
#include "USBHID.h"

USBHID HID;

static const uint8_t desc_hid_report[] = {
  0x05, 0x01,        0x09, 0x08,        0xA1, 0x01,
  0xA1, 0x00,        0x85, 0x01,
  0x16, 0xA2, 0xFE,  0x26, 0x5E, 0x01,
  0x09, 0x30,        0x09, 0x31,        0x09, 0x32,
  0x75, 0x10,        0x95, 0x03,        0x81, 0x02,
  0xC0,
  0xA1, 0x00,        0x85, 0x02,
  0x09, 0x33,        0x09, 0x34,        0x09, 0x35,
  0x75, 0x10,        0x95, 0x03,        0x81, 0x02,
  0xC0,
  0xC0
};

class SpaceMouseHID : public USBHIDDevice {
public:
  SpaceMouseHID() {
    static bool initialized = false;
    if (!initialized) {
      initialized = true;
      HID.addDevice(this, sizeof(desc_hid_report));
    }
  }
  void begin() { HID.begin(); }
  uint16_t _onGetDescriptor(uint8_t *buffer) {
    memcpy(buffer, desc_hid_report, sizeof(desc_hid_report));
    return sizeof(desc_hid_report);
  }
  void sendTranslation(int16_t x, int16_t y, int16_t z) {
    uint8_t report[6];
    report[0] = x & 0xFF; report[1] = x >> 8;
    report[2] = y & 0xFF; report[3] = y >> 8;
    report[4] = z & 0xFF; report[5] = z >> 8;
    HID.SendReport(1, report, 6);
  }
  void sendRotation(int16_t rx, int16_t ry, int16_t rz) {
    uint8_t report[6];
    report[0] = rx & 0xFF; report[1] = rx >> 8;
    report[2] = ry & 0xFF; report[3] = ry >> 8;
    report[4] = rz & 0xFF; report[5] = rz >> 8;
    HID.SendReport(2, report, 6);
  }
};

SpaceMouseHID spaceMouse;
Nunchuk nchuk;

#define JOY_CENTER 128
#define DEADZONE 8
#define SCALE_SLOW 2
#define SCALE_FAST 5

void setup() {
  
  Serial.begin(115200);

  USB.VID(0x256F);
  USB.PID(0xC631);
  USB.manufacturerName("3Dconnexion");
  USB.productName("SpaceMouse Pro Wireless (cabled)");

  spaceMouse.begin();
  USB.begin();

  Wire.begin(D4, D5, 100000);
  nchuk.begin();
  while (!nchuk.connect()) {
    Serial.println("Nunchuk not found...");
    delay(1000);
  }
  Serial.println("Ready!");
}

void loop() {
  if (!nchuk.update()) return;

  bool c = nchuk.buttonC();
  bool z = nchuk.buttonZ();

  int jx = nchuk.joyX() - JOY_CENTER;
  int jy = nchuk.joyY() - JOY_CENTER;
  if (abs(jx) < DEADZONE) jx = 0;
  if (abs(jy) < DEADZONE) jy = 0;

  int scale = (z && !c) ? SCALE_FAST : SCALE_SLOW;
  jx = jx * scale;
  jy = jy * scale;

  if (!c && !z) {
    spaceMouse.sendRotation(jy, jx, 0);
    spaceMouse.sendTranslation(0, 0, 0);
  } else if (c && !z) {
    spaceMouse.sendTranslation(0, 0, -jy);
    spaceMouse.sendRotation(0, 0, 0);
  } else if (z && !c) {
    spaceMouse.sendTranslation(0, 0, -jy);
    spaceMouse.sendRotation(0, 0, 0);
  } else if (c && z) {
    spaceMouse.sendTranslation(jx, -jy, 0);
    spaceMouse.sendRotation(0, 0, 0);
  }

  delay(20);
}