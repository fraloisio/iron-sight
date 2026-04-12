"""
Iron Sight — Live Preview + Browser Calibration
Streams annotated camera feed and runs calibration from the browser.

  python3 preview.py

Open on your Mac:  http://fraspberry2.local:8080
"""

import cv2
import numpy as np
import time
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs
from picamera2 import Picamera2

FRAME_W, FRAME_H = 320, 240
CAL_PATH    = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'calibration.json')
PARAMS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'params.json')
M = 0.2

latest_jpeg = None
frame_lock  = threading.Lock()

cal_points = {}
cal_lock   = threading.Lock()

smooth = {'x': 160.0, 'y': 120.0}
smooth_bright = {'v': 200.0}

# ── Tunable params (live, no restart needed) ──────────────
params = {
    'exposure':   5000,
    'gain':       2.0,
    'min_bright': 180,
    'dilation':   9,
    'alpha':      0.6,
    'max_dot_dist': 192,  # max px between the two IR clusters (60% of frame width)
}
if os.path.exists(PARAMS_PATH):
    with open(PARAMS_PATH) as f:
        params.update(json.load(f))
    print(f'Params loaded from {PARAMS_PATH}')
params_lock   = threading.Lock()
camera_ref    = {'picam2': None}
apply_camera  = threading.Event()  # set when exposure/gain need updating

# live stats for the UI
stats = {'bright': 0, 'blobs': 0, 'locked': False}
stats_lock = threading.Lock()


def find_clusters(gray):
    with params_lock:
        min_bright    = params['min_bright']
        dilation      = params['dilation']
        max_dot_dist  = params['max_dot_dist']

    brightest = int(gray.max())
    with stats_lock:
        stats['bright'] = brightest

    if brightest < min_bright:
        with stats_lock:
            stats['blobs'] = 0
            stats['locked'] = False
        return None, brightest

    smooth_bright['v'] = 0.1 * brightest + 0.9 * smooth_bright['v']
    threshold = int(smooth_bright['v'] * 0.75)
    _, thresh = cv2.threshold(gray, threshold, 255, cv2.THRESH_BINARY)

    kernel  = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (dilation, dilation))
    dilated = cv2.dilate(thresh, kernel)

    contours, _ = cv2.findContours(dilated, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    blobs = []
    for c in contours:
        area = cv2.contourArea(c)
        if area < 10 or area > 2000:
            continue
        M_m = cv2.moments(c)
        if M_m['m00'] > 0:
            cx = int(M_m['m10'] / M_m['m00'])
            cy = int(M_m['m01'] / M_m['m00'])
            blobs.append((area, cx, cy))

    with stats_lock:
        stats['blobs'] = len(blobs)
        stats['locked'] = len(blobs) >= 2

    if len(blobs) < 2:
        return None, brightest

    blobs.sort(reverse=True)
    top2 = sorted(blobs[:2], key=lambda b: b[1])
    _, lx, ly = top2[0]
    _, rx, ry = top2[1]
    dist = ((rx - lx) ** 2 + (ry - ly) ** 2) ** 0.5
    if dist > max_dot_dist:
        with stats_lock:
            stats['blobs'] = len(blobs)
            stats['locked'] = False
        return None, brightest
    mid = ((lx + rx) // 2, (ly + ry) // 2)
    return (lx, ly), (rx, ry), mid, brightest


def camera_loop():
    global latest_jpeg, smooth
    picam2 = Picamera2()
    picam2.configure(picam2.create_video_configuration(
        main={"size": (FRAME_W, FRAME_H), "format": "RGB888"}
    ))
    picam2.start()
    with params_lock:
        picam2.set_controls({"AeEnable": False,
                              "ExposureTime": params['exposure'],
                              "AnalogueGain": params['gain']})
    camera_ref['picam2'] = picam2
    time.sleep(1)

    while True:
        # Apply camera setting changes if requested
        if apply_camera.is_set():
            apply_camera.clear()
            with params_lock:
                picam2.set_controls({"AeEnable": False,
                                     "ExposureTime": params['exposure'],
                                     "AnalogueGain": params['gain']})

        with params_lock:
            alpha = params['alpha']

        frame_rgb = picam2.capture_array()
        frame     = cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2BGR)
        gray      = cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2GRAY)

        result = find_clusters(gray)
        if result[0] is not None:
            left_c, right_c, raw_mid, brightest = result
            cv2.circle(frame, left_c,  14, (0, 255, 0), 2)
            cv2.circle(frame, right_c, 14, (0, 255, 0), 2)
            cv2.line(frame, left_c, right_c, (0, 220, 0), 1)
            smooth['x'] = alpha * raw_mid[0] + (1 - alpha) * smooth['x']
            smooth['y'] = alpha * raw_mid[1] + (1 - alpha) * smooth['y']
            mid = (int(smooth['x']), int(smooth['y']))
            cv2.drawMarker(frame, mid, (0, 80, 255), cv2.MARKER_CROSS, 28, 2)
            cv2.circle(frame, mid, 10, (0, 80, 255), 1)
            cv2.putText(frame, f'aim ({mid[0]/FRAME_W:.3f}, {mid[1]/FRAME_H:.3f})',
                        (10, FRAME_H - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 80, 255), 1)
            cv2.putText(frame, f'bright:{brightest}  LOCKED',
                        (10, 14), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 255, 100), 1)
        else:
            brightest = result[1]
            cv2.putText(frame, f'bright:{brightest}  no IR bar',
                        (10, 14), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 100, 255), 1)

        # Draw calibration targets
        targets = {
            'tl': (int(M * FRAME_W),        int(M * FRAME_H)),
            'tr': (int((1-M) * FRAME_W),    int(M * FRAME_H)),
            'br': (int((1-M) * FRAME_W),    int((1-M) * FRAME_H)),
            'bl': (int(M * FRAME_W),         int((1-M) * FRAME_H)),
        }
        with cal_lock:
            pts = dict(cal_points)
        for key, (tx, ty) in targets.items():
            colour = (0, 255, 0) if key in pts else (255, 255, 255)
            filled = -1 if key in pts else 2
            cv2.circle(frame, (tx, ty), 10, colour, filled)
            cv2.drawMarker(frame, (tx, ty), colour, cv2.MARKER_CROSS, 24, 2)

        _, jpg = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 75])
        with frame_lock:
            latest_jpeg = jpg.tobytes()


