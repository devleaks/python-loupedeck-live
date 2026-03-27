"""
Main Loupedeck and LoupedeckLive classes.
"""
import glob
import logging
import serial
import serial.tools.list_ports
import sys
from .Devices import LoupedeckLive

logger = logging.getLogger("DeviceManager")
VERBOSE = False

# Loupedeck USB vendor ID; used to pre-filter ports before probing.
LOUPEDECK_VID = 0x2EC2


class DeviceManager:

    @staticmethod
    def list():
        """ Lists serial port names

            :raises EnvironmentError:
                On unsupported or unknown platforms
            :returns:
                A list of the serial ports available on the system
        """
        # Fast path: use pyserial's cross-platform port enumerator which carries
        # USB VID/PID metadata.  Filtering by Loupedeck's vendor ID avoids
        # opening unrelated ports (Bluetooth, MIDI, etc.) and, critically,
        # prevents the is_loupedeck() probe from being run against devices that
        # continuously emit binary data — which would previously cause an
        # infinite hang on macOS composite USB devices.
        try:
            vid_filtered = [
                p.device
                for p in serial.tools.list_ports.comports()
                if p.vid == LOUPEDECK_VID
            ]
            if vid_filtered:
                logger.debug(f"list: VID filter found {len(vid_filtered)} Loupedeck-VID port(s): {vid_filtered}")
                return vid_filtered
            logger.debug("list: VID filter found no Loupedeck-VID ports; falling back to full scan")
        except Exception as exc:
            logger.warning(f"list: VID/PID port scan failed ({exc}); falling back to full scan")

        # Fallback: original glob-based scan for platforms where pyserial's
        # list_ports does not return VID metadata.
        if sys.platform.startswith("win"):
            ports = [f"COM{i}" for i in range(1, 256)]
        elif sys.platform.startswith("linux") or sys.platform.startswith("cygwin"):
            # this excludes your current terminal "/dev/tty"
            ports = glob.glob("/dev/tty[A-Za-z0-9]*")
        elif sys.platform.startswith("darwin"):
            ports = glob.glob("/dev/tty.*")
        else:
            raise EnvironmentError("Unsupported platform")

        logger.debug(f"list: listing ports..")
        result = []
        for port in ports:
            try:
                logger.debug(f"trying {port}..")
                s = serial.Serial(port)
                s.close()
                result.append(port)
                logger.debug(f"..added {port}")
            except (OSError, serial.SerialException):
                logger.debug(f".. not added {port}", exc_info=VERBOSE)
        logger.debug(f"list: ..listed")
        return result

    def __init__(self):
        pass

    def enumerate(self):
        loupedecks = list()

        paths = DeviceManager.list()
        for path in paths:
            l = LoupedeckLive(path=path)
            if l.is_loupedeck():
                logger.debug(f"enumerate: added Loupedeck device at {path}")
                loupedecks.append(l)

        return loupedecks
