"""
Iron Sight — Live Preview + Browser Calibration
Streams annotated camera feed and runs calibration from the browser.

  python3 preview.py

Open on your Mac:  http://fraspberry.local:8080

Calibration:
  - Click each corner button while aiming at the matching point on the screen
  - After all 4, click Save — writes calibration.json and restarts ir_detect
"""

import cv2
import numpy as np
import time
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs
from picamera2 import Picamera2

FRAME_W, FRAME_H = 640, 480
CAL_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'calibration.json')
M = 0.2  # inset margin — calibration points are 20% from each corner

latest_jpeg = None
frame_lock = threading.Lock()

# Calibration state
cal_points = {}   # e.g. {'tl': (cx, cy), 'tr': ..., 'br': ..., 'bl': ...}
cal_lock = threading.Lock()

# Smoothed midpoint for display
smooth = {'x': 320.0, 'y': 240.0}
ALPHA = 0.25


def find_dots(gray):
    brightest = int(gray.max())
    threshold = max(80, int(brightest * 0.8))
    _, thresh = cv2.threshold(gray, threshold, 255, cv2.THRESH_BINARY)
    contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    dots = []
    for c in contours:
        if cv2.contourArea(c) < 3:
            continue
        M_m = cv2.moments(c)
        if M_m['m00'] > 0:
            dots.append((int(M_m['m10'] / M_m['m00']), int(M_m['m01'] / M_m['m00'])))
    return dots, brightest, threshold


def cluster_midpoint(dots):
    if len(dots) < 2:
        return None
    dots_sorted = sorted(dots, key=lambda d: d[0])
    half  = len(dots_sorted) // 2
    left  = dots_sorted[:half]
    right = dots_sorted[half:]
    lx = int(sum(d[0] for d in left)  / len(left))
    ly = int(sum(d[1] for d in left)  / len(left))
    rx = int(sum(d[0] for d in right) / len(right))
    ry = int(sum(d[1] for d in right) / len(right))
    return (lx, ly), (rx, ry), ((lx + rx) // 2, (ly + ry) // 2)


def camera_loop():
    global latest_jpeg, smooth
    picam2 = Picamera2()
    picam2.configure(picam2.create_video_configuration(
        main={"size": (FRAME_W, FRAME_H), "format": "RGB888"}
    ))
    picam2.start()
    picam2.set_controls({"AeEnable": False, "ExposureTime": 5000, "AnalogueGain": 2.0})
    time.sleep(1)

    while True:
        frame_rgb = picam2.capture_array()
        frame = cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2BGR)
        gray  = cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2GRAY)

        dots, brightest, threshold = find_dots(gray)
        result = cluster_midpoint(dots)

        # Draw raw dots
        for (dx, dy) in dots:
            cv2.circle(frame, (dx, dy), 8, (0, 255, 255), 2)

        if result:
            left_c, right_c, raw_mid = result
            cv2.circle(frame, left_c,  12, (0, 255, 0), 2)
            cv2.circle(frame, right_c, 12, (0, 255, 0), 2)
            cv2.line(frame, left_c, right_c, (0, 200, 0), 1)

            # Smooth midpoint
            smooth['x'] = ALPHA * raw_mid[0] + (1 - ALPHA) * smooth['x']
            smooth['y'] = ALPHA * raw_mid[1] + (1 - ALPHA) * smooth['y']
            mid = (int(smooth['x']), int(smooth['y']))
            cv2.circle(frame, mid, 8, (0, 0, 255), -1)
            cv2.putText(frame, f'aim: ({mid[0]/FRAME_W:.3f}, {mid[1]/FRAME_H:.3f})',
                        (10, FRAME_H - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 1)

        cv2.putText(frame, f'dots:{len(dots)}  bright:{brightest}  thresh:{threshold}',
                    (10, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 0), 1)

        # Draw saved calibration points
        with cal_lock:
            pts = dict(cal_points)
        for key, (px, py) in pts.items():
            cv2.drawMarker(frame, (px, py), (255, 128, 0),
                           cv2.MARKER_CROSS, 20, 2)

        _, jpg = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 75])
        with frame_lock:
            latest_jpeg = jpg.tobytes()


