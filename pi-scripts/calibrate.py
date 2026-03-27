"""
Iron Sight — 4-Corner Calibration
Run once on the Pi after mounting the camera on the rifle.

  python3 calibrate.py

Aim the rifle at each corner of the projected screen when prompted.
Hold still, press ENTER. Saves calibration.json when done.
Restart ir_detect.py to apply.
"""

import cv2
import numpy as np
import json
import os
from picamera2 import Picamera2

FRAME_W, FRAME_H = 640, 480
CAL_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'calibration.json')


def find_dots(gray):
    # Adaptive threshold: 80% of the brightest pixel in frame
    brightest = int(gray.max())
    threshold = max(80, int(brightest * 0.8))
    _, thresh = cv2.threshold(gray, threshold, 255, cv2.THRESH_BINARY)
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


def capture_stable(picam2, n=20):
    samples = []
    attempts = 0
    while len(samples) < n and attempts < n * 4:
        attempts += 1
        frame_rgb = picam2.capture_array()
        gray = cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2GRAY)
        dots = find_dots(gray)
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

    picam2 = Picamera2()
    picam2.configure(picam2.create_video_configuration(
        main={"size": (FRAME_W, FRAME_H), "format": "RGB888"}
    ))
    picam2.start()
    # Lock exposure — short shutter suppresses ambient light, IR dots stay bright
    picam2.set_controls({"AeEnable": False, "ExposureTime": 2000, "AnalogueGain": 1.0})
    import time; time.sleep(1)  # let controls settle
    print('Camera ready.\n')

    camera_pts = []
    screen_pts  = []

    for name, screen_pt in corners:
        # Live preview: show dot count until user is ready
        print(f'  Aim at {name} corner. Watching for dots... (press ENTER when steady)')
        while True:
            frame_rgb = picam2.capture_array()
            gray = cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2GRAY)
            dots = find_dots(gray)
            mp = cluster_midpoint(dots)
            status = f'dots:{len(dots)}' + (f'  pos:({mp[0]:.0f},{mp[1]:.0f})' if mp else '  no midpoint')
            print(f'\r  {status}    ', end='', flush=True)

            import select, sys
            if select.select([sys.stdin], [], [], 0)[0]:
                sys.stdin.readline()  # consume the Enter
                print()
                break

        pt, n = capture_stable(picam2, n=30)
        if pt is None:
            print(f'  Only got {n} frames with dots — try again.')
            continue
        print(f'  ✓  camera ({pt[0]:.1f}, {pt[1]:.1f})  →  screen {screen_pt}  [{n} frames]\n')
        camera_pts.append(pt)
        screen_pts.append(screen_pt)

    picam2.stop()

    src = np.float32(camera_pts)
    dst = np.float32(screen_pts)
    H, status = cv2.findHomography(src, dst, cv2.RANSAC)

    if H is None:
        print('\nERROR: could not compute homography — try again with steadier aim.')
        return

    inliers = int(status.sum()) if status is not None else '?'
    print(f'  Homography computed ({inliers}/4 inliers)')

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
