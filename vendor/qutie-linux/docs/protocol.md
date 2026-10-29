# PRT Qutie wire protocol

Reference for talking to the PRT Qutie (HPRT "Q2" family) label printer over Bluetooth without the vendor app.
The reference implementation is `src/qutie/protocol.py` (byte builders and parsers) and `src/qutie/transport.py`
(session).

## 1. Provenance and confidence

Derived from static analysis of the HerePrint Android app (v3.19.6, HPRT SDK, Java and native code) and checked
against a real Qutie (firmware 1.1.22, board 2.0.0). Every item carries a confidence tag:

| Tag | Meaning |
|---|---|
| **HW** | verified on the real printer |
| **APP** | taken from the app's code path for this printer model; not exercised on hardware |
| **INF** | inferred (naming, structure); treat as a hypothesis |

All multi-byte integers are little-endian unless stated. `ESC` = 0x1B, `GS` = 0x1D, `FS` = 0x1C.
Hex strings are plain bytes before the session XOR (section 3).

## 2. Transport (HW)

- Bluetooth Classic (BR/EDR), not BLE. Device class `0x040680` (imaging, printer).
- Advertised name `Qutie-<last four hex digits of the Bluetooth address>`.
- SDP records: Serial Port Profile (UUID 0x1101, name "SPP slave") on **RFCOMM channel 1**; PnP Information
  (0x1200); a vendor UUID `ffcacade-afde-cade-defa-cade00000000` that the app's transport does not use.
- An RFCOMM connection to channel 1 is accepted without PIN, pairing or bonding. The app itself uses an insecure
  RFCOMM socket created for the SPP UUID.
- The printer sends nothing right after connecting, but it does volunteer a short `pooli_sta=<byte>` message
  whenever its status changes (section 5.1). There is no message framing: commands are bare byte strings, query
  replies are fixed-length blocks ending in the ASCII marker `END`.
- Only one client can be connected. After a session is closed the printer needs about a second to accept a new
  one; an immediate reconnect may be refused (`Host is down`) or reset (`Connection reset by peer`). Retry.
- The printer powers itself off after the auto-off time (default 900 s). A powered-off printer is not
  discoverable and a connect fails with `Host is down` (errno 112, a page timeout). The same error appears when
  the printer is out of range or already connected to another device, such as the phone app.
- After switching on (a long press of the power button, sometimes needed a second time) the printer can take a few
  seconds before it answers an inquiry scan. A scan of about 8 seconds finds it reliably once it is up.
- It appears as "paired" to BlueZ but is never bonded; no link key or PIN is involved at any point.

## 3. Session handshake and write obfuscation (HW)

Right after the RFCOMM connection opens, the client sends a 10-byte request:

    1B 1C "set mm" r1 r2          (r1, r2: random bytes, each 1..100)

The printer answers two bytes:

| Reply | Meaning |
|---|---|
| `4F 4B` ("OK") | enable write obfuscation (this printer) |
| `4E 47` ("NG") | no obfuscation; a challenge/response is required instead (section 3.2) |

### 3.1 Obfuscation after OK
From now on every byte the client sends is XORed with the single byte key `K = (r1 + r2) & 0xFF`. The handshake
request itself is sent in the clear. Bytes sent by the printer are never obfuscated. A key of 0 would be a no-op;
since r1 and r2 are at least 1, K is only zero when r1 + r2 is 256, which cannot happen (max 200).

Example with r1 = 40, r2 = 87 (K = 0x7F): the status command `1B 12 73` goes on the wire as `64 6D 0C`.

### 3.2 NG fallback (APP, not needed on the Qutie)
Some firmware answers NG. The app then sends a 19-byte challenge `1B 1B 1B` followed by 16 pseudo-random bytes
(each `(rand() % 100) / (rand() % 10)`, division skipped when the divisor is 0) and expects the printer to
answer with a 16-byte digest. The digest is a customised single-block MD5: the 16 challenge bytes are XORed with
fixed per-position constants, scattered into a 64-byte template stored in the native library, run through the
standard MD5 round functions and constants, and the first output word is passed through a 256-entry
substitution table. In this mode writes are not obfuscated. This path is not implemented here.

