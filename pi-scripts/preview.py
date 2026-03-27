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

FRAME_W, FRAME_H = 640, 360  # 16:9 — matches TV aspect ratio
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


DILATION_PX = 18   # merges LEDs within the same cluster into one blob
MIN_BRIGHT  = 180  # if frame max is below this, no IR bar is visible

def find_clusters(gray):
    """
    Returns (left_centroid, right_centroid, midpoint, debug_info) or None.
    Dilates the threshold mask so the 3 LEDs on each side merge into one blob,
    then finds the 2 largest blobs and treats them as left/right clusters.
    """
    brightest = int(gray.max())
    if brightest < MIN_BRIGHT:
        return None, brightest

    threshold = int(brightest * 0.75)
    _, thresh = cv2.threshold(gray, threshold, 255, cv2.THRESH_BINARY)

    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (DILATION_PX, DILATION_PX))
    dilated = cv2.dilate(thresh, kernel)

    contours, _ = cv2.findContours(dilated, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    blobs = []
    for c in contours:
        area = cv2.contourArea(c)
        if area < 30:
            continue
        M_m = cv2.moments(c)
        if M_m['m00'] > 0:
            cx = int(M_m['m10'] / M_m['m00'])
            cy = int(M_m['m01'] / M_m['m00'])
            blobs.append((area, cx, cy))

    if len(blobs) < 2:
        return None, brightest

    # Take 2 largest blobs, sort left to right
    blobs.sort(reverse=True)
    top2 = sorted(blobs[:2], key=lambda b: b[1])
    _, lx, ly = top2[0]
    _, rx, ry = top2[1]
    mid = ((lx + rx) // 2, (ly + ry) // 2)
    return (lx, ly), (rx, ry), mid, brightest


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

        result = find_clusters(gray)
        if result[0] is not None:
            left_c, right_c, raw_mid, brightest = result
            # Draw cluster centroids
            cv2.circle(frame, left_c,  14, (0, 255, 0), 2)
            cv2.circle(frame, right_c, 14, (0, 255, 0), 2)
            cv2.line(frame, left_c, right_c, (0, 220, 0), 1)
            # Smooth midpoint
            smooth['x'] = ALPHA * raw_mid[0] + (1 - ALPHA) * smooth['x']
            smooth['y'] = ALPHA * raw_mid[1] + (1 - ALPHA) * smooth['y']
            mid = (int(smooth['x']), int(smooth['y']))
            # Crosshair aim marker
            cv2.drawMarker(frame, mid, (0, 80, 255), cv2.MARKER_CROSS, 28, 2)
            cv2.circle(frame, mid, 10, (0, 80, 255), 1)
            cv2.putText(frame, f'aim ({mid[0]/FRAME_W:.3f}, {mid[1]/FRAME_H:.3f})',
                        (10, FRAME_H - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 80, 255), 1)
            cv2.putText(frame, f'bright:{brightest}  LOCKED', (10, 20),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 100), 1)
        else:
            brightest = result[1]
            cv2.putText(frame, f'bright:{brightest}  no IR bar',
                        (10, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 100, 255), 1)

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
  body { background:#000; overflow:hidden; }
  img { position:fixed; inset:0; width:100vw; height:100vh; object-fit:fill; }
  #ui {
    position:fixed; bottom:0; left:0; right:0;
    display:grid; grid-template-columns:1fr 1fr; gap:6px; padding:8px;
    background:rgba(0,0,0,0.6);
  }
  button {
    padding:10px; background:rgba(30,30,30,0.85); border:1px solid #444; color:#ccc;
    font-family:monospace; font-size:12px; cursor:pointer; border-radius:3px;
  }
  button:hover { background:rgba(60,60,60,0.9); border-color:#aaa; }
  button.done { border-color:#0f0; color:#0f0; background:rgba(0,60,0,0.85); }
  #save { grid-column:1/-1; border-color:#f80; color:#f80; }
  #save:hover { background:rgba(60,30,0,0.9); }
  #save.saved { border-color:#0f0; color:#0f0; background:rgba(0,60,0,0.85); }
  #status {
    position:fixed; top:0; left:0; right:0; text-align:center;
    font-family:monospace; font-size:15px; font-weight:bold;
    padding:8px; pointer-events:none;
    background:rgba(0,0,0,0.7); color:#fff;
  }
  #status.ok  { color:#0f0; }
  #status.err { color:#f44; }
</style>
</head>
<body>
<img src="/stream">
<div id="status">Aim at a corner point, then click its button to capture.</div>
<div id="ui">
  <button id="btn-tl" onclick="capture('tl')">⌜ TOP-LEFT (20% in)</button>
  <button id="btn-tr" onclick="capture('tr')">⌝ TOP-RIGHT (20% in)</button>
  <button id="btn-bl" onclick="capture('bl')">⌞ BOTTOM-LEFT (20% in)</button>
  <button id="btn-br" onclick="capture('br')">⌟ BOTTOM-RIGHT (20% in)</button>
  <button id="save" onclick="save()">SAVE CALIBRATION</button>
</div>
<script>
const status = document.getElementById('status');
function setStatus(msg, type) {
  status.textContent = msg;
  status.className = type || '';
}
async function capture(corner) {
  const btn = document.getElementById('btn-' + corner);
  btn.textContent = '⏳ capturing...';
  try {
    const d = await fetch('/capture?c=' + corner).then(r => r.json());
    if (d.ok) {
      btn.classList.add('done');
      btn.textContent = btn.textContent.split('⏳')[0] + ' ✓  (' + d.x + ', ' + d.y + ')';
      setStatus('✓ ' + corner.toUpperCase() + ' captured — ' + d.remaining + ' point(s) remaining.', 'ok');
    } else {
      btn.textContent = btn.textContent.replace('⏳ capturing...', corner);
      setStatus('✗ ' + (d.error || 'No IR bar detected — aim at the corner and try again.'), 'err');
    }
  } catch(e) {
    setStatus('✗ Request failed — is preview.py still running?', 'err');
  }
}
async function save() {
  document.getElementById('save').textContent = '⏳ saving...';
  try {
    const d = await fetch('/save').then(r => r.json());
    if (d.ok) {
      document.getElementById('save').classList.add('saved');
      document.getElementById('save').textContent = '✓ CALIBRATION SAVED';
      setStatus('✓ calibration.json saved — restart ir_detect.py to apply.', 'ok');
    } else {
      document.getElementById('save').textContent = 'SAVE CALIBRATION';
      setStatus('✗ Save failed: ' + d.error, 'err');
    }
  } catch(e) {
    setStatus('✗ Request failed.', 'err');
  }
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
            if latest_jpeg is None or smooth['x'] == 320.0:
                self.send_json({'ok': False, 'error': 'no IR bar detected'})
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
