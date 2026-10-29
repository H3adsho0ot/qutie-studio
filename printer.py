"""Qutie transports. No reconnect/replay after raster transmission starts."""
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / 'vendor/qutie-linux/src'))
from qutie import protocol, raster


class USB:
    def __init__(self):
        if sys.platform == 'win32':
            import ctypes as c
            import winreg
            from ctypes import wintypes as w
            self.c = c
            self.k = c.WinDLL('kernel32', use_last_error=True)
            self.k.CreateFileW.argtypes = [w.LPCWSTR, w.DWORD, w.DWORD, c.c_void_p, w.DWORD, w.DWORD, w.HANDLE]
            self.k.CreateFileW.restype = w.HANDLE
            self.k.ReadFile.argtypes = self.k.WriteFile.argtypes = [w.HANDLE, c.c_void_p, w.DWORD, c.POINTER(w.DWORD), c.c_void_p]
            self.k.CloseHandle.argtypes = [w.HANDLE]
            root = r'SYSTEM\CurrentControlSet\Control\DeviceClasses\{28d78fad-5a12-11d1-ae5b-0000f803a8c2}'
            paths = []
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, root) as key:
                for i in range(winreg.QueryInfoKey(key)[0]):
                    name = winreg.EnumKey(key, i)
                    if 'vid_2aaf&pid_401c' in name.lower():
                        paths.append('\\\\?\\' + name.removeprefix('##?#').removeprefix('##?\\'))
            if not paths:
                raise ConnectionError('Qutie not found over USB.')
            self.handle = self.k.CreateFileW(paths[0], 0xC0000000, 3, None, 3, 0, None)
            if self.handle == c.c_void_p(-1).value:
                raise OSError(c.get_last_error(), 'Could not open the USB printer interface')
        else:
            # Resolve usblp by sysfs identity, never send to an arbitrary printer.
            candidates = []
            for device in Path('/sys/class/usbmisc').glob('lp*'):
                for parent in (device.resolve(), *device.resolve().parents):
                    try:
                        if (parent / 'idVendor').read_text().strip() == '2aaf' and (parent / 'idProduct').read_text().strip() == '401c':
                            candidates.append('/dev/usb/' + device.name)
                            break
                    except OSError:
                        continue
            if len(candidates) != 1:
                raise ConnectionError('Could not identify a unique Qutie USB port (check usblp).')
            self.fd = os.open(candidates[0], os.O_RDWR | os.O_NONBLOCK)

    def write(self, data):
        if sys.platform == 'win32':
            from ctypes import wintypes as w
            count = w.DWORD()
            if not self.k.WriteFile(self.handle, data, len(data), self.c.byref(count), None) or count.value != len(data):
                raise ConnectionError('USB transfer failed; the label may be incomplete.')
        else:
            deadline = time.monotonic() + 10
            while data:
                try:
                    count = os.write(self.fd, data)
                    if not count:
                        raise ConnectionError('USB connection closed.')
                    data = data[count:]
                except BlockingIOError:
                    if time.monotonic() > deadline:
                        raise TimeoutError('USB write timed out.')
                    time.sleep(.05)

    def read(self):
        if sys.platform == 'win32':
            from ctypes import wintypes as w
            data = self.c.create_string_buffer(512)
            count = w.DWORD()
            if not self.k.ReadFile(self.handle, data, 512, self.c.byref(count), None):
                raise OSError(self.c.get_last_error(), 'Could not read USB response')
            return data.raw[:count.value]
        import select
        return os.read(self.fd, 512) if select.select([self.fd], [], [], .5)[0] else b''

    def close(self):
        if sys.platform == 'win32':
            self.k.CloseHandle(self.handle)
        else:
            os.close(self.fd)


