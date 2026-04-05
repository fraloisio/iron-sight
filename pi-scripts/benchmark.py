"""Benchmarks downscale-before-dilate optimisation."""
import cv2
import numpy as np
import time
from picamera2 import Picamera2

FRAME_W, FRAME_H = 320, 180
DILATION_PX = 9
MIN_BRIGHT = 180
N = 60

kernel    = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (DILATION_PX, DILATION_PX))
kernel_sm = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))

picam2 = Picamera2()
picam2.configure(picam2.create_video_configuration(
    main={"size": (FRAME_W, FRAME_H), "format": "RGB888"}
))
picam2.start()
picam2.set_controls({"AeEnable": False, "ExposureTime": 5000, "AnalogueGain": 2.0})
time.sleep(1)

t_cap = t_gray = t_thr = t_dil_full = t_dil_small = t_con_full = t_con_small = 0

for _ in range(N):
    frame = picam2.capture_array()
    gray = cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY)
    brt = int(gray.max())
    if brt >= MIN_BRIGHT:
        _, thresh = cv2.threshold(gray, int(brt * 0.75), 255, cv2.THRESH_BINARY)
    else:
        thresh = np.zeros_like(gray)

    # Full-res dilate
    t0 = time.perf_counter()
    dilated = cv2.dilate(thresh, kernel)
    t1 = time.perf_counter()
    cv2.findContours(dilated, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    t2 = time.perf_counter()
    t_dil_full  += t1 - t0
    t_con_full  += t2 - t1

    # Downscale then dilate
    t0 = time.perf_counter()
    small   = cv2.resize(thresh, (FRAME_W//2, FRAME_H//2), interpolation=cv2.INTER_NEAREST)
    dilated = cv2.dilate(small, kernel_sm)
    t1 = time.perf_counter()
    cv2.findContours(dilated, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    t2 = time.perf_counter()
    t_dil_small += t1 - t0
    t_con_small += t2 - t1

picam2.stop()

print(f'\n── Dilate comparison ──')
print(f'  full-res  320x180 + 9px kernel:  dilate {t_dil_full/N*1000:.2f}ms  contours {t_con_full/N*1000:.2f}ms  = {(t_dil_full+t_con_full)/N*1000:.2f}ms')
print(f'  downscale 160x90  + 5px kernel:  dilate {t_dil_small/N*1000:.2f}ms  contours {t_con_small/N*1000:.2f}ms  = {(t_dil_small+t_con_small)/N*1000:.2f}ms')
