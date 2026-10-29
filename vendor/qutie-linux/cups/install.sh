#!/bin/sh
# Install the Qutie CUPS backend, filter and PPD (run as root).
#   sudo cups/install.sh                      install only
#   sudo cups/install.sh AA:BB:CC:DD:EE:FF    install and create the print queue "Qutie"
#   sudo cups/install.sh AA:BB:CC:DD:EE:FF MyQueue
set -eu

here=$(cd "$(dirname "$0")" && pwd)
src=$(dirname "$here")/src/qutie
cupslib=${CUPS_SERVERBIN:-/usr/lib/cups}
model=/usr/share/cups/model

[ "$(id -u)" -eq 0 ] || { echo "run as root" >&2; exit 1; }

install -d -m 755 "$cupslib/qutie"
rm -rf "$cupslib/qutie/qutie"
cp -r "$src" "$cupslib/qutie/qutie"
find "$cupslib/qutie" -name __pycache__ -prune -exec rm -rf {} +
chown -R root:root "$cupslib/qutie"
chmod -R go-w,a+rX "$cupslib/qutie"
python3 -m compileall -q "$cupslib/qutie/qutie"

install -m 755 "$here/rastertoqutie" "$cupslib/filter/rastertoqutie"
install -m 755 "$here/qutie" "$cupslib/backend/qutie"
install -d -m 755 "$model"
install -m 644 "$here/qutie.ppd" "$model/qutie.ppd"
echo "installed backend, filter and PPD"

if [ $# -ge 1 ]; then
    uri="qutie://$(echo "$1" | tr ':' '-' | tr 'a-f' 'A-F')"
    name=${2:-Qutie}
    lpadmin -p "$name" -E -v "$uri" -P "$model/qutie.ppd" -o printer-is-shared=false
    echo "created queue $name"
fi
