"""
Main Loupedeck and LoupedeckLive classes.

"""
import time
import threading
import logging
import sys
import glob
import serial

from constants import HEADERS, HAPTIC

logger = logging.getLogger("Button")

BIG_ENDIAN = "big"

WS_UPGRADE_HEADER = b"""GET /index.html
HTTP/1.1
Connection: Upgrade
Upgrade: websocket
Sec-WebSocket-Key: 123abc

"""

WS_UPGRADE_RESPONSE = 'HTTP/1.1'
MAX_TRANSACTIONS = 256

class Loupedeck:

    def __init__(self):
        self.pendingTransactions = [None for _ in range(256)]
        self.transactionID = 0

    @staticmethod
    def list():
        """ Lists serial port names

            :raises EnvironmentError:
                On unsupported or unknown platforms
            :returns:
                A list of the serial ports available on the system
        """
        if sys.platform.startswith('win'):
            ports = ['COM%s' % (i + 1) for i in range(MAX_TRANSACTIONS)]
        elif sys.platform.startswith('linux') or sys.platform.startswith('cygwin'):
            # this excludes your current terminal "/dev/tty"
            ports = glob.glob('/dev/tty[A-Za-z]*')
        elif sys.platform.startswith('darwin'):
            ports = glob.glob('/dev/tty.*')
        else:
            raise EnvironmentError('Unsupported platform')

        result = []
        for port in ports:
            try:
                s = serial.Serial(port)
                s.close()
                result.append(port)
            except (OSError, serial.SerialException):
                pass
        return result


class LoupedeckLive(Loupedeck):


    def __init__(self, path:str, baudrate:int, timeout:int):
        Loupedeck.__init__(self)

        self.connection = serial.Serial(port=path, baudrate=baudrate, timeout=timeout)
        self.callback = None
        self.inited = False

        self.handlers = {
            HEADERS["BUTTON_PRESS"]: self.print_callback,
            HEADERS["KNOB_ROTATE"]: self.print_callback,
            HEADERS["SERIAL_IN"]: self.on_serial,
            HEADERS["TICK"]: self.print_callback,
            HEADERS["TOUCH"]: self.print_callback,
            HEADERS["TOUCH_END"]: self.print_callback,
            HEADERS["VERSION_IN"]: self.print_callback
        }

        self.start()

    def init(self):
        self._write(WS_UPGRADE_HEADER, raw=True)
        self.init_ack()

    def init_ack(self):
        while True and not self.inited:
            raw_byte = self.connection.readline()
            print(raw_byte)
            if raw_byte == b'\r\n':  # got WS_UPGRADE_RESPONSE
                self.inited = True
            time.sleep(0.1)
        logger.debug(f"init_ack: inited")

        # #################@
        # Callbacks
        #
    def on_serial(self, serial):
        logger.debug(f"on_serial: {serial.strip()}")

    def print_callback(self, transactionID: int, response):
        logger.debug(f"{transactionID}: {response}")
        self.pendingTransactions[transactionID] = None

    def set_callback(self, callback):
        self.callback = callback

    def set_button_color(self, index: int, color):
        pass

    def set_key_image(self, index: int, image):
        pass

    def parse(self, buff):
        return {
            "idx": 4,
            "state": 0, # {0|1}
            "rotate": 0, # {0|1}
            "x": 132,
            "y": 223,
            "move": 0 # {0|1}
        }

    def getInfo(self):
        if self.connection is not None:
            self.send(HEADERS["SERIAL_OUT"], data=None, track=True)


    def send(self, action, data:bytearray = None, track:bool = False):
        if self.connection is None:
            return

        logger.debug(f"send: {action:04x}, {data}")
        self.transactionID = (self.transactionID + 1) % MAX_TRANSACTIONS
        # Skip transaction ID's of zero since the device seems to ignore them
        if self.transactionID == 0:
             self.transactionID = self.transactionID = 1
        header = action.to_bytes(2, BIG_ENDIAN) + self.transactionID.to_bytes(1, BIG_ENDIAN)
        logger.debug(f"send: header={header}, track={track}")
        packet = header
        if data is not None:
            logger.debug(f"send: data is not None")
            packet = packet #  + data

        if track:
            logger.debug(f"send: tracking {self.transactionID}")
            self.pendingTransactions[self.transactionID] = self.print_callback
        self._write(packet)


    def _write(self, buff, raw = False):
        """
        Send buffer to device

        :param      buffer:  The buffer
        :type       buffer:  { type_description }
        """
        logger.debug(f"_write: to send: {buff}, raw={raw}")
        if not raw:
            prep = None
            if len(buff) > 256:
                prep = bytearray(14)
                prep[0] = 0x82
                prep[1] = 0xff
                buff_len = len(buff)
                prep.insert(2, buff_len.to_bytes(4, BIG_ENDIAN, False))
            else:
                prep = bytearray(6)
                prep[0] = 0x82
                prep[1] = 0x80 + len(buff)
                # prep.insert(2, buff_length.to_bytes(4, 'big', False))
            logger.debug(f"_write: prep: {prep}, len={len(buff)}")
            self.connection.write(prep)

        logger.debug(f"_write: buff: {buff}")
        self.connection.write(buff)


    def MagicByteLengthParser(self, magicByte):
        data = bytearray(b'')
        for chunck in self.loop():
            data = data + chunk
            position = data.find(magicByte)
            while position != -1:
                logger.debug(f"magic: found {magicByte:x} at {position}")
                #  We need to at least be able to read the length byte
                if len(data) < position + 2:
                    break
                nextLength = data[position + 1]
                print(nextLength)
                #  Make sure we have enough bytes to meet self length
                expectedEnd = position + nextLength + 2
                if len(data) < expectedEnd:
                    break
                logger.debug(f"magic: data {position + 2} at {expectedEnd} (len={nextLength})")
                yield data[position+2:expectedEnd]
                data = data[expectedEnd:]
                position = data.find(magicByte)

    def receive(self, buff):
        for buff in MagicByteLengthParser(magicByte=0x82):
            logger.debug(f"received: {buff}")
            header = int.from_bytes(buff[0:2], BIG_ENDIAN)
            handler = self.handlers[header] if header in self.handlers else None
            transactionID = buff[2]
            logger.debug(f"received: transactionID {transactionID}")
            response = handler(buff[3:]) if handler is not None else buff
            resolver = self.pendingTransactions[transactionID] if transactionID in self.pendingTransactions else None
            resolver(transactionID, response) if resolver is not None else response

    # #########################################@
    # Loupedeck Functions
    #
    def vibrate(self, pattern = HAPTIC["SHORT"]):
        self.send(HEADERS["SET_VIBRATION"], pattern.to_bytes(2, BIG_ENDIAN))

    # #########################################@
    # Threading
    #
    def start(self):
        self.thread = threading.Thread(target=self.loop)
        self.running = True
        self.thread.start()


    def stop(self):
        self.running = False


    def loop(self):
        while True and self.inited:
            raw_byte = self.connection.readline()
            if raw_byte != b'':
                logger.debug(f"raw_byte: {raw_byte}")
                yield raw_byte
