"""
Main Loupedeck and LoupedeckLive classes.
"""
import logging
import math
import threading
import time
from typing import Dict, ByteString, Callable, Any, Tuple
from enum import Enum

from queue import Queue
from datetime import datetime
from PIL import Image, ImageColor
from serial import XOFF

from .constants import BAUD_RATE, READING_TIMEOUT, BIG_ENDIAN
from .Loupedeck import Loupedeck
from ..ImageHelpers import PILHelper


logger = logging.getLogger("LoupedeckLive")
# logger.setLevel(logging.DEBUG)

DEVICE_MANUFACTURER = "Loupedeck"  # verbose descriptive
DEVICE_MODEL = "Loupedeck Live"  # verbose descriptive
DEVICE_MODEL_NAME = "loupedecklive"  # technical alias, as returned in definitions

# Actions and response identifications
HEADERS: Dict[str, int] = {
    "CONFIRM": 0x0302,
    "SERIAL_OUT": 0x0303,
    "VERSION_OUT": 0x0307,
    "TICK": 0x0400,
    "SET_BRIGHTNESS": 0x0409,
    "CONFIRM_FRAMEBUFF": 0x0410,
    "SET_VIBRATION": 0x041B,
    "BUTTON_PRESS": 0x0500,
    "KNOB_ROTATE": 0x0501,
    "RESET": 0x0506,
    "DRAW": 0x050F,
    "SET_COLOR": 0x0702,
    "TOUCH": 0x094D,
    "TOUCH_END": 0x096D,
    "VERSION_IN": 0x0C07,
    "MCU": 0x180D,
    "SERIAL_IN": 0x1F03,
    "WRITE_FRAMEBUFF": 0xFF10,
}

# Button names
BUTTONS: Dict[int, str] = {
    0x01: "knobTL",
    0x02: "knobCL",
    0x03: "knobBL",
    0x04: "knobTR",
    0x05: "knobCR",
    0x06: "knobBR",
    0x07: "circle",
    0x08: "1",
    0x09: "2",
    0x0A: "3",
    0x0B: "4",
    0x0C: "5",
    0x0D: "6",
    0x0E: "7",
}

# Displays
KW_ID = "id"
KW_LEFT = "left"
KW_RIGHT = "right"
KW_CENTER = "center"
KW_WIDTH = "width"
KW_HEIGHT = "height"
KW_CIRCLE = "circle"
KW_OFFSET = "offset"

DISPLAYS: Dict[str, Dict[str, int | bytes]] = {
    KW_LEFT: {KW_ID: bytes("\x00M".encode("ascii")), KW_WIDTH: 60, KW_HEIGHT: 270, KW_OFFSET: 0},  # "L"
    KW_CENTER: {KW_ID: bytes("\x00M".encode("ascii")), KW_WIDTH: 360, KW_HEIGHT: 270, KW_OFFSET: 60},  # "A"
    KW_RIGHT: {KW_ID: bytes("\x00M".encode("ascii")), KW_WIDTH: 60, KW_HEIGHT: 270, KW_OFFSET: 420},  # "R"
}

DISPLAY_NAMES = set(DISPLAYS.keys())

BUTTON_SIZES = {KW_CENTER: [90, 90], KW_LEFT: [60, 270], KW_RIGHT: [60, 270]}


class CALLBACK_KEYWORD(Enum):
    ACTION = "action"
    KEY = "key"
    IDENTIFIER = "id"
    PUSH = "push"
    ROTATE = "rotate"
    SCREEN = "screen"
    STATE = "state"
    SWIPE = "swipe"
    TIMESTAMP = "ts"
    TOUCH_END = "touchend"
    TOUCH_MOVE = "touchmove"
    TOUCH_START = "touchstart"
    X = "x"
    Y = "y"


