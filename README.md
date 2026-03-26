# Iron Sight — Interactive Shooting Gallery

A physical shooting gallery installation designed for museum deployment. A visitor picks up a replica rifle, aims it at projected targets on a wall, and pulls the trigger. The system detects where the gun is pointing using infrared tracking and registers hits, playing explosion effects and gunshot audio in response.

## Project Status

| Module | Status |
|--------|--------|
| Module 1: Browser Game | ✅ Complete |
| Module 2: Wiimote IR Aiming Bridge | 🔧 Next |
| Module 3: Final Museum Installation | 📋 Planned |

## Files

### Browser Games (Module 1)

Both files are fully self-contained — no external dependencies, all assets base64-embedded. Run in any modern browser.

**`shooting-gallery.html`** — Minimal/plain version
- Black background with classic bullseye targets
- Projection-mapping-ready base
- 30-second rounds, 1–2 targets on screen at once
- 3 hits to destroy, scoring by ring (5–50 pts)

**`dead-eye.html`** — Western-themed version
- CSS-generated sky/ground/sun background
- 4 silhouette target types: sheriff, bandit, bottle, tin can
- Bullet counter with reload mechanic (R key)
- 45-second rounds, 6-round chamber

### Shared Systems (both games)

- Real battle rifle gunshot audio (base64-embedded MP3, Web Audio API)
- Procedural fireball explosion engine (canvas-based, no sprites required)
- Two explosion tiers: small hit burst and large kill explosion
- Synthesised ricochet, destroy thud, and dry-click sounds
- Custom crosshair replaces system cursor
- Input: mouse click, spacebar, or any coordinate pair (ready for Wiimote injection)

## Architecture (Module 2 — Wiimote IR Bridge)

```
IR bar (2 fixed IR dots on screen edge)
  ↓  infrared light
Wiimote IR camera
  ↓  Bluetooth (Pi 3B)
Raspberry Pi 3B  ←  cwiid reads raw IR x,y coords
  ↓  WebSocket (port 8765, WiFi LAN)
Mac  ←  receives coords, injects into browser
  ↓  WebSocket / JS
Browser game  ←  moves crosshair, calls shoot()
```

## Architecture (Module 3 — Final Installation)

```
IR bar (USB-powered, fixed to projection surface)
  ↓  infrared light
PixArt IR camera (inside rifle stock)
  ↓  I2C
Raspberry Pi Pico
  ↓  USB-C
Raspberry Pi 3B (Chromium kiosk mode)
  ↓  HDMI
Projector
```

## Hardware

| Item | Role |
|------|------|
| Wiimote | IR camera source — prototype aiming |
| IR sensor bar | Emits 2 IR dots for Wiimote to track |
| Raspberry Pi 3B | Bluetooth bridge + game host |
| Raspberry Pi Zero W | Backup / dedicated BT reader |
| Projector | Game display surface |
| Solenoid actuator | Recoil simulation in rifle stock |

## Game Configuration

Both HTML files have a `CFG` object at the top of the script block. All game parameters are controlled there — no hunting through code.

## Next Steps

1. Flash Raspberry Pi 3 with Raspberry Pi OS Lite 64-bit (headless)
2. Install `cwiid` + `websockets` on Pi 3
3. Write `wiimote_bridge.py` — connects to Wiimote, reads IR dots, broadcasts WebSocket JSON
4. Write calibration routine — 4-corner calibration, saves transform matrix to JSON
5. Add WebSocket receiver block to both HTML game files
6. Test end-to-end: Wiimote → Pi 3 → Mac → game crosshair movement
7. Wire solenoid circuit and add GPIO pulse to bridge script
