"""CUPS backend: sends a plain Qutie command stream over Bluetooth.

URI: qutie://AA-BB-CC-DD-EE-FF (the Bluetooth address with dashes).
"""
import os
import re
import sys

from . import discovery, protocol
from .transport import Session

# CUPS backend exit codes
OK, FAILED, RETRY = 0, 1, 6

_URI = re.compile(r"^qutie://([0-9A-Fa-f]{2}(?:-[0-9A-Fa-f]{2}){5})/?$")
CHUNK = 4096
SCAN_SECONDS = 6


# IPP printer-state-reasons for each status flag; everything else is reported as "other". CUPS drops
# reasons a backend sets when it exits unless they end in "-report", so that suffix is used throughout.
_REASON_FOR_FLAG = {0x01: "media-empty-report", 0x10: "cover-open-report"}
_ALL_REASONS = ("media-empty-report", "cover-open-report", "other-report")
LOW_BATTERY_PERCENT = 10


def report_status(status: protocol.Status, out=None) -> bool:
    """Tell CUPS about the printer condition (STATE:/ERROR:/WARNING:); return True if printing is possible."""
    out = out or sys.stderr
    reasons = set()
    for bit, (_, description) in protocol.STATUS_FLAGS.items():
        if not status.flags & bit:
            continue
        message = description[0].upper() + description[1:]
        if bit & protocol.BLOCKING_FLAGS:
            reasons.add(_REASON_FOR_FLAG.get(bit, "other-report"))
            print(f"ERROR: {message}", file=out)
        else:
            reasons.add("other-report")
            print(f"WARNING: {message}", file=out)
    if not status.flags & 0x08 and status.battery <= LOW_BATTERY_PERCENT:
        reasons.add("other-report")
        print(f"WARNING: Battery low ({status.battery}%)", file=out)
    changes = [f"+{r}" if r in reasons else f"-{r}" for r in _ALL_REASONS]
    print("STATE: " + ",".join(changes), file=out)
    return status.can_print


def uri_to_mac(uri: str) -> str:
    match = _URI.match(uri or "")
    if not match:
        raise ValueError(f"bad device URI {uri!r}, expected qutie://AA-BB-CC-DD-EE-FF")
    return match.group(1).replace("-", ":").upper()


def mac_to_uri(mac: str) -> str:
    return "qutie://" + mac.replace(":", "-").upper()


def discover(out=sys.stdout):
    for mac, name in discovery.scan(SCAN_SECONDS):
        print(f'direct {mac_to_uri(mac)} "PRT Qutie" "PRT Qutie ({name})" "MFG:PRT;MDL:Qutie;CLS:PRINTER;"', file=out)


def main(argv, env=None, stdin=None) -> int:
    env = os.environ if env is None else env
    if len(argv) == 1:
        discover()
        return OK
    if len(argv) not in (6, 7):
        print(f"Usage: {argv[0]} job-id user title copies options [file]", file=sys.stderr)
        return FAILED
    try:
        mac = uri_to_mac(env.get("DEVICE_URI", ""))
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return FAILED
    try:
        source = open(argv[6], "rb") if len(argv) == 7 else (stdin or sys.stdin.buffer)
    except OSError as exc:
        print(f"ERROR: cannot read job data: {exc}", file=sys.stderr)
        return FAILED
    try:
        with Session(mac) as session:
            try:
                before = session.status()
            except (ValueError, OSError) as exc:
                print(f"WARNING: cannot read printer status ({exc}); printing anyway", file=sys.stderr)
            else:
                if not report_status(before):
                    print(f"INFO: Not ready: {', '.join(before.problems)}", file=sys.stderr)
                    return RETRY
            while True:
                chunk = source.read(CHUNK)
                if not chunk:
                    break
                session.send(chunk)
            session.flush()
            try:
                after = session.status()
            except (ValueError, OSError):
                after = None
            if after is not None and not report_status(after):
                print("WARNING: The printer reported a problem after the job was sent; "
                      "the label may not have printed", file=sys.stderr)
    except OSError as exc:
        print(f"ERROR: cannot reach printer: {exc}", file=sys.stderr)
        print("STATE: +offline-report", file=sys.stderr)
        return RETRY
    print("STATE: -offline-report", file=sys.stderr)
    return OK
