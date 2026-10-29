# Running Qutie Studio with Docker

Image: **`ghcr.io/h3adsho0ot/qutie-studio:latest`**

The Linux image supports **amd64** PCs/servers and **arm64** Raspberry Pi OS
(64-bit). It contains the editor, bundled fonts and JavaScript, printer service,
and runtime dependencies. No API key is needed. Templates and print data live in
a separate volume, never in the published image.

Container builds and HTTP/persistence tests run in GitHub Actions. Physical USB
and Bluetooth printing from a container still needs a real hardware acceptance
test. Native Windows USB printing remains the hardware-tested setup.

## Choose a setup

| Setup | Command | Printer access |
| --- | --- | --- |
| Editor only | `docker compose up -d` | None; status is Offline |
| Linux USB | `docker compose -f compose.yaml -f compose.usb.yaml up -d` | One explicitly mapped `usblp` device |
| Linux Bluetooth | `docker compose -f compose.bluetooth.yaml up -d` | Direct RFCOMM through the Linux host network |

Use Docker Engine with the Compose plugin. The hardware configurations target a
regular Linux host with rootful Docker. Docker Desktop on Windows/macOS can run
the editor, but these files do not forward the Windows/macOS USB or Bluetooth
stack into a Linux container. Use the native Windows launcher for Windows printing.

Do not run the native service and container against the same printer at once.

## Editor-only quick start

From the cloned repository:

```sh
docker compose pull
docker compose up -d
```

Open **http://localhost:8765**. The base configuration binds only to loopback.
If another application already uses port 8765, set `QUTIE_PORT=8766` in a local
`.env` file before starting and open http://localhost:8766 instead.

For access from a trusted LAN, set `QUTIE_BIND_ADDRESS=0.0.0.0` in `.env` and use
`http://<host-LAN-IP>:8765`. There is no authentication; do not expose the service
to the internet. `.env` is ignored by Git and excluded from the Docker build.
Compose reads it for interpolation; the app itself does not load `.env` files.

## USB on Linux or Raspberry Pi

Plug in and power on the Qutie, then load the host's `usblp` driver:

```sh
sudo modprobe usblp
ls -l /dev/usb/lp*
export QUTIE_USB_DEVICE=/dev/usb/lp0
export QUTIE_USB_GID=$(stat -c '%g' "$QUTIE_USB_DEVICE")
docker compose -f compose.yaml -f compose.usb.yaml pull
docker compose -f compose.yaml -f compose.usb.yaml up -d
```

Replace `/dev/usb/lp0` with the actual Qutie device. `QUTIE_USB_GID` gives the
non-root container process access through the device's numeric host group ID.
Save both settings in an ignored `.env` file if desired. Only the chosen device
is passed through. `/sys` is mounted read-only so the app can verify VID `2AAF`
and PID `401C` and refuse a different or ambiguous printer.

USB device mappings may become stale after unplugging/reconnecting or device
renumbering. Update `QUTIE_USB_DEVICE` and its group if needed, then recreate:

```sh
docker compose -f compose.yaml -f compose.usb.yaml up -d --force-recreate
```

Check any partially printed label before retrying. The service never automatically
replays an uncertain job.

## Bluetooth on Linux or Raspberry Pi

The host manages the Bluetooth adapter. Close any phone app connected to the
printer, enable Bluetooth, and discover the printer's address:

```sh
sudo systemctl enable --now bluetooth
bluetoothctl --timeout 8 scan on
export QUTIE_MAC=AA:BB:CC:DD:EE:FF
docker compose -f compose.bluetooth.yaml pull
docker compose -f compose.bluetooth.yaml up -d
```

Replace the example MAC with your printer's address. Store it in the ignored
`.env` file for future runs. The reference driver uses direct RFCOMM sockets;
it does not need a D-Bus socket mount inside the container. Host networking gives
it access to the Linux Bluetooth network namespace. No `privileged` mode or
additional Linux capabilities are configured.

This is a **standalone Compose file**, not an override: do not combine it with
`compose.yaml`. It serves the app on the host's **port 8765 on all interfaces**;
Docker port mappings and `QUTIE_PORT` do not apply in host-network mode. Use only
on a trusted LAN. Rootless Docker and Docker Desktop's TCP/UDP host networking
are not substitutes for the host Linux Bluetooth stack.

## Data and updates

All configurations use the Compose volume `qutie-data`, mounted at `/data`.
Its full Docker name is normally `<project-name>_qutie-data`; use the same checkout
directory/project name when switching transports to keep the same templates.

```sh
docker compose logs --tail 80
docker compose down
docker compose pull
docker compose up -d
```

Use the same `-f` arguments for every command if you selected USB or Bluetooth.
Stopping/removing the container keeps the volume. **Do not use `down --volumes`**
unless you intend to remove all saved templates and print data.

For backups or migration, stop the service first and back up the whole named
volume. The runtime user is **UID/GID 10001**; a bind-mounted data directory must
be writable by that identity. Import/export is the simplest way to transfer
individual templates from the native app. When migrating all data, use an empty
destination volume, copy the stopped native app's data into it and set ownership
to `10001:10001`. Old platform-specific raster paths may not open after migration;
templates still generate fresh print data. Keep backups outside Git (for example
in the ignored `backups/` directory).

For an exact deployment, use the image digest shown in the workflow summary
instead of `latest`. Each published source commit also gets a `sha-<full-commit>`
tag. `latest` is updated after successful checks on `main`.

## Build and test locally

```sh
docker build -t qutie-studio:local .
```

The build uses an allowlisted `.dockerignore` and explicit `COPY` paths. Local
templates, uploaded images, credentials, Git metadata, screenshots and caches are
excluded from the build context. It checks Bluetooth socket constants and LZO
availability for each target architecture without connecting to a printer.

On a Linux development machine with Python available, test the built image:

```sh
bash scripts/test-container.sh qutie-studio:local
```

This uses its own disposable container, named volume and loopback port 18765. It
checks the non-root user, absence of local working files, static assets, image
upload, matching raster/preview digests and template/raster persistence across a
restart. It never submits a print job. Its container and volume are removed at
the end. Set `QUTIE_TEST_PORT` if 18765 is already in use.

## Publishing

[The container workflow](../.github/workflows/container.yml) validates Compose,
runs the application tests, builds a disposable image, and runs the container
smoke test. Only successful `main` builds publish amd64/arm64 images to GHCR.
Pull requests can run checks but cannot publish. Manual runs are also supported
on `main`.

Publishing uses the short-lived **GitHub Actions `GITHUB_TOKEN`** with
`packages: write`; no personal access token or registry password is stored in
the repository. Actions are pinned to verified commit IDs. Published images carry
the source revision label and build provenance.

GHCR creates new packages as private by default. The package owner must set its
visibility to Public in GitHub's package settings once to allow anonymous pulls;
the repository's public visibility alone does not make a package public.

Official references: [GitHub Container registry](https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry),
[package visibility](https://docs.github.com/en/packages/learn-github-packages/configuring-a-packages-access-control-and-visibility),
[Docker host networking](https://docs.docker.com/engine/network/drivers/host/).