# Haptic feedbacks
HAPTIC = {
    "SHORT": 0x01,
    "MEDIUM": 0x0A,
    "LONG": 0x0F,
    "LOW": 0x31,
    "SHORT_LOW": 0x32,
    "SHORT_LOWER": 0x33,
    "LOWER": 0x40,
    "LOWEST": 0x41,
    "DESCEND_SLOW": 0x46,
    "DESCEND_MED": 0x47,
    "DESCEND_FAST": 0x48,
    "ASCEND_SLOW": 0x52,
    "ASCEND_MED": 0x53,
    "ASCEND_FAST": 0x58,
    "REV_SLOWEST": 0x5E,
    "REV_SLOW": 0x5F,
    "REV_MED": 0x60,
    "REV_FAST": 0x61,
    "REV_FASTER": 0x62,
    "REV_FASTEST": 0x63,
    "RISE_FALL": 0x6A,
    "BUZZ": 0x70,
    "RUMBLE5": 0x77,  # lower frequencies in descending order
    "RUMBLE4": 0x78,
    "RUMBLE3": 0x79,
    "RUMBLE2": 0x7A,
    "RUMBLE1": 0x7B,
    "VERY_LONG": 0x76,  # 10 sec high freq (!)
}

# Maximum brightness value
MAX_BRIGHTNESS = 10

MAX_TRANSACTIONS = 256