# ── HTTP server ───────────────────────────────────────────
HTML = """<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<title>Iron Sight Preview</title>
<style>
  * { margin:0; padding:0; box-sizing:border-box; }
  body { background:#111; color:#eee; font-family:monospace; display:flex;
         flex-direction:column; align-items:center; padding:12px; gap:12px; }
  img { width:100%; max-width:800px; border:1px solid #333; }
  #cal { display:grid; grid-template-columns:1fr 1fr; gap:8px; width:100%; max-width:800px; }
  button {
    padding:12px; background:#222; border:1px solid #444; color:#ccc;
    font-family:monospace; font-size:13px; cursor:pointer; border-radius:4px;
  }
  button:hover { background:#333; border-color:#888; }
  button.done { border-color:#0f0; color:#0f0; }
  #save { grid-column:1/-1; background:#1a1a1a; border-color:#f80; color:#f80; }
  #save:hover { background:#2a1a00; }
  #status { font-size:12px; color:#888; text-align:center; }
</style>
</head>
<body>
<img src="/stream">
<div id="cal">
  <button id="btn-tl" onclick="capture('tl')">⌜ TOP-LEFT (20% in)</button>
  <button id="btn-tr" onclick="capture('tr')">⌝ TOP-RIGHT (20% in)</button>
  <button id="btn-bl" onclick="capture('bl')">⌞ BOTTOM-LEFT (20% in)</button>
  <button id="btn-br" onclick="capture('br')">⌟ BOTTOM-RIGHT (20% in)</button>
  <button id="save" onclick="save()">SAVE CALIBRATION</button>
</div>
<div id="status">Aim at a corner point, then click its button to capture.</div>
<script>
async function capture(corner) {
  const r = await fetch('/capture?c=' + corner);
  const d = await r.json();
  if (d.ok) {
    document.getElementById('btn-' + corner).classList.add('done');
    document.getElementById('btn-' + corner).textContent =
      document.getElementById('btn-' + corner).textContent + '  ✓ (' + d.x + ', ' + d.y + ')';
    document.getElementById('status').textContent = 'Captured ' + corner + '. ' + d.remaining + ' remaining.';
  } else {
    document.getElementById('status').textContent = 'No dots detected — make sure IR bar is visible and try again.';
  }
}
async function save() {
  const r = await fetch('/save');
  const d = await r.json();
  document.getElementById('status').textContent = d.ok ? '✓ Calibration saved! Restart ir_detect.py to apply.' : 'Error: ' + d.error;
}
</script>
</body>
</html>"""

CORNERS = {
    'tl': (M,   M  ),
    'tr': (1-M, M  ),
    'br': (1-M, 1-M),
    'bl': (M,   1-M),
}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def send_json(self, data, code=200):
        body = json.dumps(data).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', len(body))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urlparse(self.path)

        if parsed.path == '/':
            body = HTML.encode()
            self.send_response(200)
            self.send_header('Content-Type', 'text/html')
            self.send_header('Content-Length', len(body))
            self.end_headers()
            self.wfile.write(body)

        elif parsed.path == '/stream':
            self.send_response(200)
            self.send_header('Content-Type', 'multipart/x-mixed-replace; boundary=frame')
            self.end_headers()
            try:
                while True:
                    with frame_lock:
                        frame = latest_jpeg
                    if frame:
                        self.wfile.write(b'--frame\r\nContent-Type: image/jpeg\r\n\r\n')
                        self.wfile.write(frame)
                        self.wfile.write(b'\r\n')
                    time.sleep(0.05)
            except Exception:
                pass

        elif parsed.path == '/capture':
            params = parse_qs(parsed.query)
            corner = params.get('c', [None])[0]
            if corner not in CORNERS:
                self.send_json({'ok': False, 'error': 'invalid corner'})
                return
            sx, sy = int(smooth['x']), int(smooth['y'])
            # Require dots to be detected (midpoint moved from default)
            if latest_jpeg is None:
                self.send_json({'ok': False})
                return
            with cal_lock:
                cal_points[corner] = (sx, sy)
                remaining = 4 - len(cal_points)
            self.send_json({'ok': True, 'x': sx, 'y': sy, 'remaining': remaining})

        elif parsed.path == '/save':
            with cal_lock:
                pts = dict(cal_points)
            if len(pts) < 4:
                self.send_json({'ok': False, 'error': f'Need 4 points, only have {len(pts)}'})
                return
            order = ['tl', 'tr', 'br', 'bl']
            src = np.float32([(pts[k][0], pts[k][1]) for k in order])
            dst = np.float32([CORNERS[k] for k in order])
            H, _ = cv2.findHomography(src, dst, cv2.RANSAC)
            if H is None:
                self.send_json({'ok': False, 'error': 'Homography failed'})
                return
            cal = {
                'homography': H.tolist(),
                'frame_width': FRAME_W,
                'frame_height': FRAME_H,
                'points': {k: {'camera': list(pts[k]), 'screen': list(CORNERS[k])} for k in order}
            }
            with open(CAL_PATH, 'w') as f:
                json.dump(cal, f, indent=2)
            self.send_json({'ok': True})

        else:
            self.send_response(404)
            self.end_headers()


print('Starting camera...')
cam_thread = threading.Thread(target=camera_loop, daemon=True)
cam_thread.start()
time.sleep(2)

print('Preview + calibration running:')
print('  http://fraspberry.local:8080')
print('Ctrl+C to stop.\n')
HTTPServer(('0.0.0.0', 8080), Handler).serve_forever()
