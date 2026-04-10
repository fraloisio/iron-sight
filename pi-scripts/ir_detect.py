import cv2
import numpy as np
import asyncio
import websockets
import json
import threading
import os
import time
from picamera2 import Picamera2
import RPi.GPIO as GPIO

# ── GPIO setup ────────────────────────────────────────────
TRIGGER_PIN  = 22   # Brown — microswitch NO, fires shoot
RECOIL_PIN   = 27   # White — relay IN, drives solenoid
RECOIL_ENABLED = True
RECOIL_MS      = 300  # solenoid pulse duration in milliseconds

GPIO.setmode(GPIO.BCM)
GPIO.setup(TRIGGER_PIN, GPIO.IN,  pull_up_down=GPIO.PUD_UP)
GPIO.setup(RECOIL_PIN,  GPIO.OUT, initial=GPIO.LOW)

def fire_recoil():
    GPIO.output(RECOIL_PIN, GPIO.HIGH)
    time.sleep(RECOIL_MS / 1000)
    GPIO.output(RECOIL_PIN, GPIO.LOW)

def on_trigger(channel):
    latest_pos['shoot'] = True
    print('Trigger fired')
    if RECOIL_ENABLED:
        threading.Thread(target=fire_recoil, daemon=True).start()

GPIO.add_event_detect(TRIGGER_PIN, GPIO.FALLING, callback=on_trigger, bouncetime=120)

# ── Load calibration if it exists ────────────────────────
CAL_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'calibration.json')
H = None
if os.path.exists(CAL_PATH):
    with open(CAL_PATH) as f:
        cal = json.load(f)
    H = np.float32(cal['homography'])
    print(f'Calibration loaded from {CAL_PATH}')
else:
    print('No calibration.json — using raw normalised coords (run calibrate.py first)')

# ── WebSocket server ──────────────────────────────────────
latest_pos = {'x': 0.5, 'y': 0.5, 'shoot': False}
clients = set()

async def handler(websocket):
    clients.add(websocket)
    print(f'Client connected: {websocket.remote_address}')
    try:
        async for _ in websocket:
            pass
    except Exception:
        pass
    finally:
        clients.discard(websocket)
        print('Client disconnected')

async def broadcast():
    global clients
    while True:
        if clients:
            msg = json.dumps(latest_pos)
            dead = set()
            for ws in clients.copy():
                try:
                    await ws.send(msg)
                except Exception:
                    dead.add(ws)
            clients -= dead
        latest_pos['shoot'] = False
        await asyncio.sleep(0.016)

async def main():
    async with websockets.serve(handler, '0.0.0.0', 8765):
        print('WebSocket server running on port 8765')
        await broadcast()

# ── IR dot detection ──────────────────────────────────────
DILATION_PX = 9
MIN_BRIGHT  = 180

smooth_bright = {'v': 200.0}  # EMA-smoothed brightness

def find_clusters(gray):
    brightest = int(gray.max())
    if brightest < MIN_BRIGHT:
        return None
    smooth_bright['v'] = 0.1 * brightest + 0.9 * smooth_bright['v']
    _, thresh = cv2.threshold(gray, int(smooth_bright['v'] * 0.75), 255, cv2.THRESH_BINARY)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (DILATION_PX, DILATION_PX))
    dilated = cv2.dilate(thresh, kernel)
    contours, _ = cv2.findContours(dilated, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    blobs = []
    for c in contours:
        if cv2.contourArea(c) < 10 or cv2.contourArea(c) > 2000:
            continue
        M = cv2.moments(c)
        if M['m00'] > 0:
            blobs.append((cv2.contourArea(c), M['m10']/M['m00'], M['m01']/M['m00']))
    if len(blobs) < 2:
        return None
    blobs.sort(reverse=True)
    top2 = sorted(blobs[:2], key=lambda b: b[1])
    lx, ly = top2[0][1], top2[0][2]
    rx, ry = top2[1][1], top2[1][2]
    # Reject pairs that are too far apart — likely noise from different sources
    # Max allowed distance between the two clusters: 60% of frame width
    dist = ((rx - lx) ** 2 + (ry - ly) ** 2) ** 0.5
    if dist > 320 * 0.6:
        return None
    return ((lx + rx) / 2, (ly + ry) / 2)

def to_screen(cx, cy, frame_w=320, frame_h=180):
    if H is not None:
        pt = np.float32([[[cx, cy]]])
        out = cv2.perspectiveTransform(pt, H)
        nx, ny = float(out[0][0][0]), float(out[0][0][1])
    else:
        nx, ny = cx / frame_w, cy / frame_h
    return max(0.0, min(1.0, nx)), max(0.0, min(1.0, ny))

# ── Camera loop ───────────────────────────────────────────
ALPHA = 0.6
smooth = {'x': 0.5, 'y': 0.5}

def camera_loop():
    global latest_pos
    picam2 = Picamera2()
    picam2.configure(picam2.create_video_configuration(
        main={"size": (320, 180), "format": "RGB888"}
    ))
    picam2.start()
    picam2.set_controls({"AeEnable": False, "ExposureTime": 5000, "AnalogueGain": 2.0})
    import time; time.sleep(1)
    print('Camera started')

    while True:
        frame_rgb = picam2.capture_array()
        gray = cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2GRAY)
        mp = find_clusters(gray)
        if mp:
            nx, ny = to_screen(mp[0], mp[1])
            smooth['x'] = ALPHA * nx + (1 - ALPHA) * smooth['x']
            smooth['y'] = ALPHA * ny + (1 - ALPHA) * smooth['y']
            latest_pos['x'] = round(smooth['x'], 3)
            latest_pos['y'] = round(smooth['y'], 3)
            print(f'cam:({mp[0]:.0f},{mp[1]:.0f})  aim:({smooth["x"]:.3f},{smooth["y"]:.3f})')

print('Starting IR tracker + WebSocket server...')
cam_thread = threading.Thread(target=camera_loop, daemon=True)
cam_thread.start()
asyncio.run(main())
