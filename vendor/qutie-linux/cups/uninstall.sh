#!/bin/sh
# Remove the Qutie CUPS files (run as root). Optional argument: queue name to delete.
set -eu
cupslib=${CUPS_SERVERBIN:-/usr/lib/cups}
[ "$(id -u)" -eq 0 ] || { echo "run as root" >&2; exit 1; }
[ $# -ge 1 ] && lpadmin -x "$1" || true
rm -f "$cupslib/filter/rastertoqutie" "$cupslib/backend/qutie" /usr/share/cups/model/qutie.ppd
rm -rf "$cupslib/qutie"
echo "removed"
