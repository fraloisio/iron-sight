#!/usr/bin/env python3
"""Iron Sight — shutdown button daemon. Watches GPIO23, shuts down on press."""
import RPi.GPIO as GPIO
import subprocess
import signal
import sys

SHUTDOWN_PIN = 23

GPIO.setmode(GPIO.BCM)
GPIO.setup(SHUTDOWN_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)

def on_shutdown(channel):
    print('Shutdown button pressed — halting Pi...')
    subprocess.run(['sudo', 'shutdown', 'now'])

GPIO.add_event_detect(SHUTDOWN_PIN, GPIO.FALLING, callback=on_shutdown, bouncetime=2000)

def cleanup(sig, frame):
    GPIO.cleanup()
    sys.exit(0)

signal.signal(signal.SIGTERM, cleanup)
signal.signal(signal.SIGINT, cleanup)

print('Shutdown button daemon running on GPIO23')
signal.pause()
