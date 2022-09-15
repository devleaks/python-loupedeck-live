import time
import logging

from Loupedeck import DeviceManager

logging.basicConfig(level=logging.INFO)

devices = DeviceManager().enumerate()

def callback(msg):
    print(f">> {msg}")

if len(devices) > 0:
    l = devices[0]
    l.set_callback(callback)

    l.start()

    # test
    # time.sleep(10)
    # l.stop()