# ── HTML ──────────────────────────────────────────────────
HTML = """<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<title>Iron Sight Preview</title>
<style>
  * { margin:0; padding:0; box-sizing:border-box; }
  body { background:#000; overflow:hidden; font-family:monospace; }
  img { position:fixed; inset:0; width:100vw; height:100vh; object-fit:fill; }

  #panel {
    position:fixed; top:0; right:0; bottom:0; width:220px;
    background:rgba(0,0,0,0.82); border-left:1px solid #333;
    display:flex; flex-direction:column; gap:0; overflow-y:auto;
  }
  #panel h2 { color:#f80; font-size:11px; padding:8px 10px 4px; border-bottom:1px solid #333; }

  .section { padding:8px 10px; border-bottom:1px solid #222; }
  .section label { color:#aaa; font-size:10px; display:block; margin-bottom:3px; }
  .section .val  { color:#fff; font-size:11px; float:right; }
  input[type=range] { width:100%; accent-color:#f80; cursor:pointer; }

  #stats { background:rgba(0,0,0,0.5); padding:8px 10px; font-size:11px; }
  .stat  { display:flex; justify-content:space-between; padding:2px 0; }
  .stat span { color:#aaa; }
  .stat b    { color:#fff; }
  .stat b.ok  { color:#0f0; }
  .stat b.err { color:#f44; }

  #cal { padding:8px 10px; display:flex; flex-direction:column; gap:5px; }
  button {
    padding:7px 6px; background:rgba(30,30,30,0.9); border:1px solid #444;
    color:#ccc; font-family:monospace; font-size:11px; cursor:pointer; border-radius:3px;
  }
  button:hover { background:rgba(60,60,60,0.9); border-color:#aaa; }
  button.done  { border-color:#0f0; color:#0f0; }
  #save        { border-color:#f80; color:#f80; }
  #reset       { border-color:#f44; color:#f44; }
  #saveparams  { border-color:#08f; color:#08f; }
  #save.saved { border-color:#0f0; color:#0f0; }

  #status {
    position:fixed; top:0; left:0; right:220px; text-align:center;
    font-family:monospace; font-size:13px; font-weight:bold;
    padding:6px; pointer-events:none;
    background:rgba(0,0,0,0.7); color:#fff;
  }
  #status.ok  { color:#0f0; }
  #status.err { color:#f44; }
</style>
</head>
<body>
<img src="/stream">
<div id="status">Aim at a corner target, then click its button.</div>

<div id="panel">
  <h2>DETECTION PARAMS</h2>

  <div class="section">
    <label>Exposure (µs) <span class="val" id="v-exposure">5000</span></label>
    <input type="range" id="s-exposure" min="500" max="15000" step="500" value="5000"
           oninput="updateParam('exposure', this.value)">
  </div>
  <div class="section">
    <label>Gain <span class="val" id="v-gain">2.0</span></label>
    <input type="range" id="s-gain" min="1" max="8" step="0.5" value="2"
           oninput="updateParam('gain', this.value)">
  </div>
  <div class="section">
    <label>Dilation px <span class="val" id="v-dilation">9</span></label>
    <input type="range" id="s-dilation" min="3" max="20" step="1" value="9"
           oninput="updateParam('dilation', this.value)">
  </div>
  <div class="section">
    <label>Smoothing alpha <span class="val" id="v-alpha">0.6</span></label>
    <input type="range" id="s-alpha" min="0.05" max="1" step="0.05" value="0.6"
           oninput="updateParam('alpha', this.value)">
  </div>
  <div class="section">
    <label>Max dot distance px <span class="val" id="v-max_dot_dist">192</span></label>
    <input type="range" id="s-max_dot_dist" min="20" max="320" step="5" value="192"
           oninput="updateParam('max_dot_dist', this.value)">
  </div>

  <h2>LIVE STATS</h2>
  <div id="stats">
    <div class="stat"><span>Brightness</span><b id="st-bright">—</b></div>
    <div class="stat"><span>Blobs found</span><b id="st-blobs">—</b></div>
    <div class="stat"><span>Status</span><b id="st-locked">—</b></div>
  </div>

  <button id="saveparams" onclick="saveParams()" style="margin:8px 10px 0;">SAVE PARAMS</button>

  <h2>CALIBRATION</h2>
  <div id="cal">
    <button id="btn-tl" onclick="capture('tl')">⌜ TOP-LEFT</button>
    <button id="btn-tr" onclick="capture('tr')">⌝ TOP-RIGHT</button>
    <button id="btn-bl" onclick="capture('bl')">⌞ BOTTOM-LEFT</button>
    <button id="btn-br" onclick="capture('br')">⌟ BOTTOM-RIGHT</button>
    <button id="save"  onclick="save()">SAVE CALIBRATION</button>
    <button id="reset" onclick="resetCal()">RESET / START OVER</button>
  </div>
</div>

<script>
const status = document.getElementById('status');
function setStatus(msg, type) { status.textContent = msg; status.className = type || ''; }

// ── Live stats polling ──
async function pollStats() {
  try {
    const d = await fetch('/stats').then(r => r.json());
    document.getElementById('st-bright').textContent = d.bright;
    document.getElementById('st-blobs').textContent  = d.blobs;
    const el = document.getElementById('st-locked');
    el.textContent  = d.locked ? 'LOCKED' : 'no IR bar';
    el.className    = d.locked ? 'ok' : 'err';
  } catch(e) {}
  setTimeout(pollStats, 200);
}
pollStats();

// ── Param sliders ──
async function saveParams() {
  const btn = document.getElementById('saveparams');
  btn.textContent = '⏳ saving...';
  try {
    const d = await fetch('/saveparams').then(r => r.json());
    btn.textContent = d.ok ? '✓ PARAMS SAVED' : 'SAVE PARAMS';
  } catch(e) { btn.textContent = 'SAVE PARAMS'; }
  setTimeout(() => btn.textContent = 'SAVE PARAMS', 2000);
}
async function updateParam(key, val) {
  document.getElementById('v-' + key).textContent = parseFloat(val);
  await fetch('/setparam?' + key + '=' + val);
}

// ── Calibration ──
async function capture(corner) {
  const btn = document.getElementById('btn-' + corner);
  const orig = btn.textContent;
  btn.textContent = '⏳ ...';
  try {
    const d = await fetch('/capture?c=' + corner).then(r => r.json());
    if (d.ok) {
      btn.classList.add('done');
      btn.textContent = orig + ' ✓';
      setStatus('✓ ' + corner.toUpperCase() + ' captured — ' + d.remaining + ' left.', 'ok');
    } else {
      btn.textContent = orig;
      setStatus('✗ ' + (d.error || 'No IR bar — aim and retry.'), 'err');
    }
  } catch(e) { btn.textContent = orig; setStatus('✗ Request failed.', 'err'); }
}
async function resetCal() {
  await fetch('/reset');
  ['tl','tr','br','bl'].forEach(c => {
    const btn = document.getElementById('btn-' + c);
    btn.classList.remove('done');
    btn.textContent = btn.textContent.replace(' ✓','');
  });
  document.getElementById('save').classList.remove('saved');
  document.getElementById('save').textContent = 'SAVE CALIBRATION';
  setStatus('Reset — aim at a corner target, then click its button.', '');
}
async function save() {
  document.getElementById('save').textContent = '⏳ saving...';
  try {
    const d = await fetch('/save').then(r => r.json());
    if (d.ok) {
      document.getElementById('save').classList.add('saved');
      document.getElementById('save').textContent = '✓ SAVED';
      setStatus('✓ calibration.json saved — restart ir_detect.py to apply.', 'ok');
    } else {
      document.getElementById('save').textContent = 'SAVE CALIBRATION';
      setStatus('✗ Save failed: ' + d.error, 'err');
    }
  } catch(e) { setStatus('✗ Request failed.', 'err'); }
}
</script>
</body>
</html>"""

