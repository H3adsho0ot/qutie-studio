"""Find Qutie printers through BlueZ (bluetoothctl)."""
import subprocess
import tempfile
import threading
import time


def known_printers() -> list[tuple[str, str]]:
    """Devices BlueZ currently knows whose name starts with 'Qutie': (address, name)."""
    try:
        out = subprocess.run(["bluetoothctl", "devices"], capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    found = []
    for line in out.splitlines():
        parts = line.split(maxsplit=2)
        if len(parts) == 3 and parts[0] == "Device" and parts[2].startswith("Qutie"):
            found.append((parts[1], parts[2]))
    return found


def scan(seconds: int = 8, cancel: threading.Event | None = None) -> list[tuple[str, str]]:
    """Scan for `seconds` (or until `cancel` is set), then return the printers BlueZ found."""
    with tempfile.TemporaryFile("w+") as out:
        try:
            proc = subprocess.Popen(["bluetoothctl", "--timeout", str(seconds), "scan", "on"],
                                    stdout=out, stderr=subprocess.STDOUT, text=True)
        except OSError:
            return known_printers()
        deadline = time.monotonic() + seconds + 10
        while proc.poll() is None:
            if (cancel is not None and cancel.is_set()) or time.monotonic() > deadline:
                proc.terminate()
                break
            time.sleep(0.1)
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()
        out.seek(0)
        output = out.read()
    if cancel is not None and cancel.is_set():
        return []
    if "Failed to start discovery" in output:
        # another scan (CUPS, another window) already runs: let it finish, then use what it found
        time.sleep(seconds)
    return known_printers()
