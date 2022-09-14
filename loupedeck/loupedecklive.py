"""
Main Loupedeck and LoupedeckLive classes.

"""
import glob
import io
import logging
import math
import serial
import sys
import threading
import time
from queue import Queue

from PIL import Image, ImageColor

from constants import BIG_ENDIAN, WS_UPGRADE_HEADER, WS_UPGRADE_RESPONSE
from constants import HEADERS, BUTTONS, HAPTIC, MAX_BRIGHTNESS, DISPLAYS

logger = logging.getLogger("Button")


MAX_TRANSACTIONS = 256

class Loupedeck:

    def __init__(self):
        self.connection = None
        self.inited = False
        self.running = False

        self._buffer = bytearray(b"")
        self._messages = Queue()

        self.pendingTransactions = [None for _ in range(256)]
        self.transaction_id = 0

        self.callback = None

    @staticmethod
    def list():
        """ Lists serial port names

            :raises EnvironmentError:
                On unsupported or unknown platforms
            :returns:
                A list of the serial ports available on the system
        """
        if sys.platform.startswith("win"):
            ports = ["COM%s" % (i + 1) for i in range(MAX_TRANSACTIONS)]
        elif sys.platform.startswith("linux") or sys.platform.startswith("cygwin"):
            # this excludes your current terminal "/dev/tty"
            ports = glob.glob("/dev/tty[A-Za-z]*")
        elif sys.platform.startswith("darwin"):
            ports = glob.glob("/dev/tty.*")
        else:
            raise EnvironmentError("Unsupported platform")

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
        self.thread1 = None  # read
        self.thread2 = None  # messages

        self.handlers = {
            HEADERS["BUTTON_PRESS"]: self.on_button,
            HEADERS["KNOB_ROTATE"]: self.on_rotate,
            HEADERS["SERIAL_IN"]: self.on_serial,
            HEADERS["TICK"]: self.on_tick,
            HEADERS["TOUCH"]: self.on_touch,
            HEADERS["TOUCH_END"]: self.on_touch_end,
            HEADERS["VERSION_IN"]: self.on_version
        }

        self.init()

    def init(self):
        self.init_ws()
        self.info()
        self.vibrate("ASCEND_MED")
        self.test_image()
        # self.start()

    def init_ws(self):
        self.send(WS_UPGRADE_HEADER, raw=True)
        while True and not self.inited:
            raw_byte = self.connection.readline()
            print(raw_byte)
            if raw_byte == b"\r\n":  # got WS_UPGRADE_RESPONSE
                self.inited = True
            time.sleep(0.1)
        logger.debug(f"init_ack: inited")

    def info(self):
        if self.connection is not None:
            self.do_action(HEADERS["SERIAL_OUT"], data=None, track=True)
            self.do_action(HEADERS["VERSION_OUT"], data=None, track=True)

    # #########################################@
    # Serial Connection
    #
    def send(self, buff, raw = False):
        """
        Send buffer to device

        :param      buffer:  The buffer
        :type       buffer:  { type_description }
        """
        logger.debug(f"send: to send: {buff}, raw={raw}")
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
                # prep.insert(2, buff_length.to_bytes(4, "big", False))
            logger.debug(f"send: prep: {prep}, len={len(buff)}")
            self.connection.write(prep)

        logger.debug(f"send: buff: {buff}")
        self.connection.write(buff)

    # #########################################@
    # Threading
    #
    def start(self):
        self.thread1 = threading.Thread(target=self._read_serial)
        self.thread2 = threading.Thread(target=self._process_messages)
        self.running = True
        self.thread2.start()
        self.thread1.start()

    def stop(self):
        self.running = False


    def _read_serial(self):

        def magic_byte_length_parser(chunk, magicByte = 0x82):
            """
            Build local _buffer and scan it for complete messages.
            Enqueue messages (responses) when reconstituted.

            :param      chunk:      New chunk of data
            :type       chunk:      bytearray
            :param      magicByte:  The magic byte delimiter
            :type       magicByte:  byte
            """
            trace = False
            self._buffer = self._buffer + chunk
            position = self._buffer.find(magicByte)
            while position != -1:
                if trace:
                    logger.debug(f"magic: found {magicByte:x} at {position}")
                #  We need to at least be able to read the length byte
                if len(self._buffer) < position + 2:
                    if trace:
                        logger.debug(f"magic: not enough bytes ({len(self._buffer)}), waiting for more")
                    break
                nextLength = self._buffer[position + 1]
                #  Make sure we have enough bytes to meet self length
                expectedEnd = position + nextLength + 2
                if len(self._buffer) < expectedEnd:
                    if trace:
                        logger.debug(f"magic: not enough bytes for message ({len(self._buffer)}, exp={expectedEnd}), waiting for more")
                    break
                if trace:
                    logger.debug(f"magic: message from {position + 2} to {expectedEnd} (len={nextLength}), enqueueing")
                self._messages.put(self._buffer[position+2:expectedEnd])
                self._buffer = self._buffer[expectedEnd:]
                position = self._buffer.find(magicByte)

        logger.debug("_read_serial: starting")

        while self.running and self.inited:
            raw_byte = b""
            if self.inited:
                raw_byte = self.connection.read()
            else:
                raw_byte = self.connection.readline()
            if raw_byte != b"":
                # logger.debug(f"raw_byte: {raw_byte}")
                magic_byte_length_parser(raw_byte)

        logger.debug("_read_serial: terminated")

    def _process_messages(self):

        logger.debug("_process_messages: starting")

        while self.running:
            while not self._messages.empty():
                buff = self._messages.get()
                logger.debug(f"_process_messages: {buff}")
                try:
                    header = int.from_bytes(buff[0:2], BIG_ENDIAN)
                    handler = self.handlers[header] if header in self.handlers else None
                    transaction_id = buff[2]
                    logger.debug(f"_process_messages: transaction_id {transaction_id}, {header:x}")
                    response = handler(buff[3:]) if handler is not None else buff
                    resolver = self.pendingTransactions[transaction_id] if transaction_id in self.pendingTransactions else None
                    if resolver is not None:
                        resolver(transaction_id, response)
                    else:
                        self.on_default_callback(transaction_id, response)
                except:
                    logger.error(f"_process_messages: exception:", exc_info=1)
                    logger.error(f"_process_messages: continuing")

            time.sleep(1)

        logger.debug("_process_messages: terminated")

    # #########################################@
    # Callbacks
    #
    def do_action(self, action, data:bytearray = None, track:bool = False):
        if self.connection is None:
            return

        logger.debug(f"do_action: {action:04x}, {data}")
        self.transaction_id = (self.transaction_id + 1) % MAX_TRANSACTIONS
        if self.transaction_id == 0:  # Skip transaction ID's of zero since the device seems to ignore them
             self.transaction_id = self.transaction_id + 1
        header = action.to_bytes(2, BIG_ENDIAN) + self.transaction_id.to_bytes(1, BIG_ENDIAN)
        logger.debug(f"do_action: id={self.transaction_id}, header={header}, track={track}")
        payload = header
        if data is not None:
            payload = payload + data.to_bytes(1, BIG_ENDIAN)
            logger.debug(f"do_action: has data '{data}': {payload}")

        if track:
            logger.debug(f"do_action: tracking {self.transaction_id}")
            self.pendingTransactions[self.transaction_id] = self.on_default_callback
        self.send(payload)

    def on_serial(self, serial):
        logger.info(f"Serial number: {serial.strip()}")

    def on_version(self, version):
        logger.info(f"Version: {version[0]}.{version[1]}.{version[2]}")

    def on_button(self, buff):
        idx = BUTTONS[buff[0]]
        event = 'down' if buff[1] == 0x00 else 'up'
        if self.callback:
            self.callback({
                "type": "button",
                "idx": idx,
                "state": event
            })
        logger.debug(f"on_button: {idx}, {event}")

    def on_rotate(self, buff):
        idx = BUTTONS[buff[0]]
        event = "right" if buff[1] == 0x01 else "left"
        if self.callback:
            self.callback({
                "type": "rotate",
                "idx": idx,
                "state": event
            })
        logger.debug(f"on_rotate: {idx}, {event}")

    def on_tick(self, buff):
        logger.debug(f"on_tick: {buff}")

    def on_touch(self, buff):
        logger.debug(f"on_touch: {buff}")

    def on_touch_end(self, buff):
        logger.debug(f"on_touch_end: {buff}")

    def on_default_callback(self, transaction_id: int, response):
        logger.debug(f"{transaction_id}: {response}")
        self.pendingTransactions[transaction_id] = None

    def set_callback(self, callback):
        self.callback = callback

    # #########################################@
    # Loupedeck Functions
    #
    def set_brightness(self, brightness: int):
        byte = max(0, min(MAX_BRIGHTNESS, round(brightness * MAX_BRIGHTNESS, 0)))
        self.do_action(HEADERS["SET_BRIGHTNESS"], byte.to_bytes(1))

    def set_button_color(self, idx: int, color):
        keys = list(filter(lambda k: BUTTONS[k] == idx, BUTTONS))
        if len(keys) != 1:
            logger.info(f"set_button_color: invalid button key {idx}")
        key = keys.keys()[0]
        (r, g, b) = ImageColor.getrgb(color)
        data = bytearray([key, r, g, b])
        self.do_action(HEADERS["SET_COLOR"], data)
        logger.debug(f"set_button_color: sent {idx}, {color}")

    def vibrate(self, pattern = "SHORT"):
        if pattern not in HAPTIC.keys():
            logger.error(f"vibrate: invalid pattern {pattern}")
            return
        self.do_action(HEADERS["SET_VIBRATION"], HAPTIC[pattern])
        logger.debug(f"vibrate: sent {pattern}")

    # Image display functions
    #
    def refresh(self, display:int):
        display_info = DISPLAYS[display]
        return self.do_action(HEADERS["DRAW"], display_info.id, track=True)

    def draw_buffer(self, buff, display:str, width: int = None, height: int = None, x:int = 0, y:int = 0, auto_refresh:bool = True):
        display_info = DISPLAYS[display]
        if width is None:
            width = display_info.width
        if height is None:
            height = display_info.height
        expected = width * height * 2
        if len(buff) != expected:
            logger.error(f"draw_buffer: invalid buffer {len(buff)}, expected={expected}")

        header = x.to_bytes(2, BIG_ENDIAN)
        header = header + y.to_bytes(2, BIG_ENDIAN)
        header = header + width.to_bytes(2, BIG_ENDIAN)
        header = header + height.to_bytes(2, BIG_ENDIAN)
        payload = display_info.id + header + buff
        self.do_action(HEADERS["WRITE_FRAMEBUFF"], payload, track=True)
        if auto_refresh:
            self.refresh(display)

    def draw_image(self, image, display:str, width: int = None, height: int = None, x:int = 0, y:int = 0, auto_refresh:bool = True):
        # 2 bytes per pixel: format = "I;16B"
        compressed_image = io.BytesIO()
        image.save(compressed_image, "I;16B", quality=100)
        buff = compressed_image.getbuffer()
        self.draw_buffer(buff, display=display, width=width, height=height, x=x, y=y, auto_refresh=auto_refresh)

    def draw_screen(self, image, display:str, auto_refresh:bool = True):
        if type(image) == bytearray:
            self.draw_buffer(image, display=display, auto_refresh=auto_refresh)
        else: # type(image) == PIL.Image.Image
            self.draw_image(image, display=display, auto_refresh=auto_refresh)

    def set_key_image(self, idx: int, image):
        # Get offset x/y for key index
        width = 90
        height = 90
        x = idx % 4 * width
        y = math.floor(idx / 4) * height
        if type(image) == bytearray:
            self.draw_buffer(image, display="center", width=width, height=height, x=x, y=y, auto_refresh=True)
        else: # type(image) == PIL.Image.Image
            self.draw_image(image, display="center", width=width, height=height, x=x, y=y, auto_refresh=True)


    def test_image(self):
        image = Image.new("RGBA", (3, 3), "red")
        compressed_image = io.BytesIO()
        image.save(compressed_image, "PNG", quality=100)
        print("test_image", bytearray(compressed_image.getbuffer()))
