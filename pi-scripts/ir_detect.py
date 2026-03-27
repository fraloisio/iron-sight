import cv2
import numpy as np
import subprocess
import asyncio
import websockets
import json
import threading
import os

# ── Load calibration if it exists ────────────────────────
CAL_PATH = os.path.join(os.path.dirname(__file__), 'calibration.json')
H = None  # homography matrix
if os.path.exists(CAL_PATH):
    with open(CAL_PATH) as f:
        cal = json.load(f)
    H = np.float32(cal['homography'])
    print(f'Calibration loaded from {CAL_PATH}')
else:
    print('No calibration.json found — using raw normalised coords (run calibrate.py first)')

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
        await asyncio.sleep(0.033)  # ~30 fps

async def main():
    async with websockets.serve(handler, '0.0.0.0', 8765):
        print('WebSocket server running on port 8765')
        await broadcast()

# ── IR dot detection ──────────────────────────────────────
def find_dots(frame):
    """Return list of (x, y) centroids for all bright IR dots in frame."""
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    _, thresh = cv2.threshold(gray, 200, 255, cv2.THRESH_BINARY)
    contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    dots = []
    for c in contours:
        if cv2.contourArea(c) < 3:
            continue
        M = cv2.moments(c)
        if M['m00'] > 0:
            dots.append((M['m10'] / M['m00'], M['m01'] / M['m00']))
    return dots

def cluster_midpoint(dots):
    """
    Split dots into left/right clusters by x position.
    Return (midpoint_x, midpoint_y) in camera pixel coords, or None if < 2 dots.
    """
    if len(dots) < 2:
        return None
    dots_sorted = sorted(dots, key=lambda d: d[0])
    half = len(dots_sorted) // 2
    left  = dots_sorted[:half]
    right = dots_sorted[half:]
    lx = sum(d[0] for d in left)  / len(left)
    ly = sum(d[1] for d in left)  / len(left)
    rx = sum(d[0] for d in right) / len(right)
    ry = sum(d[1] for d in right) / len(right)
    return ((lx + rx) / 2, (ly + ry) / 2)

def to_screen(cx, cy, frame_w=640, frame_h=480):
    """
    Map camera-space midpoint to normalised screen coords (0.0–1.0).
    Uses homography if calibrated, otherwise simple normalisation.
    """
    if H is not None:
        pt = np.float32([[[cx, cy]]])
        out = cv2.perspectiveTransform(pt, H)
        nx, ny = float(out[0][0][0]), float(out[0][0][1])
    else:
        nx = cx / frame_w
        ny = cy / frame_h
    # clamp to valid range
    return max(0.0, min(1.0, nx)), max(0.0, min(1.0, ny))

# ── Camera loop ───────────────────────────────────────────
def camera_loop():
    global latest_pos
    cmd = [
        'rpicam-vid', '--width', '640', '--height', '480',
        '--framerate', '30', '--codec', 'mjpeg',
        '--output', '-', '--timeout', '0', '--nopreview'
    ]
    process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    buf = b''
    while True:
        chunk = process.stdout.read(4096)
        if not chunk:
            break
        buf += chunk
        start = buf.find(b'\xff\xd8')
        end   = buf.find(b'\xff\xd9')
        if start == -1 or end == -1 or end <= start:
            continue
        jpg = buf[start:end + 2]
        buf = buf[end + 2:]
        frame = cv2.imdecode(np.frombuffer(jpg, np.uint8), cv2.IMREAD_COLOR)
        if frame is None:
            continue

        dots = find_dots(frame)
        mp = cluster_midpoint(dots)
        if mp:
            nx, ny = to_screen(mp[0], mp[1])
            latest_pos['x'] = round(nx, 3)
            latest_pos['y'] = round(ny, 3)
            print(f'dots:{len(dots)}  cam:({mp[0]:.0f},{mp[1]:.0f})  aim:({nx:.3f},{ny:.3f})')

print('Starting IR tracker + WebSocket server...')
cam_thread = threading.Thread(target=camera_loop, daemon=True)
cam_thread.start()
asyncio.run(main())
