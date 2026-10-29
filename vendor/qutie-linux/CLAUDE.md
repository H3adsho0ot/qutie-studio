# qutie (PRT Qutie label printer for Linux)

Python package in `src/qutie` (`protocol` pure byte builders/parsers, `lzo`, `raster`, `transport` RFCOMM session,
`discovery`, `cli`, and the CUPS pieces `cupsraster` reader, `cups_filter`, `cups_backend`). `job` is the print
sequence shared by CLI and designer. `designer/` is the optional Qt label editor (`model` has no Qt imports;
`canvas`, `render`, `panels`, `printing`, `app`; see `docs/designer.md`). `cups/` holds the thin entry scripts,
`qutie.ppd` (edit it directly, check with `cupstestppd`) and `install.sh`/`uninstall.sh` (root). Protocol notes live
in `docs/protocol.md`; update them when the wire behaviour changes.

## Build / test
- `.venv/bin/pytest` (venv is git-ignored). Live printer tests are manual: `qutie status`, `qutie print`.
- Printer address is never committed; pass `--mac` or `QUTIE_MAC`.
- Tests must never touch the real user configuration: `tests/conftest.py` points `XDG_CONFIG_HOME` at a temporary
  directory (a test once overwrote the saved printer with a fake address). Never write real settings from tests.

## Rules
- Public-repo privacy: no hostnames, IPs, absolute paths, Bluetooth addresses, serial numbers, keys. Test fixtures
  use made-up values.
- Reverse-engineering artifacts (APKs, decompiled sources, native libs) stay outside the repo; only protocol
  notes and clean-room code go in.
- The filter outputs the plain command stream; only the backend (via `Session`) applies the XOR.
- `TIOCOUTQ` on Bluetooth sockets returns free send-buffer space, not queued bytes (see `Session._unsent`).
- Designer: scene units are printer dots; the on-screen view, the "as printed" preview and the print image all come
  from `render.render_scene`. Always use `scene.macro(...)` (not bare beginMacro) and the live element from
  `scene.doc.find(id)`: `AddElement` recreates elements from saved state. In item mouse handlers use
  `event.scenePos()`, not `event.pos()` (it lags after the item moves itself). Qt tests need
  `QT_QPA_PLATFORM=offscreen` (set in `tests/conftest.py`).
- Backends run as `lp` (mode 755) under AppArmor; keep them import-only against `/usr/lib/cups/qutie`.
- Every byte sent to the printer after the handshake is XORed with the session key (`transport.Session.send`).
