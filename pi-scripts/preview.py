"""
Iron Sight — Live Camera Preview
Streams annotated camera feed to your browser.

  python3 preview.py

Then open on your Mac:  http://fraspberry.local:8080
Shows detected IR dots, midpoint, and brightness info.
Ctrl+C to stop.
"""

import cv2
import numpy as np
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from picamera2 import Picamera2
import threading

FRAME_W, FRAME_H = 640, 480
latest_jpeg = None
lock = threading.Lock()


def find_dots(gray):
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
            dots.append((int(M['m10'] / M['m00']), int(M['m01'] / M['m00'])))
    return dots, int(brightest), int(threshold)


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
    mx = (lx + rx) // 2
    my = (ly + ry) // 2
    return (lx, ly), (rx, ry), (mx, my)


def camera_loop():
    global latest_jpeg
    picam2 = Picamera2()
    picam2.configure(picam2.create_video_configuration(
        main={"size": (FRAME_W, FRAME_H), "format": "RGB888"}
    ))
    picam2.start()
    picam2.set_controls({"AeEnable": False, "ExposureTime": 2000, "AnalogueGain": 1.0})
    time.sleep(1)

    while True:
        frame_rgb = picam2.capture_array()
        frame = cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2BGR)
        gray  = cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2GRAY)

        dots, brightest, threshold = find_dots(gray)
        result = cluster_midpoint(dots)

        # Draw each dot
        for (dx, dy) in dots:
            cv2.circle(frame, (dx, dy), 8, (0, 255, 255), 2)

        if result:
            left_c, right_c, mid = result
            cv2.circle(frame, left_c,  12, (0, 255, 0), 2)   # left cluster — green
            cv2.circle(frame, right_c, 12, (0, 255, 0), 2)   # right cluster — green
            cv2.circle(frame, mid,      6, (0, 0, 255), -1)  # midpoint — red filled
            cv2.line(frame, left_c, right_c, (0, 200, 0), 1)
            nx = round(mid[0] / FRAME_W, 3)
            ny = round(mid[1] / FRAME_H, 3)
            cv2.putText(frame, f'aim: ({nx}, {ny})', (10, FRAME_H - 10),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 1)

        cv2.putText(frame, f'dots:{len(dots)}  bright:{brightest}  thresh:{threshold}',
                    (10, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 0), 1)

        _, jpg = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
        with lock:
            latest_jpeg = jpg.tobytes()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass  # suppress request logs

    def do_GET(self):
        if self.path == '/':
            self.send_response(200)
            self.send_header('Content-Type', 'text/html')
            self.end_headers()
            self.wfile.write(b'''<html><body style="margin:0;background:#000">
<img src="/stream" style="width:100%;height:100vh;object-fit:contain">
</body></html>''')
        elif self.path == '/stream':
            self.send_response(200)
            self.send_header('Content-Type', 'multipart/x-mixed-replace; boundary=frame')
            self.end_headers()
            try:
                while True:
                    with lock:
                        frame = latest_jpeg
                    if frame:
                        self.wfile.write(b'--frame\r\nContent-Type: image/jpeg\r\n\r\n')
                        self.wfile.write(frame)
                        self.wfile.write(b'\r\n')
                    time.sleep(0.05)
            except Exception:
                pass


print('Starting camera...')
cam_thread = threading.Thread(target=camera_loop, daemon=True)
cam_thread.start()
time.sleep(2)

print('Preview running — open on your Mac:')
print('  http://fraspberry.local:8080')
print('Ctrl+C to stop.\n')
HTTPServer(('0.0.0.0', 8080), Handler).serve_forever()
