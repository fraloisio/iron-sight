# Iron Sight — Interactive Shooting Gallery

A museum installation where visitors aim a replica rifle at projected targets and pull the trigger. Infrared tracking detects where the gun is pointing and registers hits in a browser-based game. Designed for unattended operation in a public space.

**Created by:** Francesco Aloisio  
**Development assistance:** [Claude](https://claude.ai) (Anthropic)

---

## Table of Contents

1. [How It Works](#how-it-works)
2. [Hardware](#hardware)
3. [Wiring](#wiring)
4. [3D Files & Physical Assembly](#3d-files--physical-assembly)
5. [Space & Projector Setup](#space--projector-setup)
6. [Software Overview](#software-overview)
7. [Pi Setup](#pi-setup)
8. [Connection Modes](#connection-modes)
9. [First-Time Calibration](#first-time-calibration)
10. [Running the System](#running-the-system)
11. [Detection Parameters](#detection-parameters)
12. [Game Configuration](#game-configuration)

---

## How It Works

```
Wii IR bar (2 IR dots, fixed to projected surface)
  ↓  infrared light
Pi Camera v2 NoIR (inside rifle scope, points toward screen)
  ↓  picamera2 + OpenCV blob detection
Raspberry Pi Zero W2 (inside scope body)
  ↓  WebSocket JSON {x, y, shoot}  — port 8765
Browser game (shooting-gallery.html, any device on same network)
  ↓  moves crosshair, calls shoot() on trigger event
Projector → wall
```

The camera detects the two IR dots from the Wii bar and triangulates the midpoint. A homography transform (calibrated per installation) maps camera pixel coordinates to normalised screen coordinates [0–1]. The trigger microswitch sends a `shoot: true` flag via the same WebSocket message.

---

## Hardware

### Components

| Item | Model / Detail |
|------|---------------|
| Computer | Raspberry Pi Zero W2 |
| Camera | Raspberry Pi NoIR Camera Module v2.1 — 8 MP, 1080p, 75° FOV (IMX219 sensor) |
| IR emitter | Nintendo Wii sensor bar (OEM, USB-powered) |
| Laser pointer | KY-008 650 nm laser module (optional, used during calibration) |
| Trigger | Hinge Lever Micro Switch (NO contact wired to GPIO22) |
| Shutdown button | Momentary push button (wired to GPIO23 and GPIO3) |
| Rifle base | Gevær M/10 (Colt Canada C7 variant, Danish Army service rifle), decommissioned prop |
| Scope housing | 3D-printed faux scope — see `3d-files/` folder |
| Mounting | Picatinny rail system (rifle already had rails fitted) |
| Display | Projector — see [Space & Projector Setup](#space--projector-setup) |

> **Solenoid recoil:** A solenoid actuator was prototyped but removed from the final installation. The code in `ir_detect.py` still contains recoil logic (GPIO27). It is electrically harmless if nothing is wired to GPIO27, but set `RECOIL_ENABLED = False` at the top of `ir_detect.py` to suppress the GPIO output entirely.

---

## Wiring

All wires are soldered directly to the Pi Zero W2 GPIO header pins.

| Physical Pin | GPIO | Wire colour | Role |
|---|---|---|---|
| 2 | 5V | Red | (spare / future use) |
| 5 | GPIO3 | Yellow | Shutdown button — also hardware wake-from-halt |
| 6 | GND | Blue | Shared ground |
| 9 | GND | Green | Spare ground |
| 13 | GPIO27 | White | Recoil relay (unused — solenoid removed) |
| 14 | GND | Green | Trigger ground |
| 15 | GPIO22 | Brown | Trigger microswitch input |
| 16 | GPIO23 | Yellow | Shutdown button (software) |

### Microswitch wiring

| Microswitch terminal | Connects to |
|---|---|
| COM | Green wire → GND (Pin 14) |
| NO (Normally Open) | Brown wire → GPIO22 (Pin 15) |
| NC | Unconnected |

Pulling the trigger closes the NO contact, pulling GPIO22 LOW. The software uses an internal pull-up (`PUD_UP`) and triggers on `FALLING` edge with 120 ms debounce.

### Shutdown button

Two buttons both trigger shutdown. GPIO3 (Pin 5) has a hardware feature: pressing it also **powers the Pi back on** after a halt, so you can use the same button to turn on and off.

---

## 3D Files & Physical Assembly

All CAD and print files are in the `3d-files/` folder:

```
3d-files/
  *.3dm        Rhino source files (editable)
  *.stl        Print-ready STL files
  photos/      Assembly reference photos
```

### Assembly notes

- The scope body is 3D-printed in two halves that clamp around the Pi Zero W2.
- The **camera module** mounts flush at the **objective end** (the end pointing toward the screen/IR bar). The lens faces outward through a hole in the end cap.
- The **push button** (shutdown) mounts at the **eyepiece end** (the end facing the shooter).
- The assembled scope mounts onto the rifle's **Picatinny rail** using a standard rail clamp. No permanent modification to the rifle is required.
- Route the camera ribbon cable internally before closing the housing halves.
- The Pi's USB port (USB OTG) should remain accessible via a cutout for USB connection mode.

---

## Space & Projector Setup

These measurements were validated in the museum installation:

| Parameter | Value |
|---|---|
| Projector distance from wall | 3 m |
| Projector height (lens) | 60 cm from floor |
| Projected surface width | 1.65 m |
| Projected surface height | 1.02 m |
| Bottom edge of projected area | 1.65 m from floor |
| IR bar position | 25 cm below the top edge of the projected area, 60 cm from the top-right corner |
| Shooter position | 5.5 to 6 m from the wall, aligned with the centre of the projected area |

The current version of the software supports the IR bar placed either at the **top or bottom** of the projected area (not just the centre). Adjust the bar position and re-calibrate if the installation geometry differs.

> The IR bar should be USB-powered and fixed securely — any movement invalidates the calibration.

---

## Software Overview

### Files on the Pi (`~/`)

| File | Purpose |
|---|---|
| `ir_detect.py` | **Main process.** IR tracking + trigger + WebSocket server (port 8765). Run this during the game. |
| `preview.py` | **Calibration tool.** Live MJPEG preview at port 8080 with parameter sliders. Run this when setting up or re-calibrating. |
| `ironside-shutdown.py` | **Shutdown daemon.** Watches GPIO23 and GPIO3; halts the Pi on button press. Should always be running. |
| `ironside-portal.py` | **WiFi portal.** Runs when Pi is in hotspot mode; lets you connect the Pi to a WiFi network via a browser. |
| `calibration.json` | Homography matrix saved by `preview.py`. Loaded automatically by `ir_detect.py`. |
| `params.json` | Detection parameters saved by `preview.py`. Loaded automatically by `ir_detect.py`. |

### Files on the game device (laptop/Mac)

| File | Purpose |
|---|---|
| `shooting-gallery.html` | Main game — open in any browser |
| `config.js` | WebSocket connection config (Pi hostname and port). Edit this if the Pi's hostname or IP changes. |
| `ironside-manual.html` | Full operation manual. Serve locally with `python3 -m http.server 8080` to use the 3D viewer. |

`shooting-gallery.html` is fully self-contained — no server, no internet, no dependencies. Open directly in a browser.

### Architecture note

`ir_detect.py` and `ironside-shutdown.py` are independent processes. Run both in separate terminal sessions (or as systemd services — see [Running the System](#running-the-system)).

---

## Pi Setup

### OS

**Use Raspberry Pi OS Lite 32-bit** (not 64-bit).  
The 64-bit variant has a known NetworkManager bug that breaks WPA2 WiFi (`key-mgmt` negotiation fails). 32-bit works correctly.

Flash with Raspberry Pi Imager. Enable SSH and set hostname to `scope` in the imager's advanced options.

A pre-built image of a working installation is available at `archive/scope-backup-2026-04-28.img.gz`. Flash it directly — Raspberry Pi Imager can handle `.img.gz` without decompressing.

### Python dependencies

```bash
sudo apt update
sudo apt install -y python3-picamera2 python3-opencv python3-numpy python3-websockets
```

### Repository

```bash
git clone <repo-url>
# or copy the files manually via scp
```

The scripts expect to live in `~/` (home directory). `calibration.json` and `params.json` are read from the same directory as the script.

---

## Connection Modes

The Pi supports three connection modes. Choose based on what network infrastructure is available at the venue.

### Mode 1 — USB (simplest, no WiFi needed)

Connect the Pi to the game laptop with a USB **data** cable (Pi's USB OTG port, **not** the PWR port).

The Pi presents itself as a USB Ethernet adapter. Access the Pi at `scope.local` or `10.12.194.1`.

This mode requires USB gadget mode to be enabled in `/boot/config.txt` and `/boot/cmdline.txt`. See `ironside-manual.html` (Pi setup section) for the exact configuration steps.

### Mode 2 — WiFi (museum network)

Connect the Pi to the venue's WiFi. The Pi is reachable at `scope.local` on the same network.

To save a WiFi password onto the Pi:

```bash
sudo nmcli device wifi connect "SSID" password "password"
```

Or use Mode 3 (hotspot + portal) to do it from a browser without SSH.

### Mode 3 — Hotspot (Pi is the access point)

The Pi broadcasts its own WiFi network. The game laptop connects to it directly — no venue WiFi needed.

**Network:** `ironside`  
**Password:** `ironsight`  
**Pi address:** `10.42.0.1`

To activate the hotspot:

```bash
sudo nmcli connection up Hotspot
python3 ironside-portal.py  # optional: web UI to switch the Pi to a different WiFi
```

When the hotspot is active, navigate to `http://10.42.0.1` in a browser to get a portal page that lets you select a WiFi network and save credentials to the Pi (useful for switching from hotspot mode to museum WiFi mode without SSH).

> See `ironside-manual.html` for the full step-by-step network setup.

---

## First-Time Calibration

Calibration maps the camera's view to the projected screen. It must be done at the installation site with the projector on, the IR bar in place, and the rifle pointed at the screen.

1. Start the preview tool on the Pi:
   ```bash
   python3 preview.py
   ```

2. Open `http://scope.local:8080` in a browser on the game laptop.

3. Check the live feed — you should see two bright IR dots. If not, adjust **Exposure** down (try 1000–2000 µs) until ambient light is suppressed and only the IR dots are visible. Use **Dilation** to merge each dot cluster. **Save Params** when happy.

4. Aim the rifle at the **top-left** calibration target circle shown on the preview. Click **TOP-LEFT** in the browser.

5. Repeat for **TOP-RIGHT**, **BOTTOM-LEFT**, **BOTTOM-RIGHT**.

6. Click **SAVE CALIBRATION**. This writes `calibration.json`.

7. Stop `preview.py`. Start `ir_detect.py` (see below). The calibration loads automatically.

> Recalibrate if: the projector is moved, the IR bar is moved, or the scope is adjusted on the rail.

---

## Running the System

Both processes must be running during operation:

**Terminal 1 — Shutdown daemon:**
```bash
python3 ~/ironside-shutdown.py
```

**Terminal 2 — IR tracker + WebSocket:**
```bash
python3 ~/ir_detect.py
```

Then open `shooting-gallery.html` on the game laptop. The game connects to `ws://scope.local:8765` automatically.

### Optional: autostart on boot (recommended for museum deployment)

Create two systemd service files so the Pi starts the system without any manual steps after power-on.

**`/etc/systemd/system/ironside-shutdown.service`**
```ini
[Unit]
Description=Iron Sight shutdown button daemon
After=multi-user.target

[Service]
ExecStart=/usr/bin/python3 /home/admin/ironside-shutdown.py
Restart=always
User=admin

[Install]
WantedBy=multi-user.target
```

**`/etc/systemd/system/ironside.service`**
```ini
[Unit]
Description=Iron Sight IR tracker
After=network.target ironside-shutdown.service

[Service]
ExecStart=/usr/bin/python3 /home/admin/ir_detect.py
Restart=always
User=admin
WorkingDirectory=/home/admin

[Install]
WantedBy=multi-user.target
```

Enable both:
```bash
sudo systemctl daemon-reload
sudo systemctl enable ironside-shutdown.service ironside.service
sudo systemctl start ironside-shutdown.service ironside.service
```

---

## Detection Parameters

Accessible in `preview.py` at `http://scope.local:8080`. Changes apply live. Click **SAVE PARAMS** to persist — values are restored automatically on next startup.

| Parameter | Default | Effect |
|---|---|---|
| **Exposure (µs)** | 5000 | Sensor shutter time. Lower = darker image, isolates IR dots from ambient light. **This is the most important parameter.** Try 500–2000 µs for clean detection in lit environments. |
| **Gain** | 2.0 | Sensor amplification. Increase if IR dots are too faint at low exposure. |
| **Zoom** | 1.0 | Digital crop into the sensor frame. 1.0 = full 75° FOV. Recalibrate after changing. |
| **Dilation (px)** | 9 | Blob expansion before detection. Merges diffuse LED spots into solid clusters. Too high merges both clusters into one. |
| **Smoothing alpha** | 0.6 | EMA filter on crosshair position. 1.0 = instant (jittery). 0.1 = very smooth (laggy). |
| **Deadzone** | 0.004 | Minimum movement threshold (normalised 0–1). Prevents cursor drift when the rifle is held still. |
| **Max dot distance (px)** | 192 | Maximum pixel distance between the two IR clusters. Rejects false-positive pairs from other IR sources. |

**RESET** restores factory defaults without affecting the saved `params.json`.

---

## Game Configuration

`shooting-gallery.html` has a `CFG` object at the top of its `<script>` block. All timing, scoring, and gameplay parameters are set there.

The WebSocket address is set in `config.js` (not inside the HTML files) — update it there if the Pi's hostname or IP changes.
