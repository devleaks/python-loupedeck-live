# Application constants

BAUD_RATE = 460800
BIG_ENDIAN = "big"
READING_TIMEOUT = 1  # seconds

# Serial Websocket negociation (!)
WS_UPGRADE_HEADER = b"""GET /index.html
HTTP/1.1
Connection: Upgrade
Upgrade: websocket
Sec-WebSocket-Key: 123abc

"""

WS_UPGRADE_RESPONSE = [
    b"HTTP/1.1 101 Switching Protocols\r\n",
    b"Upgrade: websocket\r\n",
    b"Connection: Upgrade\r\n",
    b"Sec-WebSocket-Accept: ALtlZo9FMEUEQleXJmq++ukUQ1s=\r\n",
    b"\r\n",
]

# Various constants used by the Loupedeck firmware

# # Debug function
# def print_bytes(buff, begin: int = 18, end: int = 10):
#     if buff is None:
#         return None
#     if len(buff) > 20:
#         return f"{buff[0:begin]} ... {buff[-end:]}"
#     return f"{buff}"
