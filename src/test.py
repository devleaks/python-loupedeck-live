import time
import logging

from Loupedeck import DeviceManager

logging.basicConfig(level=logging.DEBUG)

devices = DeviceManager().enumerate()

def callback(msg):
    print(f">> {msg}")

if len(devices) > 0:
    l = devices[0]
    print("trying..", l)
    l.set_callback(callback)
    l.test()
    time.sleep(5)
    l.stop()
