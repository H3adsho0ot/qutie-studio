# Third-party notices

Bundled third-party software keeps its original copyright notices and licenses.

| Component | Version / revision | License | Included files |
| --- | --- | --- | --- |
| [Qutie protocol and Linux driver](https://github.com/AnonTester/prt-qutie-label-printer) | `e6e3f9c595bc4cd3e08a6886054b8b24d3d9e2d3` | MIT, copyright 2026 AnonTester | [`vendor/qutie-linux/`](vendor/qutie-linux/), including [`LICENSE`](vendor/qutie-linux/LICENSE) |
| [Konva](https://github.com/konvajs/konva) | 9.3.22 | MIT | [`static/vendor/konva.min.js`](static/vendor/konva.min.js), [`KONVA-LICENSE.txt`](static/vendor/KONVA-LICENSE.txt) |
| [Noto Sans](https://github.com/google/fonts/tree/main/ofl/notosans) | Variable upright and italic fonts | SIL Open Font License 1.1 | [`NotoSans.ttf`](static/fonts/NotoSans.ttf), [`NotoSans-Italic.ttf`](static/fonts/NotoSans-Italic.ttf), [`OFL.txt`](static/fonts/OFL.txt) |

Font source Git blob IDs: upright `75575046c015ff623a848096a15779867ba71453`,
italic `429692da4c3f2751f50bdfab7d0fdb3639717524` (Google Fonts, `ofl/notosans`).

The Qutie reference sources are included without code modifications. The application
adds its own Windows USB transport in `printer.py`; the upstream reference's
charge-only USB statement does not describe the Q2 device tested with this app.

Python dependencies are installed separately from `requirements.txt` and retain
their respective upstream licenses. The application code has no separately granted
license at this time; public availability does not change third-party license terms.
