import time
import logging

from loupedecklive import LoupedeckLive

logging.basicConfig(level=logging.DEBUG)

devices = LoupedeckLive.list()

print(devices)

def callback(msg):
    print(f"received {msg}")

l = LoupedeckLive(path=devices[1], baudrate=256000, timeout=1)
l.set_callback(callback)
l.start()