"""RFCOMM session with the obfuscated-write handshake."""
import fcntl
import random
import socket
import struct
import termios
import time

from . import protocol

RFCOMM_CHANNEL = 1


class Session:
    def __init__(self, mac: str, timeout: float = 15.0, attempts: int = 3):
        self.events: list[int] = []   # status bytes the printer volunteered ("pooli_sta=")
        # The printer needs a moment to release the previous link, so a quick
        # reconnect can be refused or reset; retry the whole connect + handshake.
        for attempt in range(attempts):
            self._sock = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM, socket.BTPROTO_RFCOMM)
            self._sock.settimeout(timeout)
            self._key = None
            try:
                self._sock.connect((mac, RFCOMM_CHANNEL))
                self._handshake()
                return
            except OSError:
                self._sock.close()
                if attempt == attempts - 1:
                    raise
                time.sleep(1.5)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def close(self):
        self._sock.close()

    def _handshake(self):
        r1, r2 = random.randint(1, 100), random.randint(1, 100)
        self._sock.send(protocol.handshake_request(r1, r2))
        reply = self._read(3.0)
        if reply != b"OK":
            raise ConnectionError(f"unsupported handshake reply {reply!r}")
        self._key = protocol.session_key(r1, r2)

    def _read(self, first_timeout: float, quiet: float = 0.4) -> bytes:
        out = b""
        self._sock.settimeout(first_timeout)
        try:
            while True:
                data = self._sock.recv(512)
                if not data:
                    break
                out += data
                self._sock.settimeout(quiet)
        except socket.timeout:
            pass
        return out

    def send(self, data: bytes):
        self._sock.sendall(protocol.xor(data, self._key))

    def query(self, command: bytes, timeout: float = 1.5) -> bytes:
        """Send a query and return the reply with volunteered status notifications removed."""
        self.send(command)
        reply, events = protocol.strip_events(self._read(timeout))
        self.events += events
        return reply

    def poll_events(self, timeout: float = 0.2) -> list[int]:
        """Collect status notifications that arrived while idle (or while a job was sent)."""
        data, events = protocol.strip_events(self._read(timeout, quiet=timeout))
        self.events += events
        return events

    def status(self) -> protocol.Status:
        return protocol.parse_status(self.query(protocol.CMD_STATUS))

    def info(self) -> protocol.Info:
        return protocol.parse_info(self.query(protocol.CMD_INFO))

    def _unsent(self) -> int:
        # On Bluetooth sockets TIOCOUTQ reports the *free* send-buffer space, not the queued bytes.
        free = struct.unpack("i", fcntl.ioctl(self._sock.fileno(), termios.TIOCOUTQ, struct.pack("i", 0)))[0]
        return max(0, self._sock.getsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF) - free)

    def flush(self, timeout: float = 60.0, settle: float = 0.5):
        """Wait until the kernel has handed all queued bytes to the printer, then let it settle."""
        deadline = time.monotonic() + timeout
        try:
            while self._unsent() > 0 and time.monotonic() < deadline:
                time.sleep(0.05)
        except OSError:
            time.sleep(1.0)   # no queue introspection on this socket: fall back to a fixed wait
        time.sleep(settle)
