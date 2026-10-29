"""Command line interface: qutie status | info | scan | print | test-page."""
import argparse
import os
import sys

from PIL import Image

from . import discovery, job, protocol
from .transport import Session


def _resolve_mac(args) -> str:
    mac = args.mac or os.environ.get("QUTIE_MAC")
    if mac:
        return mac
    found = discovery.known_printers()
    if len(found) == 1:
        return found[0][0]
    sys.exit("no printer selected: pass --mac or set QUTIE_MAC (run `qutie scan` to find it)")


def cmd_scan(args):
    for mac, name in discovery.scan(args.seconds):
        print(mac, name)


def cmd_status(args):
    with Session(_resolve_mac(args)) as s:
        st = s.status()
    print(f"battery: {st.battery}%  auto-off: {st.auto_off_seconds // 60} min")
    print("status: " + ("ready" if not st.problems else "; ".join(st.problems)))


def cmd_info(args):
    with Session(_resolve_mac(args)) as s:
        info = s.info()
    for field, value in vars(info).items():
        print(f"{field}: {value}")


def cmd_test_page(args):
    with Session(_resolve_mac(args)) as s:
        s.send(protocol.CMD_TEST_PAGE)
        s.flush()


def cmd_print(args):
    image = Image.open(args.image)
    with Session(_resolve_mac(args)) as s:
        rows = job.send_image(s, image, copies=args.copies, density=args.density, label_mm=args.label_mm,
                              feed_mm=args.feed_mm, rotation=args.rotate, width=args.width)
    print(f"printed {args.copies} copy/copies, {args.width}x{rows} dots")


def main(argv=None):
    p = argparse.ArgumentParser(prog="qutie")
    p.add_argument("--mac", help="printer Bluetooth address (or set QUTIE_MAC)")
    sub = p.add_subparsers(dest="command", required=True)
    sc = sub.add_parser("scan", help="scan for printers")
    sc.add_argument("--seconds", type=int, default=10)
    sc.set_defaults(func=cmd_scan)
    sub.add_parser("status", help="battery and auto-off").set_defaults(func=cmd_status)
    sub.add_parser("info", help="model, firmware, serial").set_defaults(func=cmd_info)
    sub.add_parser("test-page", help="print the built-in test page").set_defaults(func=cmd_test_page)
    pr = sub.add_parser("print", help="print an image")
    pr.add_argument("image")
    pr.add_argument("--density", type=int, default=75, help="0..255 (default 75)")
    pr.add_argument("--copies", type=int, default=1)
    pr.add_argument("--width", type=int, default=protocol.HEAD_DOTS, help="dots across the label")
    pr.add_argument("--rotate", type=int, choices=[0, 90, 180, 270], default=0,
                    help="rotate the image counter-clockwise before printing (landscape designs: 90 or 270)")
    group = pr.add_mutually_exclusive_group()
    group.add_argument("--label-mm", type=float, help="label length in mm: feed to the next label")
    group.add_argument("--feed-mm", type=float, default=14, help="continuous stock: feed after print (default 14)")
    pr.set_defaults(func=cmd_print)
    args = p.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