class LoupedeckLive(Loupedeck):
    def __init__(self, path: str, baudrate: int = BAUD_RATE, timeout: int = READING_TIMEOUT, auto_start: bool = True):
        Loupedeck.__init__(self, path=path, baudrate=baudrate, timeout=timeout)

        self.auto_start = auto_start
        self.reading_thread = None  # read
        self.process_thread = None  # messages
        self.reading_running = False
        self.process_running = False
        self.reading_finished = None
        self.process_finished = None
        self.get_serial = None
        self.touches: Dict[int, Dict] = {}

        self.handlers = {
            HEADERS["BUTTON_PRESS"]: self.on_button,
            HEADERS["KNOB_ROTATE"]: self.on_rotate,
            HEADERS["SERIAL_IN"]: self.on_serial,
            HEADERS["TICK"]: self.on_tick,
            HEADERS["TOUCH"]: self.on_touch,
            HEADERS["TOUCH_END"]: self.on_touch_end,
            HEADERS["VERSION_IN"]: self.on_version,
        }

        self._messages: Queue = Queue()
        self.get_timeout = 1  # Queue get() timeout, in seconds

        if not self.is_loupedeck():
            return None

        self.init()

    def deck_type(self):
        if self.inited:
            return DEVICE_MODEL_NAME if self._is_loupedeck else "unknown"

    def open(self):
        pass

    def close(self):
        pass

    def is_visual(self):
        return True

    def key_image_format(self):
        return {"size": (90, 90), "format": "RGB565", "flip": None, "rotation": None}

    def init(self):
        self.start()
        self.info()  # this is more to test it is working...
        logger.debug(f"init: inited")

    def info(self):
        if self.connection is not None:
            logger.debug(f"Device: {self.path}")
            self.get_serial = threading.Event()
            self.do_action(HEADERS["SERIAL_OUT"], track=True)
            self.do_action(HEADERS["VERSION_OUT"], track=True)
            if not self.get_serial.wait(10):
                logger.warning(f"info: could not get serial number")

            time.sleep(self.get_timeout)  # give time to get answers

    def id(self):
        return self.serial

    def key_layout(self):
        return (4, 3)

    def key_count(self):
        return 4 * 3

    def key_names(self, big: bool = False):
        if big:
            return [KW_LEFT, KW_CENTER, KW_RIGHT]
        return [KW_LEFT, KW_RIGHT] + list(range(self.key_count()))

    # #########################################@
    # Threading
    #
    def _read_serial(self):
        def magic_byte_length_parser(chunk, magicByte=0x82):
            """
            Build local _buffer and scan it for complete messages.
            Enqueue complete messages (responses) when reconstituted.

            :param    chunk:      New chunk of data
            :type      chunk:     bytearray
            :param    magicByte:  The magic byte delimiter
            :type      magicByte:  byte
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
                    logger.debug(f"magic: message from {position + 2} to {expectedEnd} (len={nextLength}), enqueueing ({self._messages.qsize()})")
                self._messages.put(self._buffer[position + 2 : expectedEnd])
                self._buffer = self._buffer[expectedEnd:]
                position = self._buffer.find(magicByte)

        logger.debug("_read_serial: starting")

        while self.reading_running:
            try:
                raw_byte = self.connection.read()
                if raw_byte != b"":
                    magic_byte_length_parser(raw_byte)
            except:
                logger.error(f"_read_serial: exception:", exc_info=1)
                logger.error(f"_read_serial: resuming")

        self.reading_running = False

        logger.debug("_read_serial: terminated")

    def _process_messages(self):
        """
        Dequeue messages, decode them, and call back closing open transactions if any.
        """
        logger.debug("_process_messages: starting")

        while self.process_running:
            try:
                # logger.debug(f"_process_messages: dequeueing {self._messages.qsize()}")
                buff = self._messages.get(timeout=self.get_timeout)
                try:
                    # logger.debug(f"_process_messages: got {buff}")
                    header = int.from_bytes(buff[0:2], BIG_ENDIAN)
                    handler = self.handlers[header] if header in self.handlers else None
                    transaction_id = buff[2]
                    # logger.debug(f"_process_messages: transaction_id {transaction_id}, header {header:x}")
                    response = handler(buff[3:]) if handler is not None else buff
                    resolver = self.pendingTransactions[transaction_id] if transaction_id in self.pendingTransactions else None
                    if resolver is not None:
                        resolver(transaction_id, response)
                    else:
                        self.on_default_callback(transaction_id, response)
                except:
                    logger.error(f"_process_messages: exception:", exc_info=1)
                    logger.error(f"_process_messages: resuming")
            except:  # timeout, continue while self.process_running==True
                pass
                # logger.debug(f"_process_messages: timed out, continuing")

        logger.debug("_process_messages: terminated")

    def start(self):
        """
        Start both processes if not started.
        """
        if self.inited:
            if not self.reading_running:
                self.reading_thread = threading.Thread(target=self._read_serial)
                self.reading_thread.name = "LoupedeckLive::_read_serial"
                self.reading_running = True
                self.reading_thread.start()
                logger.debug("start: read started")
            else:
                logger.warning("start: read already running")
            if not self.process_running:
                self.process_thread = threading.Thread(target=self._process_messages)
                self.process_thread.name = "LoupedeckLive::_process_messages"
                self.process_running = True
                self.process_thread.start()
                logger.debug("start: process started")
            else:
                logger.warning("start: process already running")
            logger.debug("start: started")
        else:
            logger.warning("start: cannot start, not initialized")

    def stop(self):
        """
        Stop both processes
        """
        done = False
        if self.reading_running:
            self.reading_running = False
            self.reading_thread.join(timeout=2 * READING_TIMEOUT)
            done = True
            if self.reading_thread.is_alive():
                # self.reading_running = True  # ??
                logger.warning("stop: reader thread did not finish cleanly")

        if self.process_running:
            self.process_running = False
            self.process_thread.join(timeout=2 * self.get_timeout)
            done = True
            if self.process_thread.is_alive():
                # self.process_running = True  # ??
                logger.warning("stop: process thread did not finish cleanly")
        if done:
            logger.debug("stop: stopped")
        else:
            logger.warning("stop: already stopped")

    # #########################################@
    # Callbacks
    #
    def do_action(self, action, data: Any | None = None, track: bool = False):
        if not self.inited:
            logger.warning(f"do_action: not started")
            return

        if data is not None and type(data) != bytearray and type(data) != bytes:
            data = data.to_bytes(1, BIG_ENDIAN)
            # logger.debug(f"do_action: converted data") #  '{data}'")

        # logger.debug(f"do_action: {action:04x}, {print_bytes(data)}")
        self.transaction_id = (self.transaction_id + 1) % MAX_TRANSACTIONS
        if self.transaction_id == 0:  # Skip transaction ID's of zero since the device seems to ignore them
            self.transaction_id = self.transaction_id + 1
        header = action.to_bytes(2, BIG_ENDIAN) + self.transaction_id.to_bytes(1, BIG_ENDIAN)
        # logger.debug(f"do_action: id={self.transaction_id}, header={header}, track={track}")
        payload = header
        if data is not None:
            # logger.debug(f"do_action: has data {payload} + '{print_bytes(data)}'")
            payload = payload + data

        if track:
            # logger.debug(f"do_action: tracking {self.transaction_id}")
            self.pendingTransactions[self.transaction_id] = action
        self.send(payload)

    def on_serial(self, serial: bytearray):
        self.serial = serial.decode("ascii").strip()
        if self.get_serial is not None:
            self.get_serial.set()
        # logger.info(f"Serial number: {self.serial}")

    def on_version(self, version: bytearray):
        self.version = f"{version[0]}.{version[1]}.{version[2]}"
        # logger.info(f"Version: {self.version}")

    def on_button(self, buff: bytearray):
        idx = BUTTONS[buff[0]]
        event = "down" if buff[1] == 0x00 else "up"
        if self.callback:
            self.callback(
                self,
                {
                    CALLBACK_KEYWORD.IDENTIFIER.value: idx,
                    CALLBACK_KEYWORD.ACTION.value: CALLBACK_KEYWORD.PUSH.value,
                    CALLBACK_KEYWORD.STATE.value: event,
                    CALLBACK_KEYWORD.TIMESTAMP.value: datetime.now().timestamp(),
                },
            )
        # logger.debug(f"on_button: {idx}, {event}")

    def on_rotate(self, buff: bytearray):
        idx = BUTTONS[buff[0]]
        event = KW_RIGHT if buff[1] == 0x01 else KW_LEFT
        if self.callback:
            self.callback(
                self,
                {
                    CALLBACK_KEYWORD.IDENTIFIER.value: idx,
                    CALLBACK_KEYWORD.ACTION.value: CALLBACK_KEYWORD.ROTATE.value,
                    CALLBACK_KEYWORD.STATE.value: event,
                    CALLBACK_KEYWORD.TIMESTAMP.value: datetime.now().timestamp(),
                },
            )
        # logger.debug(f"on_rotate: {idx}, {event}")

    def on_touch(self, buff: bytearray, event=CALLBACK_KEYWORD.TOUCH_MOVE.value):
        x = int.from_bytes(buff[1:3], BIG_ENDIAN)
        y = int.from_bytes(buff[3:5], BIG_ENDIAN)
        idx = buff[5]

        # Determine target
        screen = KW_CENTER
        if x < 60:
            screen = KW_LEFT
        elif x > 420:
            screen = KW_RIGHT

        key = None
        if screen == KW_CENTER:
            column = math.floor((x - 60) / 90)
            row = math.floor(y / 90)
            key = row * 4 + column

        # Create touch
        touch = {
            CALLBACK_KEYWORD.IDENTIFIER.value: idx,
            CALLBACK_KEYWORD.ACTION.value: event,
            CALLBACK_KEYWORD.SCREEN.value: screen,
            CALLBACK_KEYWORD.KEY.value: key,
            CALLBACK_KEYWORD.X.value: x,
            CALLBACK_KEYWORD.Y.value: y,
            CALLBACK_KEYWORD.TIMESTAMP.value: datetime.now().timestamp(),
        }
        if event == "touchmove":
            if idx not in self.touches:
                touch["action"] = "touchstart"
                self.touches[idx] = touch
        else:
            del self.touches[idx]

        if self.callback:
            self.callback(self, touch)

        # logger.debug(f"on_touch: {event}, {buff}")

    def on_touch_end(self, buff: bytearray):
        self.on_touch(buff, event="touchend")

    def on_tick(self, buff: bytearray):
        logger.debug(f"on_tick: {buff}")

    def on_default_callback(self, transaction_id: int, response: bytearray):
        # logger.debug(f"on_default_callback: {transaction_id}: {response}")
        self.pendingTransactions[transaction_id] = None

    def set_callback(self, callback: Callable):
        """
        This is the user's callback called when action
        occurred on the Loupedeck device

        :param    callback:  The callback
        :type      callback:  Function
        """
        # callback signature: callback(self:Loupedeck, message:dict)
        self.callback = callback

    # #########################################@
    # Loupedeck Functions
    #
    def set_brightness(self, brightness: int):
        """
        Set brightness, from 0 (dark) to 100.
        """
        brightness = math.floor(brightness / 10)
        if brightness < 1:
            logger.warning(f"set_brightness: brightness set to 0")
            brightness = 0
        if brightness > MAX_BRIGHTNESS:
            brightness = MAX_BRIGHTNESS
        self.do_action(HEADERS["SET_BRIGHTNESS"], brightness.to_bytes(1, BIG_ENDIAN))
        # logger.debug(f"set_brightness: sent {brightness}")

    def set_button_color(self, name: str, color: Tuple[int, int, int] | str):
        keys = list(filter(lambda k: BUTTONS[k] == name, BUTTONS))
        if len(keys) != 1:
            logger.warning(f"set_button_color: invalid button key {name}")
            return
        key = keys[0]

        if type(color) is str:
            temp = ImageColor.getrgb(color)
            if len(temp) == 3:
                (r, g, b) = temp
            else:
                (r, g, b, a) = temp
        else:
            (r, g, b) = color  # type: ignore
        data = bytearray([key, r, g, b])
        self.do_action(HEADERS["SET_COLOR"], data)
        # logger.debug(f"set_button_color: sent {name}, {color}")

    def vibrate(self, pattern="SHORT"):
        if pattern not in HAPTIC.keys():
            logger.error(f"vibrate: invalid pattern {pattern}")
            return
        self.do_action(HEADERS["SET_VIBRATION"], HAPTIC[pattern])
        # logger.debug(f"vibrate: sent {pattern}")

    # Image display functions
    #
    def refresh(self, display: str):
        display_info = DISPLAYS[display]
        self.do_action(HEADERS["DRAW"], display_info[KW_ID], track=True)
        # logger.debug("refresh: refreshed")

    def draw_buffer(self, buff, display: str, width: int | None = None, height: int | None = None, x: int = 0, y: int = 0, auto_refresh: bool = True):
        t = DISPLAYS[display][KW_OFFSET] if display in DISPLAYS else DISPLAYS[KW_CENTER][KW_OFFSET]
        xoffset: int = int.from_bytes(t) if type(t) is bytes else int(t)
        x = x + xoffset
        display_info = DISPLAYS[display]
        loc_width: int = int(display_info[KW_WIDTH]) if width is None else width
        loc_height: int = int(display_info[KW_HEIGHT]) if height is None else height
        expected: int = loc_width * loc_height * 2
        if len(buff) != expected:
            logger.error(f"draw_buffer: invalid buffer {len(buff)}, expected={expected}")
            return  # don't do anything because it breaks the connection to send invalid length buffer

        # logger.debug(f"draw_buffer: o={x},{y}, dim={width},{height}")

        header = x.to_bytes(2, BIG_ENDIAN)
        header = header + y.to_bytes(2, BIG_ENDIAN)
        header = header + loc_width.to_bytes(2, BIG_ENDIAN)
        header = header + loc_height.to_bytes(2, BIG_ENDIAN)
        payload = display_info[KW_ID] + header + buff  # type: ignore
        self.do_action(HEADERS["WRITE_FRAMEBUFF"], payload, track=True)
        # logger.debug(f"draw_buffer: buffer sent {len(buff)} bytes")
        if auto_refresh:
            self.refresh(display)

    def draw_image(self, image, display: str, width: int | None = None, height: int | None = None, x: int = 0, y: int = 0, auto_refresh: bool = True):
        buff = PILHelper.to_native_format(display, image)
        self.draw_buffer(buff, display=display, width=width, height=height, x=x, y=y, auto_refresh=auto_refresh)

    def draw_left_image(self, image, width: int | None = None, height: int | None = None, x: int = 0, y: int = 0, auto_refresh: bool = True):
        self.draw_image(image=image, display="left", width=width, height=height, x=x, y=y, auto_refresh=auto_refresh)

    def draw_right_image(self, image, width: int | None = None, height: int | None = None, x: int = 0, y: int = 0, auto_refresh: bool = True):
        self.draw_image(image=image, display="right", width=width, height=height, x=x, y=y, auto_refresh=auto_refresh)

    def draw_center_image(self, image, width: int | None = None, height: int | None = None, x: int = 0, y: int = 0, auto_refresh: bool = True):
        self.draw_image(image=image, display="center", width=width, height=height, x=x, y=y, auto_refresh=auto_refresh)

    def draw_screen(self, image, display: str, auto_refresh: bool = True):
        if type(image) == bytearray:
            self.draw_buffer(image, display=display, auto_refresh=auto_refresh)
        else:  # type(image) == PIL.Image.Image
            self.draw_image(image, display=display, auto_refresh=auto_refresh)

    def set_key_image(self, idx: str, image):
        x = 0
        y = 0
        if idx == KW_LEFT:
            display = idx
        elif idx == KW_RIGHT:
            display = idx
        else:
            display = KW_CENTER
            # note: if idx==KW_CENTER, should display the whole image in center portion
            # may be later...
            # else, idx must be a number 0..11
            idx_in = idx
            try:
                loc_idx = int(idx)
                width = BUTTON_SIZES[display][0]
                height = BUTTON_SIZES[display][1]
                x = (loc_idx % 4) * width
                y = math.floor(loc_idx / 4) * height
            except ValueError:
                logger.warning(f"set_key_image: key «{idx_in}»: invalid index for center display, aborting set_key_image")
                return

        width = BUTTON_SIZES[display][0]
        height = BUTTON_SIZES[display][1]
        # logger.info(f"set_key_image: key {idx}: {x}, {y}, {width}, {height}")

        if type(image) == bytearray:
            self.draw_buffer(image, display=display, width=width, height=height, x=x, y=y, auto_refresh=True)
        else:  # type(image) == PIL.Image.Image
            self.draw_image(image, display=display, width=width, height=height, x=x, y=y, auto_refresh=True)

    def set_left_image(self, image):
        self.set_key_image(KW_LEFT, image)

    def set_right_image(self, image):
        self.set_key_image(KW_RIGHT, image)

    def set_center_image(self, image):
        self.set_key_image(KW_CENTER, image)

    def reset(self):
        colors = ["black" for i in range(3)]  # ["cyan", "magenta", "blue"]
        i = 0
        for display, sizes in DISPLAYS.items():
            image = Image.new("RGBA", (sizes[KW_WIDTH], sizes[KW_HEIGHT]), colors[i])
            self.draw_image(image, display=display, auto_refresh=True)
            i = i + 1

    # #########################################@
    # Development and testing
    #
    def test(self):
        WAIT_TIME = 3
        SHORT_WAIT = 0.4
        # for i in HAPTIC.keys():
        #     self.vibrate(i)
        #     print(i)
        #     time.sleep(WAIT_TIME)

        for bright in range(0, 100, 10):
            time.sleep(SHORT_WAIT)
            self.set_brightness(bright)

        for i in range(1, 7):
            self.set_button_color(f"{i}", (00, 00, 101))
            self.set_button_color(f"{i + 1}", (190, 00, 00))
            time.sleep(SHORT_WAIT)

        self.set_button_color("1", "red")
        self.set_button_color("2", "orange")
        self.set_button_color("3", "yellow")
        self.set_button_color("4", "green")
        self.set_button_color("5", "blue")
        self.set_button_color("6", "purple")
        self.set_button_color("7", "white")
        self.test_image()

    def test_image(self):
        # image = Image.new("RGBA", (360, 270), "cyan")
        with open("Assets/yumi.jpg", "rb") as infile:
            image = Image.open(infile).convert("RGBA")
            self.draw_image(image, display=KW_CENTER)
        with open("Assets/left.jpg", "rb") as infile:
            image = Image.open(infile).convert("RGBA")
            self.draw_image(image, display=KW_LEFT)
        with open("Assets/right.jpg", "rb") as infile:
            image = Image.open(infile).convert("RGBA")
            self.draw_image(image, display=KW_RIGHT)
        # image2 = Image.new("RGBA", (90, 90), "blue")
        # self.set_key_image(6, image2)


if __name__ == "__main__":
    from ..DeviceManager import DeviceManager

    logging.basicConfig(level=logging.INFO)
    devices = DeviceManager.list()

    def callback(msg):
        print(f"received {msg}")

    l = LoupedeckLive(path=devices[1], baudrate=256000, timeout=1)
    l.set_callback(callback)

    l.start()
    # test
    # time.sleep(10)
    # l.stop()
