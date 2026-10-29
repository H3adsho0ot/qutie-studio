# Qutie Label Designer

A desktop editor for labels, built with PySide6 (Qt). It prints through the same code path as the CLI
(`qutie.job`), directly over Bluetooth, so no CUPS setup is needed.

    pip install -e '.[gui]'
    qutie-designer [file.qlabel]

## Working with it
- Pick a tool on the left (text, rectangle, ellipse, line, image, QR code, barcode) and click on the label to
  place the element; the tool then returns to "Select".
- Select an element to move it (drag; snaps to 0.5 mm), resize it (handles), or rotate it (round handle above the
  box; hold Shift for 15 degree steps). Arrow keys nudge by 0.5 mm (Shift: 2 mm).
- The right panel has the label settings (length, darkness, copies, feed after each label, print direction) and
  the properties of the selected element. Numeric fields are in millimetres.
- Everything is undoable (Ctrl+Z / Ctrl+Shift+Z), including mouse edits. Repeated edits of one field merge into
  one step.
- View > "As printed" (Ctrl+B) shows the label as pure black and white exactly as it will be printed.
- Printer > Choose printer scans for a Qutie (switch it on first) and remembers it. Print (Ctrl+P) checks the
  printer first: with the cover open, out of paper, or too hot/cold nothing is sent and the reason is shown.
  Warnings (a QR code too small to scan, text that does not fit its box) are listed before printing; labels
  with invalid code data cannot be printed.

## Saving tape: trim and fit
A label rarely fills its whole length, and tape is wasted for every blank millimetre that is printed.
- **Trim blank space when printing** (label panel, on for new labels): the print image is cut down to the inked
  columns plus the margin (default 1 mm each side), so no blank tape is fed before or after the content. The design
  itself is not changed; the "as printed" preview greys out the zones that will be left out, and the panel shows
  `Prints 17.5 mm (saves 22.5 mm)`. Ink is measured on the final black-and-white image, not from element boxes, so
  an oversized text box does not waste tape. Files saved before this option existed keep printing as designed.
- **Fit length to content** (button): moves everything to the start of the label and sets the length to the
  content width plus margins, as one undoable step. It also finds content that sticks out of the label, and the
  content stays pixel-identical (it is shifted by a whole number of dots). The length cannot go below 4 mm.
- The "Feed after" setting is separate: it is the tape pushed out after each label so it can be torn off, and it is
  not trimmed.

## Printer status in the status bar
The bottom right shows the printer's condition with a coloured dot: green `ready · battery 100%`, orange for a
warning (battery low or needs charging, or `not reachable`), red when printing is not possible (cover open, out
of paper, too hot or cold, battery damaged). Hover it for the time of the last check and the auto-off setting.

The printer talks to one device at a time, so the app never keeps a connection open. It makes a short
connect-query-disconnect check, and only while the window is the active window, so a forgotten background window
cannot keep the printer awake: when the window gets focus, after choosing a printer, and then every 30 seconds.
Background checks fail fast (one attempt) and never show a dialog. Printer > "Monitor printer status" turns it
off (remembered). Printer > "Check printer" checks on demand and reports in a message box.

Shortcuts: Ctrl+D duplicate, Delete remove, `]` / `[` bring forward / send backward (Ctrl for front/back),
Ctrl+0 fit, Ctrl +/- zoom, Ctrl+wheel zoom.

## Geometry
The print head is 12 mm (96 dots) wide at 8 dots/mm, so a label is `length x 12 mm`. You design it landscape,
with the length running left to right. When printing, the picture is turned by the "print direction" setting
(270 degrees = clockwise by default, or 90 = counter-clockwise) so its width lies across the head. If a test print
reads upside down along the tape, switch the setting.

## Rendering rules
One scene unit is one printer dot, so the editor, the preview and the printed output share the same pixels:
- Shapes are drawn without anti-aliasing; line widths are rounded to whole dots (minimum 1 dot = 0.125 mm).
- Text is anti-aliased and then thresholded at 50 %, like everything else. Font sizes are in points at 203 dpi.
- QR codes and barcodes are drawn with a whole number of dots per module, centred in their box, with a 2 module
  quiet zone for QR codes. Modules under 2 dots (0.25 mm) are flagged: they print but may not scan reliably. A box
  too small for even 1 dot per module is an error.
- Images are converted to grey, scaled with Lanczos, then either thresholded (0..255) or dithered
  (Floyd-Steinberg). Transparency prints as white.
- Barcode types: Code 128, Code 39, EAN-13 (the check digit is added from 12 digits).

## Verified on a real Qutie (continuous 12 mm stock)
- Print direction 270 degrees (the default) gives text that reads correctly along the tape, not mirrored
  (`examples/orientation-test.qlabel`).
- A 95 mm label (16 raster blocks in one job) prints completely (`examples/print-quality-test.qlabel`).
- Lines 1 dot (0.125 mm) wide print as clean lines; 5 pt text is readable.
- QR codes at 2 and 3 dots per module and a Code 128 barcode at 2 dots per module scan with a phone camera.
  Modules of 1 dot are not tested and stay flagged as risky.
- Trimmed printing (a 40 mm design printed as 17.5 mm with 1 mm margins) comes out with no blank tape before or after.
- Not tested: gap/die-cut labels (the feed-to-next-label command), labels longer than 95 mm.

## File format (`.qlabel`)
UTF-8 JSON, versioned. Images are embedded as base64 PNG so a file is self-contained. Unknown element fields are
ignored; a file with a newer `version` than the program knows is refused.

    {
      "version": 1,
      "label": {"length_mm": 40.0, "density": 75, "copies": 1, "feed_mm": 14.0, "trim": true,
                "trim_margin_mm": 1.0, "rotation": 270},
      "elements": [
        {"kind": "text", "id": "...", "x": 2.0, "y": 2.0, "w": 30.0, "h": 8.0, "rotation": 0.0,
         "text": "Hello", "font": "DejaVu Sans", "size_pt": 12.0, "bold": false, "italic": false,
         "underline": false, "align": "left", "line_spacing": 1.0, "inverse": false},
        {"kind": "shape", "shape": "rect|ellipse|line", "stroke_mm": 0.5, "fill": false, ...},
        {"kind": "image", "png_b64": "...", "threshold": 128, "dither": false, "keep_aspect": true, ...},
        {"kind": "qr", "data": "https://example.org", "ecc": "M", ...},
        {"kind": "barcode", "data": "123456789", "symbology": "code128|code39|ean13", "show_text": true, ...}
      ]
    }

Geometry is in millimetres: `x`, `y` are the top-left of the unrotated box, `rotation` is in degrees clockwise
around the box centre. Elements are listed bottom to top.

## Settings
The chosen printer (name and address) is stored by Qt in the user's configuration directory
(`~/.config/qutie/designer.conf`), never in a label file.

## Modules
`model` (document, no Qt), `codes` (QR/barcode modules), `canvas` (scene, items, view), `commands` (undo),
`render` (scene to print image), `panels` (property panels), `printing` (worker threads), `app` (window).