class USBSession:
    def __init__(self):
        self.io = USB()
        self.key = None
        try:
            # USB firmware can expose the command stream without Bluetooth's session XOR.
            self.io.write(protocol.CMD_INFO)
            raw_info = self._read(143)
            try:
                protocol.parse_info(raw_info)
                self.key = 0
                return
            except ValueError:
                pass
            self.io.write(protocol.handshake_request(40, 87))
            if self._read(2) != b'OK':
                raise ConnectionError('No response from Qutie. Turn on the printer and check the USB data cable.')
            self.key = 127
        except Exception:
            self.io.close()
            raise

    def _read(self, length):
        data = b''
        deadline = time.monotonic() + 4
        while len(data) < length and time.monotonic() < deadline:
            data += self.io.read()
            data, _ = protocol.strip_events(data)
        return data

    def send(self, data):
        self.io.write(protocol.xor(data, self.key))

    def status(self):
        self.send(protocol.CMD_STATUS)
        return protocol.parse_status(self._read(17))

    def info(self):
        self.send(protocol.CMD_INFO)
        return protocol.parse_info(self._read(143))

    def flush(self):
        time.sleep(1)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.io.close()


def session():
    if os.environ.get('QUTIE_TRANSPORT', 'usb') == 'bluetooth':
        if sys.platform != 'linux':
            raise ConnectionError('Bluetooth printing is prepared for Linux/Raspberry Pi. Please use USB on Windows.')
        mac = os.environ.get('QUTIE_MAC', '').strip()
        if not mac:
            raise ConnectionError('Set QUTIE_MAC to your printer Bluetooth address before using Bluetooth.')
        from qutie.transport import Session
        return Session(mac, timeout=8, attempts=1)
    return USBSession()


def _status():
    with session() as link:
        info, state = link.info(), link.status()
        return {'connected': True, 'model': info.model, 'firmware': info.firmware,
                'battery': state.battery, 'ready': state.can_print, 'problems': state.problems}


def _print_image(image, feed_mm=14):
    with session() as link:
        link.info()
        state = link.status()
        if not state.can_print:
            raise ConnectionError('Printer not ready: ' + ', '.join(state.problems))
        width, _, packed = raster.to_raster(image)
        link.send(protocol.cmd_density(75))
        for block in raster.raster_blocks(width, packed):
            link.send(block)
        link.send(protocol.cmd_feed(round(feed_mm * 8)))
        link.flush()
        # Ready status is a practical indication, not a physical completion receipt.
        for _ in range(8):
            try:
                after = link.status()
                if after.can_print:
                    return 'Sent; the printer is responding again. Please check the label.'
                raise ConnectionError('Printer reported after transfer: ' + ', '.join(after.problems))
            except ValueError:
                time.sleep(1)
        return 'Sent; completion not confirmed. Check the label before printing again.'


def _run(args, timeout):
    import subprocess
    import json
    try:
        result = subprocess.run([sys.executable, str(Path(__file__).resolve()), *args],
                                capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=timeout,
                                env={**os.environ, 'PYTHONIOENCODING': 'utf-8'},
                                creationflags=0x08000000 if sys.platform == 'win32' else 0)
    except subprocess.TimeoutExpired:
        raise TimeoutError('Printer timed out. Check the connection; no automatic retry.')
    value = json.loads(result.stdout) if result.stdout.strip() else {}
    if result.returncode:
        raise ConnectionError(value.get('error') or result.stderr.strip() or 'Printer process failed')
    return value


def status():
    return _run(['status'], 15)


def print_image(image, feed_mm=14):
    import tempfile
    with tempfile.TemporaryDirectory(prefix='qutie-print-') as tmp:
        path = Path(tmp) / 'job.png'
        image.save(path)
        return _run(['print', str(path), str(feed_mm)], 60)


if __name__ == '__main__':
    import json
    from PIL import Image
    try:
        if sys.argv[1] == 'status':
            value = _status()
        else:
            with Image.open(sys.argv[2]) as image:
                value = _print_image(image, float(sys.argv[3]))
        print(json.dumps(value, ensure_ascii=True))
    except Exception as e:
        print(json.dumps({'error': str(e)}, ensure_ascii=True))
        sys.exit(1)
