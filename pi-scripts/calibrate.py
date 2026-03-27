"""
Iron Sight — 4-Corner Calibration
Run once on the Pi after mounting the camera on the rifle.

  python3 calibrate.py

Aim the rifle at each corner of the PROJECTED SCREEN AREA when prompted.
Hold still, press ENTER. Saves calibration.json when done.
Restart ir_detect.py to apply.
"""

import cv2
import numpy as np
import subprocess
import json
import os

FRAME_W, FRAME_H = 640, 480
CAL_PATH = os.path.join(os.path.dirname(__file__), 'calibration.json')


def start_camera():
    cmd = [
        'rpicam-vid', '--width', str(FRAME_W), '--height', str(FRAME_H),
        '--framerate', '30', '--codec', 'mjpeg',
        '--output', '-', '--timeout', '0', '--nopreview'
    ]
    return subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)


def read_frame(process):
    buf = b''
    while True:
        chunk = process.stdout.read(4096)
        if not chunk:
            return None
        buf += chunk
        start = buf.find(b'\xff\xd8')
        end   = buf.find(b'\xff\xd9')
        if start != -1 and end != -1 and end > start:
            jpg = buf[start:end + 2]
            return cv2.imdecode(np.frombuffer(jpg, np.uint8), cv2.IMREAD_COLOR)


def find_dots(frame):
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
    if len(dots) < 2:
        return None
    dots_sorted = sorted(dots, key=lambda d: d[0])
    half  = len(dots_sorted) // 2
    left  = dots_sorted[:half]
    right = dots_sorted[half:]
    lx = sum(d[0] for d in left)  / len(left)
    ly = sum(d[1] for d in left)  / len(left)
    rx = sum(d[0] for d in right) / len(right)
    ry = sum(d[1] for d in right) / len(right)
    return ((lx + rx) / 2, (ly + ry) / 2)


def capture_stable(process, n=20):
    """Average the midpoint over n successful frames."""
    samples = []
    attempts = 0
    while len(samples) < n and attempts < n * 4:
        attempts += 1
        frame = read_frame(process)
        if frame is None:
            continue
        dots = find_dots(frame)
        mp = cluster_midpoint(dots)
        if mp:
            samples.append(mp)

    if len(samples) < 5:
        return None, len(samples)

    x = sum(s[0] for s in samples) / len(samples)
    y = sum(s[1] for s in samples) / len(samples)
    return (x, y), len(samples)


def main():
    print('\n── Iron Sight  4-Corner Calibration ──────────────────')
    print('Aim the rifle at each corner of the projected screen.')
    print('Hold steady and press ENTER to capture each corner.\n')

    corners = [
        ('TOP-LEFT',     (0.0, 0.0)),
        ('TOP-RIGHT',    (1.0, 0.0)),
        ('BOTTOM-RIGHT', (1.0, 1.0)),
        ('BOTTOM-LEFT',  (0.0, 1.0)),
    ]

    process = start_camera()

    camera_pts = []
    screen_pts  = []

    for name, screen_pt in corners:
        while True:
            input(f'\n  Aim at {name} corner → press ENTER when steady: ')
            pt, n = capture_stable(process, n=20)
            if pt is None:
                print(f'  Only got {n} frames with dots — check IR bar is powered and visible. Try again.')
                continue
            print(f'  ✓  camera ({pt[0]:.1f}, {pt[1]:.1f})  →  screen {screen_pt}  [{n} frames]')
            camera_pts.append(pt)
            screen_pts.append(screen_pt)
            break

    process.terminate()

    # Compute homography: camera pixel coords → normalised screen coords (0–1)
    src = np.float32(camera_pts)
    dst = np.float32(screen_pts)
    H, status = cv2.findHomography(src, dst, cv2.RANSAC)

    if H is None:
        print('\nERROR: could not compute homography — try again with steadier aim.')
        return

    inliers = int(status.sum()) if status is not None else '?'
    print(f'\n  Homography computed ({inliers}/4 inliers)')

    cal = {
        'homography': H.tolist(),
        'frame_width': FRAME_W,
        'frame_height': FRAME_H,
        'corners': {name: {'camera': list(cp), 'screen': list(sp)}
                    for (name, sp), cp in zip(corners, camera_pts)}
    }
    with open(CAL_PATH, 'w') as f:
        json.dump(cal, f, indent=2)

    print(f'  Saved → {CAL_PATH}')
    print('\n  Restart ir_detect.py to apply calibration.\n')


main()