## 4. Command reference

### 4.1 Queries

| Command | Bytes | Reply |
|---|---|---|
| Status (HW) | `1B 12 73` | 17 bytes, section 5 |
| Info (HW) | `1B 12 64` | 143 bytes, section 6 |

Replies arrive within about 200 ms. The app waits up to 1 s and, if the reply is shorter than expected,
reads once more and concatenates (the reply can be split across two RFCOMM reads).

**While the printer is mechanically printing it does not answer queries** (HW). A status request sent right after
the last raster data gets no reply for several seconds; ask again every second or so until a complete block with
the `END` marker arrives (the designer waits up to 8 seconds). Replies may also be glued to `pooli_sta=`
notifications (section 5.1) and must be parsed after removing those.

### 4.2 Settings

| Command | Bytes | Notes |
|---|---|---|
| Print density (HW) | `1D "setc" d` | d 0..255; app default 75; the current value is echoed in status byte 6 |
| Print speed (APP) | `1D "sets" s` | accepted range 1..30; the app's configured value for the Qutie is 35, which its own range check rejects, so it never sends this command |
| Auto power-off (APP) | `1D "sett" nL nH` | seconds; status bytes 4..5 report it |
| Paper type (APP) | `1D "setp" t` | selects the media mode (label with gap, continuous, ...); the values are defined in the app's Dart code and not yet mapped; the printer acknowledges |
| Learn paper (APP) | `1D "setL"` | media calibration ("paper study") |
| LED colour (APP) | `1D "setl" c` | c 0..5 |
| Printer name (APP) | `1D "setn"` then up to 12 ASCII bytes | |
| Factory settings (APP) | `1D "setr"` | |
| Justification (APP) | `1B 61 n` | n = 0 left, 1 centre, 2 right (also accepts ASCII `30`..`32`); aligns print data narrower than the head; the app sends 1 before each job |

### 4.3 Paper movement and self-test

| Command | Bytes | Notes |
|---|---|---|
| Feed paper (HW) | `1B 1B 01 nL nH` | feed n dots; used after a job on continuous stock |
| Feed to next label (APP) | `1D 66 nL nH` | advance n dots / to the label gap; used after a job on label stock |
| Self-test page (APP) | `1B 1B 00` | |
| Clean / cleaning feed (APP) | `1B 12 43` sent twice | |

### 4.4 Key/value store (APP)
Persistent settings use a textual command family introduced by `1B 1C 26 20 "V1 "` (ESC FS `&` space `V1`):

| Operation | Bytes |
|---|---|
| Set | `1B 1C 26 20 "V1 setkey" 0D 0A` t `kL kH` len value |
| Get | `1B 1C 26 20 "V1 getkey" 0D 0A` t `kL kH` len |
| Action | `1B 1C 26 20 "V1 do \"<name>\"" 0D 0A` |
| Read value | `1B 1C 26 20 "V1 getval \"<name>\"" 0D 0A` |

`t` is a table byte (always 1 in the app). Known keys: 209 power-on action, 215 lid-open action, 495 volume.
Known actions: `save_param_zone` (commit settings to flash; the app sends it after changing the keys above),
`reset_printer`. Other names exist for Wi-Fi and NFC features that the Qutie does not have.

### 4.5 Raster print block (HW)

    1D 76 30 30  wL wH  hL hH  c0 c1 c2 c3  <c bytes of LZO1X data>

| Field | Meaning |
|---|---|
| `1D 76 30 30` | `GS v 0` raster command with mode byte `0x30` |
| w | bytes per row (dots / 8); 12 for the 96-dot head |
| h | number of rows in this block |
| c | length in bytes of the compressed data (u32) |
| data | LZO1X-1 compressed raster, `w * h` bytes once decompressed |

