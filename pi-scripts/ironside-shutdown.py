#!/usr/bin/env python3
"""Iron Sight — shutdown button daemon. Watches GPIO23 and GPIO3, shuts down on press.
GPIO3 (Pin 5) also has hardware wake-from-halt — pressing it powers the Pi back on."""
import RPi.GPIO as GPIO
import subprocess
import signal
import sys

SHUTDOWN_PIN_23 = 23   # Yellow, Pin 16
SHUTDOWN_PIN_3  = 3    # Yellow, Pin 5  (also hardware wake-from-halt)

GPIO.setmode(GPIO.BCM)
GPIO.setup(SHUTDOWN_PIN_23, GPIO.IN, pull_up_down=GPIO.PUD_UP)
GPIO.setup(SHUTDOWN_PIN_3,  GPIO.IN, pull_up_down=GPIO.PUD_UP)

def on_shutdown(channel):
    print(f'Shutdown button pressed (GPIO{channel}) — halting Pi...')
    subprocess.run(['sudo', 'shutdown', 'now'])

GPIO.add_event_detect(SHUTDOWN_PIN_23, GPIO.FALLING, callback=on_shutdown, bouncetime=2000)
GPIO.add_event_detect(SHUTDOWN_PIN_3,  GPIO.FALLING, callback=on_shutdown, bouncetime=2000)

def cleanup(sig, frame):
    GPIO.cleanup()
    sys.exit(0)

signal.signal(signal.SIGTERM, cleanup)
signal.signal(signal.SIGINT, cleanup)

print('Shutdown button daemon running on GPIO23 (Pin 16) and GPIO3 (Pin 5)')
signal.pause()