CORNERS = {
    'tl': (0.0, 0.0),
    'tr': (1.0, 0.0),
    'br': (1.0, 1.0),
    'bl': (0.0, 1.0),
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

        elif parsed.path == '/stats':
            with stats_lock:
                self.send_json(dict(stats))

        elif parsed.path == '/setparam':
            qs = parse_qs(parsed.query)
            with params_lock:
                camera_changed = False
                for key, vals in qs.items():
                    if key not in params:
                        continue
                    val = float(vals[0])
                    if key in ('exposure', 'min_bright', 'dilation'):
                        val = int(val)
                    params[key] = val
                    if key in ('exposure', 'gain'):
                        camera_changed = True
                if camera_changed:
                    apply_camera.set()
            self.send_json({'ok': True})

        elif parsed.path == '/saveparams':
            with params_lock:
                data = dict(params)
            with open(PARAMS_PATH, 'w') as f:
                json.dump(data, f, indent=2)
            self.send_json({'ok': True})

        elif parsed.path == '/reset':
            with cal_lock:
                cal_points.clear()
            self.send_json({'ok': True})

        elif parsed.path == '/capture':
            qs = parse_qs(parsed.query)
            corner = qs.get('c', [None])[0]
            if corner not in CORNERS:
                self.send_json({'ok': False, 'error': 'invalid corner'})
                return
            sx, sy = int(smooth['x']), int(smooth['y'])
            if latest_jpeg is None or smooth['x'] == 160.0:
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
print('  http://fraspberry2.local:8080')
print('Ctrl+C to stop.\n')
ThreadingHTTPServer(('0.0.0.0', 8080), Handler).serve_forever()
