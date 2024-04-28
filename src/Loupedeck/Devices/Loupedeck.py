"""
Loupedeck base class. Kind of ABC for future loupedeck devices.
"""

import logging
from typing import Callable
import serial

from threading import RLock

from .constants import (
    BAUD_RATE,
    READING_TIMEOUT,
    BIG_ENDIAN,
    WS_UPGRADE_HEADER,
    WS_UPGRADE_RESPONSE,
)

logger = logging.getLogger("Loupedeck")
# logger.setLevel(logging.DEBUG)


DEVICE_MANUFACTURER = "Loupedeck"  # verbose descriptive
UNKNOWN_DEVICE = "unknown"
NUM_ATTEMPTS = 1  # + 1 mandatory


class Loupedeck:
    DECK_TYPE = "Loupedeck"

    def __init__(
        self, path: str, baudrate: int = BAUD_RATE, timeout: int = READING_TIMEOUT
    ):
        self.path: str = path
        # See https://lucidar.me/en/serialib/most-used-baud-rates-table/ for baudrates
        self.connection = serial.Serial(port=path, baudrate=baudrate, timeout=timeout)
        logger.debug(f"__init__: connection opened")

        self.serial: str | None = None
        self.version: str | None = None
        self.inited = False
        self.running = False

        self._buffer = bytearray(b"")
        self._is_loupedeck = False

        self.pendingTransactions = [None for _ in range(256)]
        self.transaction_id = 0

        self.callback: Callable | None = None

        self.update_lock = RLock()

    def __del__(self):
        """
        Delete handler for the automatically closing the serial port.
        """
        try:
            if self.connection is not None:
                if self.connection.is_open:
                    self.connection.close()
                    logger.debug(f"__del__: connection closed")
                del self.connection  # calls self.connection.close()
                self.connection = None
        except:
            logger.error(f"__del__: exception:", exc_info=1)

    def __enter__(self):
        """
        Enter handler for the StreamDeck, taking the exclusive update lock on
        the deck. This can be used in a `with` statement to ensure that only one
        thread is currently updating the deck, even if it is doing multiple
        operations (e.g. setting the image on multiple keys).
        """
        self.update_lock.acquire()

    def __exit__(self, type, value, traceback):
        """
        Exit handler for the StreamDeck, releasing the exclusive update lock on
        the deck.
        """
        self.update_lock.release()

    def deck_type(self):
        if self.inited:
            return Loupedeck.DECK_TYPE if self._is_loupedeck else UNKNOWN_DEVICE

    def is_loupedeck(self) -> bool:
        global NUM_ATTEMPTS

        if self.inited:
            return self._is_loupedeck

        self.send(WS_UPGRADE_HEADER, raw=True)

        cnt = 0
        good = 0
        if NUM_ATTEMPTS < 1:
            NUM_ATTEMPTS = 1
        logger.debug(f"is_loupedeck: {self.path}: trying..")
        while not self.inited and good < len(WS_UPGRADE_RESPONSE):
            raw_byte = self.connection.readline()
            logger.debug(f"is_loupedeck: {raw_byte}")
            if raw_byte in WS_UPGRADE_RESPONSE:  # got entire WS_UPGRADE_RESPONSE
                good = good + 1
            if raw_byte == b"":
                cnt = cnt + 1
            if cnt > NUM_ATTEMPTS:
                logger.debug(
                    f"is_loupedeck: {self.path}: ..got {cnt} wrong answers, probably not a {type(self).__name__} device, ignoring."
                )
                self.inited = True
        if good == len(WS_UPGRADE_RESPONSE):  # not 100% correct, but ok.
            logger.debug(
                f"is_loupedeck: {self.path}: ..got a {type(self).__name__} device"
            )
            self.inited = True
            self._is_loupedeck = True

        return self._is_loupedeck

    def get_info(self):
        if self.inited:
            return {"version": self.version, "serial": self.serial, "path": self.path}
        return None

    def get_serial_number(self):
        return self.serial if self.inited else None

    # #########################################@
    # Serial Connection
    #
    def send(self, buff, raw=False):
        """
        Send buffer to device

        :param      buffer:  The buffer
        :type       buffer:  { type_description }
        """
        # logger.debug(f"send: to send: len={len(buff)}, raw={raw}, {print_bytes(buff)}")
        if not raw:
            prep = None
            if len(buff) > 0x80:
                prep = bytearray(14)
                prep[0] = 0x82
                prep[1] = 0xFF
                buff_len = len(buff)
                prep[6:10] = buff_len.to_bytes(4, BIG_ENDIAN)
            else:
                prep = bytearray(6)
                prep[0] = 0x82
                prep[1] = 0x80 + len(buff)
                # prep.insert(2, buff_length.to_bytes(4, "big", False))
            # logger.debug(f"send: PREP: len={len(buff)}: {prep}")
            with self:
                self.connection.write(prep)
                self.connection.write(buff)
        else:
            with self:
                # logger.debug(f"send: buff: len={len(buff)}, {print_bytes(buff)}") # {buff},
                self.connection.write(buff)
