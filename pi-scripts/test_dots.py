"""Quick diagnostic — prints what the camera sees every second. Ctrl+C to stop."""
import cv2
import numpy as np
from picamera2 import Picamera2

picam2 = Picamera2()
picam2.configure(picam2.create_video_configuration(
    main={"size": (640, 480), "format": "RGB888"}
))
picam2.start()
print('Camera started. Point at the IR bar. Ctrl+C to stop.\n')

frame_count = 0
try:
    while True:
        frame_rgb = picam2.capture_array()
        frame_count += 1
        if frame_count % 30 != 0:
            continue

        gray = cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2GRAY)
        brightest = int(gray.max())
        print(f'Brightest pixel: {brightest}')

        for threshold in [240, 220, 200, 180, 150]:
            _, thresh = cv2.threshold(gray, threshold, 255, cv2.THRESH_BINARY)
            contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            dots = []
            for c in contours:
                area = cv2.contourArea(c)
                if area < 1:
                    continue
                M = cv2.moments(c)
                if M['m00'] > 0:
                    cx = int(M['m10'] / M['m00'])
                    cy = int(M['m01'] / M['m00'])
                    dots.append((cx, cy, round(area, 1)))
            print(f'  threshold {threshold}: {len(dots)} dots  {dots[:8]}')
        print()
finally:
    picam2.stop()
