import time
import logging

from loupedecklive import LoupedeckLive

logging.basicConfig(level=logging.DEBUG)

devices = LoupedeckLive.list()

print(devices)

l = LoupedeckLive(path=devices[1], baudrate=256000, timeout=1)

l.init()

time.sleep(2)
l.getInfo()