Raster data: 1 bit per dot, most significant bit is the leftmost dot, **1 = black**, rows padded to whole bytes,
top row first (the first row printed is the one that leaves the printer first).

The decoder is a standard LZO1X decompressor; a stream made only of literals is also accepted (a literal-only
stream is `17+n`, the n literal bytes, then the end marker `11 00 00`, for n <= 238; larger n uses a leading
`00` and a zero-run length extension). The app uses liblzo2 `lzo1x_1_compress`.

**Chunking.** The app splits the raster into blocks of whole rows with at most `(720 / w) * w` bytes of
uncompressed data each (60 rows for w = 12), so a long label is a sequence of consecutive blocks. Blocks are
sent back to back with no acknowledgement in between.

## 5. Status reply (17 bytes, HW)

| Offset | Meaning | Sample |
|---|---|---|
| 0 | condition bit field, see below; 0 = ready | `00` |
| 1 | state code (the app reads it as the decimal digits of byte 1 followed by byte 0); always 0 so far | `00` |
| 2 | unknown, constant | `01` |
| 3 | battery percent | `64` (100) |
| 4..5 | auto power-off, seconds (u16) | `84 03` (900) |
| 6 | print density currently set | `4B` (75) |
| 7..8 | unknown | `00 00` |
| 9..11 | LED colour R, G, B | `00 00 00` |
| 12 | slowly changing value, `0x18` before and `0x19` after printing (INF: head temperature in degrees C) | `19` |
| 13 | unknown | `00` |
| 14..16 | marker | `45 4E 44` ("END") |

Byte 0 bits (the app shows one message per bit):

| Bit | Value | Meaning | Confidence |
|---|---|---|---|
| 0 | 0x01 | out of paper | APP (never seen set: lifting the paper required opening the cover, so only bit 4 appeared) |
| 1 | 0x02 | printer too hot | APP |
| 2 | 0x04 | printer too cold | APP |
| 3 | 0x08 | battery needs charging | APP |
| 4 | 0x10 | paper cover open | **HW** (set while the cover was open, cleared when closed) |
| 5 | 0x20 | battery damaged | APP |

### 5.1 Unsolicited status notifications (HW)
Whenever byte 0 changes, the printer sends the ASCII text `pooli_sta=` followed by one byte holding the new
value of status byte 0 (e.g. `70 6F 6F 6C 69 5F 73 74 61 3D 10` when the cover opens, `... 3D 00` when it
closes). These 11-byte messages arrive at any time, including directly in front of or behind a query reply, so a
reader must remove them before parsing a status or info block (`protocol.strip_events`). They are also the way to
learn about a problem during a print job.

## 6. Info reply (143 bytes, HW)

| Offset | Length | Meaning | Sample |
|---|---|---|---|
| 0 | 32 | model string, NUL padded | `HPRT Q2` |
| 32 | 24 | product name | `Qutie` |
| 56 | 32 | device serial number | (device specific) |
| 88 | 3 | firmware version, one byte per component | `01 01 16` (1.1.22) |
| 91 | 3 | board version | `02 00 00` (2.0.0) |
| 94 | 18 | Bluetooth name | `Qutie-xxxx` |
| 112 | 12 | version string | `V4110` |
| 124 | 12 | Bluetooth address as 12 ASCII hex digits | |
| 136 | 4 | `none` (unused field) | `6E 6F 6E 65` |
| 140 | 3 | marker | `45 4E 44` ("END") |

## 7. Geometry and media

- Resolution 203 dpi = 8 dots/mm.
- Head width in the app's model table: 96 dots = 12 mm (12 bytes per row). Labels use the full width; narrower
  images are centred (HW, verified with a 96-dot-wide test image).
- Maximum length per print in the app's model table: 640 rows (80 mm) per feed unit (`maxFeedLengthLineNum`,
  APP; longer jobs are sent as consecutive blocks). A 95 mm label sent as 16 consecutive raster blocks in one
  job printed completely (HW); longer jobs were not tried.
