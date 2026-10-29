# Qutie Studio

A local web-based label designer and print server for the **HPRT Qutie / Q2**.
Design labels in your browser, save reusable templates, and print over USB on
Windows. A Raspberry Pi can later host the editor and Bluetooth print service
on your home network.

**No cloud, account, API key, or internet connection is needed during use.**
Initial dependency installation requires internet access unless packages are
already available locally. The interface is in English.

## Contents

- [Features](#features)
- [Printer compatibility](#printer-compatibility)
- [Windows quick start](#windows-quick-start)
- [Designing and printing](#designing-and-printing)
- [Docker](#docker)
- [Raspberry Pi installation](#raspberry-pi-installation)
- [Configuration](#configuration)
- [Data, backups and migration](#data-backups-and-migration)
- [API](#api)
- [Development and testing](#development-and-testing)
- [Troubleshooting](#troubleshooting)
- [Project layout](#project-layout)
- [Third-party software and licensing](#third-party-software-and-licensing)

## Features

- Text, PNG/JPEG images, QR codes, lines and frames.
- Move, resize, rotate, duplicate and remove elements; undo and redo.
- Separate horizontal/vertical centering and front/back layer controls.
- Adjustable label length, or Auto sizing that follows the content.
- The actual monochrome print raster is displayed directly in the editor.
- Named templates with embedded images, JSON import/export and duplication.
- Automatic printer status with model, firmware, readiness and battery level.
- Sequential print jobs; uncertain jobs are never retried automatically.
- Local fonts and JavaScript assets, with no CDN requests.

## Printer compatibility

| Item | Current support |
| --- | --- |
| Target printer | HPRT Qutie / Q2 |
| Tested firmware | Q2 firmware 1.1.20 |
| Tape | 15 mm continuous thermal tape |
| Printable area | 96 dots across, equivalent to 12 mm |
| Resolution | 8 dots/mm, approximately 203 dpi |
| Label length | 10–80 mm in the editor |
| Windows USB | Tested with real prints using the existing `usbprint` driver |
| Windows Bluetooth | Discovery succeeded; printing is not supported by this app |
| Linux / Raspberry Pi Bluetooth | Integrated from a Linux-tested upstream driver; this webapp still needs a real Pi hardware test |
| Linux USB | Implemented through `usblp`; real Pi hardware testing pending |
| Die-cut labels | Not supported by the current webapp; gap alignment is not implemented |

Real USB tests covered text, accented characters, QR codes, images, frames, lines
and rotation. A 40 mm test ruler measured approximately 40 mm, supporting the
100% default length correction. Physical disconnect/paper-fault tests remain
pending. Compatibility with other printer models or firmware is not guaranteed.

> **Local-network application:** there are no user accounts or authentication.
> Keep the server on a trusted home network. Do not forward its port to the
> internet or expose it through a public tunnel. Publishing this source repository
> does not publish a running printer service.

## Windows quick start

### Requirements

- Windows with **Python 3.11 or later** on PATH (required by the pinned Pillow version).
- A browser and a USB data cable.
- The Qutie switched on with continuous tape loaded.
- Git to clone the repository, or download and extract the repository ZIP instead.

```powershell
git clone https://github.com/H3adsho0ot/qutie-studio.git
cd qutie-studio
.\start.ps1
```

Open **http://localhost:8765**. The launcher creates `.venv` and installs the
runtime dependencies on the first start.

If you prefer manual setup:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m uvicorn app:app --host 127.0.0.1 --port 8765 --workers 1
```

Keep the existing **Windows `usbprint` driver**. Do not replace it with Zadig or
WinUSB. Device selection uses USB VID `2AAF` and PID `401C`.

To serve other devices on your trusted LAN:

```powershell
.\start.ps1 -ListenAddress 0.0.0.0
```

Use `http://<PC-LAN-IP>:8765` from those devices. Stop the server with **Ctrl+C**.
Always run a **single worker**, which owns the print queue and printer lock.

## Designing and printing

1. Start a new template or open a saved one. Add elements using the toolbar.
2. Select an element to edit its properties on the right. Drag to move it; use
   handles to resize or rotate it. Hover over an icon to see its action.
3. Set the print width above the label. Here, width means the label's length
   along the tape feed direction; the tape itself remains 15 mm wide.
4. New labels use **Auto**. It fits all content, including rotated bounds and
   strokes, with at least 2 mm of horizontal margin on each side. Clicking Auto
   again restores the previous manual width (initially 40 mm). Content exceeding
   80 mm including margins must be reduced before printing.
5. The editor automatically displays the final black-and-white raster. Selection
   handles are editing controls and are never printed. Printing stays disabled
   while a new raster is being calculated.
6. Click the **printer icon** once. Check the output before retrying an uncertain
   job, then cut the tape manually at the printer.

The **gear next to the battery** opens Tape & print settings:

| Setting | Default | Purpose |
| --- | --- | --- |
| Feed after printing | 14 mm | Advances tape for manual cutting |
| Length correction | 100% | Calibrates the length along the feed direction |
| Black threshold | 160 | Controls conversion to black and white |
| Dither photos | Off | Uses dithering for grayscale images |

Length correction formula: `current factor × target length / measured length`.
It does not change the physical print-head width or final feed.

Use the **disk icon** to save. The three-dot menu on each saved template (also
available by right-click) provides **Export**, **Create copy** and **Delete**.
Those actions use the selected saved template and preserve the current draft.
Exports embed their images and can be imported on another server.

The header refreshes printer status on opening and every 30 seconds. Hardware
queries are cached for 15 seconds across browsers and pause during printing.
Disconnected printers hide the previous battery reading.

## Docker

Prebuilt Linux images are published to **`ghcr.io/h3adsho0ot/qutie-studio:latest`**
for **amd64** and **arm64** (64-bit Raspberry Pi OS). To start the editor:

```sh
docker compose pull
docker compose up -d
```

Open http://localhost:8765. The base configuration has no printer passthrough.
For printing, use the supplied **Linux USB override** or **standalone Linux
Bluetooth configuration**. Both keep templates in a persistent volume and run
without privileged mode. Physical container printing still needs hardware testing;
native Windows USB is the tested setup.

See [the Docker guide](docs/docker.md) for hardware access, LAN binding, updates,
data migration and building your own image. Docker Desktop does not provide the
Windows USB/Bluetooth transport used by the native application.

## Raspberry Pi installation

Raspberry Pi OS **64-bit with Python 3.11+** is recommended. This setup runs
natively with systemd; a desktop and CUPS are not required. Actual operation of
this webapp on Raspberry Pi hardware still needs verification.

Copy the repository to `/opt/qutie-web`, including `vendor/` and `static/`.
Do not copy a Windows `.venv` to Linux.

```sh
sudo apt update
sudo apt install python3-venv bluez liblzo2-2
sudo useradd --system --home /var/lib/qutie-web --shell /usr/sbin/nologin qutie
sudo usermod -aG lp,bluetooth qutie
sudo python3 -m venv /opt/qutie-web/.venv
sudo /opt/qutie-web/.venv/bin/pip install -r /opt/qutie-web/requirements.txt
```

Close any phone app connected to the printer, turn the printer on, and discover
its address:

```sh
bluetoothctl --timeout 8 scan on
```

Create a local configuration file outside the repository:

```sh
sudo install -m 600 /dev/null /etc/qutie-web.env
sudoedit /etc/qutie-web.env
```

Enter **your own printer address**, replacing the example:

```ini
QUTIE_MAC=AA:BB:CC:DD:EE:FF
```

The reference Bluetooth driver does not require a PIN or pairing. Install and
start the service:

```sh
sudo cp /opt/qutie-web/qutie.service /etc/systemd/system/
sudo systemctl enable --now bluetooth
sudo systemctl daemon-reload
sudo systemctl enable --now qutie
```

Open **`http://<Pi-LAN-IP>:8765`**.

```sh
journalctl -u qutie -n 50       # view service logs
sudo systemctl stop qutie     # stop before backup or maintenance
sudo systemctl restart qutie  # apply configuration changes
```

### USB on Linux

Add `QUTIE_TRANSPORT=usb` to `/etc/qutie-web.env`, then load the kernel driver:

```sh
sudo modprobe usblp
sudo systemctl restart qutie
```

The service user needs access to `/dev/usb/lp*` through the `lp` group. The app
identifies the Qutie by VID/PID via sysfs and refuses an ambiguous selection.

## Configuration

Set environment variables before launching the server. The systemd service loads
`/etc/qutie-web.env`; the application does **not** automatically load `.env` files.

| Variable | Default | Description |
| --- | --- | --- |
| `QUTIE_TRANSPORT` | `usb` | Use `usb` or `bluetooth`; the included Pi service defaults to `bluetooth` |
| `QUTIE_MAC` | None | Required for Bluetooth; use your printer's address |
| `QUTIE_DATA` | `data/` beside `app.py` | Templates, images, previews and job state |

The included service uses `/var/lib/qutie-web` for data and listens on
`0.0.0.0:8765`. The Windows launcher defaults to `127.0.0.1:8765` and supports
`-ListenAddress` and `-Port` arguments.

No API keys or cloud credentials are required. Keep machine-specific settings
in ignored local files or outside the checkout.

## Data, backups and migration

`data/` contains the SQLite database, uploaded images and saved print rasters.
It is deliberately excluded from Git, together with virtual environments, logs,
local settings, credential files and working screenshots.

- **Back up:** stop the server, then copy the entire data directory.
- **Restore:** stop the destination server and restore that directory.
- **Windows to Pi:** stop the Pi service, copy the data directory to
  `/var/lib/qutie-web`, and set ownership to `qutie:qutie`.
- **Individual templates:** use JSON export/import; images are embedded.

Saved raster paths are platform-specific. Old print rasters may not open after
migration, but templates and their embedded images remain usable and generate
fresh print data. An interrupted job becomes uncertain on restart and is not
replayed automatically.

## API

FastAPI's interactive documentation is available at **`/docs`** while the server
is running. All mutation requests are intended for the same-origin local app.

| Method | Endpoint | Purpose |
| --- | --- | --- |
| GET | `/api/templates` | List saved templates |
| GET / PUT / DELETE | `/api/templates/{id}` | Load, save or delete a template |
| POST | `/api/images` | Upload a PNG/JPEG image |
| GET | `/api/images/{name}` | Retrieve an uploaded image |
| GET | `/api/qr?text=...` | Generate a QR image |
| POST | `/api/render` | Return the monochrome editor raster without saving it |
| POST | `/api/previews` | Save immutable print data and return its SHA-256 digest |
| GET | `/api/previews/{id}.png` | Retrieve saved print data |
| GET | `/api/printer` | Read cached printer status |
| POST | `/api/jobs` | Queue a job using a preview ID and unique request ID |
| GET | `/api/jobs` | List recent job states |

The client compares the live raster's digest with the saved preview before
creating a job. A changed draft or digest mismatch blocks submission. Reusing a
request ID does not print a second copy. The editor has no job-history panel,
but the queue remains available through the API.

## Development and testing

Install development dependencies into the same virtual environment:

```sh
python -m pip install -r requirements-dev.txt
python -m pytest tests -q
node --check static/app.js
node --test tests/test_label_size.cjs
```

On Windows, use `.\.venv\Scripts\python.exe` if the environment is not activated.
Node.js is needed only for the JavaScript checks, not for running the app.
GitHub Actions runs the checks on Ubuntu and Windows with Python 3.11.

Tests use temporary data and a simulated printer. They cover template persistence,
image validation, raster geometry, identical editor/print bytes, status caching,
queue deduplication and failure without automatic replay. Size tests cover empty
and short labels, multiple elements, rotated/negative bounds, rounding and overflow.
They do not replace a physical hardware test.

### Optional physical calibration

```powershell
# Create a test image; this does not print:
.\.venv\Scripts\python.exe hardware_test.py
# Send exactly one real test label through the running server:
.\.venv\Scripts\python.exe hardware_test.py --print
```

`create_full_test.py` adds an 80 mm demonstration template to a running local
server without printing it. It includes an image, QR code, ruler, rotated text
and accented characters.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| Printer is Offline | Power, USB data cable, and whether another app holds the connection |
| USB interface will not open | Keep the native Windows `usbprint` driver; do not replace it |
| Bluetooth reports missing configuration | Set `QUTIE_MAC` and restart; Bluetooth is Linux-only |
| Linux reports no unique USB port | Load `usblp`, check VID/PID and `lp` permissions |
| Print icon is disabled | Wait for the raster, check for an active job, or reduce Auto content to 80 mm |
| Length is slightly wrong | Measure a known ruler and adjust Length correction |
| Transfer outcome is uncertain | Inspect the label before starting another job; do not assume nothing printed |

## Project layout

```text
app.py                      FastAPI API, persistence, rendering and job queue
printer.py                  Shared printer API with Windows/Linux USB and Linux Bluetooth
start.ps1                   Windows launcher
qutie.service               Raspberry Pi systemd service
Dockerfile                  Non-root Linux image for amd64/arm64
compose*.yaml               Editor, Linux USB and Linux Bluetooth configurations
docs/docker.md              Docker installation and publishing guide
scripts/                    Disposable container integration checks
static/                     Browser editor, styles and bundled font/JavaScript assets
tests/                      Application and automatic-sizing tests
vendor/qutie-linux/         Pinned upstream Qutie implementation and its license
hardware_test.py            Optional physical calibration helper
create_full_test.py         Demonstration-template helper
requirements*.txt           Pinned runtime/development dependencies
THIRD_PARTY_NOTICES.md       Upstream versions, provenance and licenses
data/                       Local runtime data (created automatically, ignored by Git)
```

## Third-party software and licensing

This project uses the [AnonTester Qutie protocol implementation](https://github.com/AnonTester/prt-qutie-label-printer)
at commit **`e6e3f9c595bc4cd3e08a6886054b8b24d3d9e2d3`** (MIT), Konva 9.3.22
(MIT), and Noto Sans (SIL Open Font License 1.1). Their license files are included.
See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) for details.

The original application code has no separately granted license at this time.
Third-party components retain their own licenses. This project is independent
of HPRT and is not an official HPRT product.