- Print quality on the real printer (density 75, HW): vertical lines 1 dot (0.125 mm) wide print as clean lines,
  5 pt text is readable, and QR codes at 2 and 3 dots per module and a Code 128 barcode at 2 dots per module
  scan with a phone camera. Modules of 1 dot were not tried.
- Blank rows at the start or end of the raster are printed as blank tape. A sender that wants to save tape
  must crop the image itself (the designer trims to the inked columns plus a margin).
- Stock: continuous 12 mm tape was used for all tests. `1D 66` (feed to next label) and the paper-type setting
  for gap/die-cut labels were not exercised.
- Label length for the feed-to-next-label command is `round(mm * 8)` dots (APP, not exercised on hardware).

## 8. Print job sequence (HW for the continuous-feed variant)

The app, per copy:

1. `1D "setc" d` (density, default 75)
2. `1B 61 01` (centre justification; not sent by this implementation, no effect on a full-width image)
3. one or more raster blocks (section 4.5)
4. `1D 66 nL nH` for label stock, or `1B 1B 01 nL nH` for continuous stock (14 mm feed by default)
5. 100 ms pause, then the next copy

Worked example (96 x 2 dots, dotted first row, solid second row, density 75, 14 mm feed), plain bytes:

    1D 73 65 74 63 4B                                    density 75
    1D 76 30 30 0C 00 02 00 1C 00 00 00                  raster block header (w=12, h=2, 28 bytes of data)
    29 AA AA AA AA AA AA AA AA AA AA AA AA               LZO: 0x29 = literal run of 24 bytes (17+24=41)
    FF FF FF FF FF FF FF FF FF FF FF FF                  ... second row
    11 00 00                                             LZO end marker
    1B 1B 01 70 00                                       feed 112 dots

Everything above goes through the XOR of section 3.1 before it is sent.

## 9. Open questions

- Values of the paper-type setting and how gap-label stock is selected and calibrated (no gap labels were
  available to test).
- Meaning of status bytes 1, 2, 7, 8, 13; whether bit 0 (no paper) is raised only when a print is attempted
  (it was not seen when paper was lifted out of the path, only the cover bit).
- Whether the printer reports print completion. The status notifications show condition changes, not progress;
  the practical signal is that queries start being answered again once printing has finished.
- Effect of `1B 61 n` on images narrower than the head (this implementation pads to full width instead).
- Whether status byte 12 really is a head temperature (it moved from 0x18 to 0x19 after printing).

## 10. Notes for implementers on Linux (BlueZ)

These cost time to find out and are not part of the printer protocol itself.

- No pairing is needed, but the adapter must be powered on (`rfkill unblock bluetooth`, `bluetoothctl power on`).
- BlueZ forgets unpaired devices a few minutes after discovery stops, so `bluetoothctl devices` can be empty even
  though the printer is on. Run a short scan (`bluetoothctl --timeout 8 scan on`) first. A second scan started
  while one is running fails with "Failed to start discovery"; wait for the first to finish instead.
- `connect()` on an RFCOMM socket can fail with `Host is down` for the reasons in section 2 and works on the next
  attempt after switching the printer on; reconnecting within about a second of closing a session may be refused
  or reset, so retry a few times.
- To know when a job has really left the machine before closing the socket, do not trust `TIOCOUTQ` on a
  Bluetooth socket: it returns the *free* send-buffer space, not the queued bytes. The queued amount is
  `SO_SNDBUF` minus that value. Closing right after `sendall` can cut a long job short.
- Use `socket.AF_BLUETOOTH` / `BTPROTO_RFCOMM` directly; no `pybluez` or `rfcomm bind` is required, and the
  device does not need to be "connected" in the desktop Bluetooth settings.
- Only one process can talk to the printer at a time (CUPS backend, GUI, CLI and the phone all compete), so tools
  should keep connections short and release them after each job or status check.
