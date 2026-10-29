"""Main window of the Qutie label designer."""
import sys
import time
from datetime import datetime
from pathlib import Path

from PIL import Image
from PySide6.QtCore import QEvent, QPointF, QSettings, Qt, QTimer
from PySide6.QtGui import QAction, QActionGroup, QColor, QImage, QKeySequence, QPainter, QPixmap, QUndoStack
from PySide6.QtWidgets import (QApplication, QDialog, QDialogButtonBox, QDockWidget, QFileDialog, QGraphicsPixmapItem,
                               QLabel, QLineEdit, QListWidget, QMainWindow, QMessageBox, QProgressBar,
                               QPushButton, QScrollArea, QToolBar, QVBoxLayout, QWidget)

from .. import protocol
from . import render
from .canvas import LabelScene, LabelView
from .model import DOTS_PER_MM, HEIGHT_MM, MAX_LENGTH_MM, MIN_LENGTH_MM, Barcode, Label, Picture, QRCode, Shape, Text
from .panels import LabelSettings, PropertiesPanel
from .printing import PrinterWorker, ScanWorker, describe, run_in_thread, shutdown

POLL_MS = 30_000            # status refresh interval while the window is active
MIN_POLL_GAP_S = 5.0
LOW_BATTERY = 10
STATUS_COLORS = {"ok": "#2e9e4f", "warn": "#d98e04", "error": "#d64545", "info": ""}
FILE_FILTER = "Qutie labels (*.qlabel);;All files (*)"
TOOLS = (("select", "Select"), ("text", "Text"), ("rect", "Rectangle"), ("ellipse", "Ellipse"), ("line", "Line"),
         ("image", "Image"), ("qr", "QR code"), ("barcode", "Barcode"))


class PreviewOverlay(QGraphicsPixmapItem):
    """The label exactly as it will be printed (1 bit), shown over the design."""

    def paint(self, painter, option, widget=None):
        if self.scene() is not None and not self.scene().printing:
            super().paint(painter, option, widget)


class FindPrintersDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("Choose printer")
        self.setMinimumWidth(420)
        self.mac = ""
        self.found: list[tuple[str, str]] = []
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.list = QListWidget()
        self.manual = QLineEdit()
        self.manual.setPlaceholderText("or type a Bluetooth address, AA:BB:CC:DD:EE:FF")
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        self.rescan = QPushButton("Scan again")
        self.rescan.clicked.connect(self.scan)
        layout = QVBoxLayout(self)
        for widget in (self.status, self.list, self.manual, self.rescan, buttons):
            layout.addWidget(widget)
        self.scan()

    def scan(self):
        self.rescan.setEnabled(False)       # one scan at a time: a second bluetoothctl would be refused
        self.status.setText("Scanning for printers, about 8 seconds (switch the printer on)...")
        self.list.clear()
        self.found = []
        worker = ScanWorker(8)
        self._scan_worker = worker
        worker.found.connect(self._show)                 # bound methods of this dialog: delivered on the GUI thread
        worker.finished.connect(self._scan_done)
        run_in_thread(worker)

    def done(self, result):
        worker = getattr(self, "_scan_worker", None)
        if worker is not None:
            worker.cancel.set()                          # stop bluetoothctl now instead of letting it run on
        super().done(result)

    def _show(self, printers):
        self.found = printers
        for mac, name in printers:
            self.list.addItem(f"{name}  ({mac})")
        if printers:
            self.list.setCurrentRow(0)

    def _scan_done(self, ok: bool, message: str):
        self.rescan.setEnabled(True)
        if not ok:
            self.status.setText(f"Scan failed: {message}")
        elif not self.found:
            self.status.setText("No Qutie found. Switch the printer on (long press the power button), make sure "
                                "no phone is connected to it, then scan again.")
        else:
            self.status.setText(f"{len(self.found)} printer(s) found. Select one.")

    def _accept(self):
        typed = self.manual.text().strip()
        if typed:
            self.mac = typed.upper()
        elif self.list.currentRow() >= 0:
            self.mac = self.found[self.list.currentRow()][0]
        if self.mac:
            self.accept()


class MainWindow(QMainWindow):
    def __init__(self, doc: Label | None = None, path: str | None = None):
        super().__init__()
        self.settings = QSettings("qutie", "designer")
        self.path = path
        self.undo = QUndoStack(self)
        self.scene = LabelScene(doc or Label(), self.undo)
        self.view = LabelView(self.scene)
        self.setCentralWidget(self.view)
        self.tool = "select"
        self.overlay = None
        self._busy = False
        self._job_prints = False
        self._job_image = None
        self._unreachable = False
        self._polling = False
        self._poll_unreachable = False
        self._last_poll = 0.0
        self._preview_timer = QTimer(self, singleShot=True, interval=120)
        self._preview_timer.timeout.connect(self._refresh_extras)

        self._build_actions()
        self._build_menus()
        self._build_toolbar()
        self._build_docks()
        self._build_status()

        self.view.placeRequested.connect(self.place_at)
        self.view.nudgeRequested.connect(self.nudge)
        self.undo.cleanChanged.connect(self._update_title)
        self.undo.indexChanged.connect(self._schedule_preview)
        self.scene.elementsChanged.connect(self._schedule_preview)
        self.scene.labelChanged.connect(self._schedule_preview)
        self.scene.labelChanged.connect(self.view.viewport().update)
        self.scene.selectionChanged.connect(self._update_actions)
        self._update_title()
        self._update_actions()
        self._update_printer_label()
        self._refresh_extras()
        self._poll_timer = QTimer(self, interval=POLL_MS)
        self._poll_timer.timeout.connect(self._poll_printer)
        self._poll_timer.start()
        QTimer.singleShot(1000, self._poll_printer)
        self.resize(1200, 640)
        QTimer.singleShot(0, self.view.zoom_fit)

    # --- construction ---------------------------------------------------------------------
    def _action(self, text, slot, shortcut=None, checkable=False):
        action = QAction(text, self)
        if shortcut:
            action.setShortcut(QKeySequence(shortcut))
        action.setCheckable(checkable)
        action.triggered.connect(slot)
        return action

    def _build_actions(self):
        a = self._action
        self.act_new = a("&New", self.new_label, QKeySequence.New)
        self.act_open = a("&Open...", self.open_label, QKeySequence.Open)
        self.act_save = a("&Save", self.save, QKeySequence.Save)
        self.act_save_as = a("Save &as...", self.save_as, QKeySequence.SaveAs)
        self.act_export = a("&Export PNG...", self.export_png)
        self.act_quit = a("&Quit", self.close, QKeySequence.Quit)
        self.act_undo = self.undo.createUndoAction(self, "&Undo")
        self.act_undo.setShortcut(QKeySequence.Undo)
        self.act_redo = self.undo.createRedoAction(self, "&Redo")
        self.act_redo.setShortcut(QKeySequence.Redo)
        self.act_delete = a("&Delete", self.delete_selected, QKeySequence.Delete)
        self.act_duplicate = a("D&uplicate", self.duplicate_selected, "Ctrl+D")
        self.act_select_all = a("Select &all", lambda: [i.setSelected(True) for i in self.scene.items()],
                                QKeySequence.SelectAll)
        self.act_front = a("Bring to &front", lambda: self._reorder(to=10**6), "Ctrl+]")
        self.act_back = a("Send to &back", lambda: self._reorder(to=0), "Ctrl+[")
        self.act_forward = a("Bring &forward", lambda: self._reorder(delta=1), "]")
        self.act_backward = a("Send &backward", lambda: self._reorder(delta=-1), "[")
        self.act_zoom_in = a("Zoom &in", lambda: self.view.zoom_by(1.25), QKeySequence.ZoomIn)
        self.act_zoom_out = a("Zoom &out", lambda: self.view.zoom_by(0.8), QKeySequence.ZoomOut)
        self.act_zoom_fit = a("&Fit label", self.view.zoom_fit, "Ctrl+0")
        self.act_preview = a("&As printed (black and white)", self._toggle_preview, "Ctrl+B", checkable=True)
        self.act_grid = a("&Grid", self._toggle_grid, checkable=True)
        self.act_grid.setChecked(True)
        self.act_choose = a("&Choose printer...", self.choose_printer)
        self.act_check = a("Check &printer", self.check_printer)
        self.act_monitor = a("&Monitor printer status (while this window is active)", self._toggle_monitor,
                             checkable=True)
        self.act_monitor.setChecked(self.settings.value("printer/monitor", True, type=bool))
        self.act_print = a("&Print", self.print_label, "Ctrl+P")
        self.align_actions = [
            a(text, lambda _=False, m=mode: self.align(m)) for text, mode in (
                ("Align left", "left"), ("Align centre horizontally", "hcenter"), ("Align right", "right"),
                ("Align top", "top"), ("Align centre vertically", "vcenter"), ("Align bottom", "bottom"))]

    def _build_menus(self):
        bar = self.menuBar()
        file_menu = bar.addMenu("&File")
        for action in (self.act_new, self.act_open, self.act_save, self.act_save_as, self.act_export):
            file_menu.addAction(action)
        file_menu.addSeparator()
        file_menu.addAction(self.act_quit)
        edit = bar.addMenu("&Edit")
        for action in (self.act_undo, self.act_redo):
            edit.addAction(action)
        edit.addSeparator()
        for action in (self.act_duplicate, self.act_delete, self.act_select_all):
            edit.addAction(action)
        edit.addSeparator()
        for action in (self.act_front, self.act_forward, self.act_backward, self.act_back):
            edit.addAction(action)
        align = edit.addMenu("A&lign to label")
        for action in self.align_actions:
            align.addAction(action)
        view = bar.addMenu("&View")
        for action in (self.act_zoom_in, self.act_zoom_out, self.act_zoom_fit, self.act_preview, self.act_grid):
            view.addAction(action)
        printer = bar.addMenu("&Printer")
        for action in (self.act_choose, self.act_check, self.act_monitor, self.act_print):
            printer.addAction(action)

    def _build_toolbar(self):
        toolbar = QToolBar("Tools", self)
        toolbar.setOrientation(Qt.Vertical)
        toolbar.setMovable(False)
        self.addToolBar(Qt.LeftToolBarArea, toolbar)
        group = QActionGroup(self)
        group.setExclusive(True)
        self.tool_actions = {}
        for key, text in TOOLS:
            action = QAction(text, self)
            action.setCheckable(True)
            action.setToolTip(f"{text} - click on the label to add" if key != "select" else "Select and move")
            action.triggered.connect(lambda _=False, k=key: self.set_tool(k))
            group.addAction(action)
            toolbar.addAction(action)
            self.tool_actions[key] = action
        self.tool_actions["select"].setChecked(True)
        toolbar.setToolButtonStyle(Qt.ToolButtonTextOnly)
        toolbar.addSeparator()
        toolbar.addAction(self.act_print)

    def _build_docks(self):
        self.label_settings = LabelSettings(self.scene)
        self.properties = PropertiesPanel(self.scene)
        self.properties.replaceImageRequested.connect(self.replace_image)
        self.label_settings.fitRequested.connect(self.fit_length_to_content)
        host = QWidget()
        column = QVBoxLayout(host)
        column.addWidget(self.label_settings)
        column.addWidget(self.properties, 1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(host)
        dock = QDockWidget("Properties", self)
        dock.setWidget(scroll)
        dock.setMinimumWidth(300)
        self.addDockWidget(Qt.RightDockWidgetArea, dock)

    def _build_status(self):
        self.printer_label = QLabel()
        self.progress = QProgressBar()
        self.progress.setMaximumWidth(140)
        self.progress.hide()
        self.statusBar().addPermanentWidget(self.progress)
        self.statusBar().addPermanentWidget(self.printer_label)

    # --- tools and placing ----------------------------------------------------------------
    def set_tool(self, key: str):
        self.tool = key
        placing = key != "select"
        self.view.place_mode = placing
        self.view.setDragMode(self.view.DragMode.NoDrag if placing else self.view.DragMode.RubberBandDrag)
        self.view.viewport().setCursor(Qt.CrossCursor if placing else Qt.ArrowCursor)
        self.statusBar().showMessage("Click on the label to place it" if placing else "", 4000)

    def place_at(self, scene_pos: QPointF):
        tool = self.tool
        self.tool_actions["select"].setChecked(True)
        self.set_tool("select")
        length = self.scene.doc.length_mm
        factories = {
            "text": lambda: Text(w=min(30.0, length - 2), h=8.0),
            "rect": lambda: Shape(shape="rect", w=min(15.0, length - 2), h=8.0),
            "ellipse": lambda: Shape(shape="ellipse", w=min(12.0, length - 2), h=8.0),
            "line": lambda: Shape(shape="line", w=min(20.0, length - 2), h=1.5, stroke_mm=0.5),
            "qr": lambda: QRCode(w=10.0, h=10.0),
            "barcode": lambda: Barcode(w=min(30.0, length - 2), h=9.0),
        }
        if tool == "image":
            element = self._image_from_dialog()
        else:
            element = factories[tool]()
        if element is None:
            return
        element.x = min(max(0.0, round(scene_pos.x() / 8 * 2) / 2), max(0.0, length - element.w))
        element.y = min(max(0.0, round(scene_pos.y() / 8 * 2) / 2), max(0.0, HEIGHT_MM - element.h))
        self.scene.add_new(element)

    def _image_from_dialog(self) -> Picture | None:
        path, _ = QFileDialog.getOpenFileName(self, "Add image", "", "Images (*.png *.jpg *.jpeg *.bmp *.gif *.webp)")
        if not path:
            return None
        try:
            image = Image.open(path)
            image.load()
        except Exception as exc:
            QMessageBox.warning(self, "Image", f"Cannot open this image: {exc}")
            return None
        picture = Picture()
        picture.set_image(image)
        height = min(10.0, HEIGHT_MM - 2)
        picture.h = height
        picture.w = max(1.0, min(self.scene.doc.length_mm - 2, height * image.width / image.height))
        return picture

    def replace_image(self):
        ids = self.scene.selected_ids()
        picture = self._image_from_dialog() if ids else None
        if picture is not None:
            self.scene.edit(ids[:1], {"png_b64": picture.png_b64}, "Replace image")

    # --- editing commands -----------------------------------------------------------------
    def delete_selected(self):
        self.scene.delete_selected()

    def duplicate_selected(self):
        ids = self.scene.selected_ids()
        if not ids:
            return
        clones = []
        with self.scene.macro("Duplicate"):
            for element_id in ids:
                clone = self.scene.doc.find(element_id).copy()
                clone.x, clone.y = clone.x + 2, clone.y + 1
                self.scene.add_new(clone)
                clones.append(clone.id)
        self.scene.clearSelection()
        for element_id in clones:
            self.scene.item_for(element_id).setSelected(True)

    def nudge(self, dx: float, dy: float):
        for element_id in self.scene.selected_ids():
            element = self.scene.doc.find(element_id)
            self.scene.edit([element_id], {"x": element.x + dx, "y": element.y + dy}, "Move", "nudge")

    def _reorder(self, delta=None, to=None):
        for element_id in self.scene.selected_ids():
            self.scene.change_order(element_id, delta=delta, to=to)

    def align(self, mode: str):
        ids = self.scene.selected_ids()
        label_w, label_h = self.scene.doc.length_mm, HEIGHT_MM
        with self.scene.macro("Align"):
            for element_id in ids:
                item = self.scene.item_for(element_id)
                box = item.mapRectToScene(0, 0, item.width, item.height)      # bounds of the rotated box
                x0, y0, x1, y1 = (box.left() / 8, box.top() / 8, box.right() / 8, box.bottom() / 8)
                element = self.scene.doc.find(element_id)
                dx = {"left": -x0, "right": label_w - x1, "hcenter": (label_w - (x1 - x0)) / 2 - x0}.get(mode, 0)
                dy = {"top": -y0, "bottom": label_h - y1, "vcenter": (label_h - (y1 - y0)) / 2 - y0}.get(mode, 0)
                self.scene.edit([element_id], {"x": element.x + dx, "y": element.y + dy}, "Align")

    def _update_actions(self):
        has = bool(self.scene.selected_ids())
        for action in (self.act_delete, self.act_duplicate, self.act_front, self.act_back, self.act_forward,
                       self.act_backward, *self.align_actions):
            action.setEnabled(has)

    # --- files ----------------------------------------------------------------------------
    def _update_title(self):
        name = Path(self.path).name if self.path else "Untitled"
        self.setWindowTitle(f"{name}{'' if self.undo.isClean() else ' *'} - Qutie Label Designer")

    def _confirm_discard(self) -> bool:
        if self.undo.isClean():
            return True
        answer = QMessageBox.question(self, "Unsaved changes", "Save changes to this label first?",
                                      QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel)
        if answer == QMessageBox.Save:
            return self.save()
        return answer == QMessageBox.Discard

    def _load(self, doc: Label, path: str | None):
        self.scene.doc = doc
        self.scene.rebuild()
        self.overlay = None
        self.undo.clear()
        self.undo.setClean()
        self.path = path
        self.label_settings.load()
        self.properties.refresh()
        self._update_title()
        self._refresh_extras()
        self.view.zoom_fit()

    def new_label(self):
        if self._confirm_discard():
            self._load(Label(), None)

    def open_label(self, path: str | None = None):
        if not self._confirm_discard():
            return
        path = path or QFileDialog.getOpenFileName(self, "Open label", "", FILE_FILTER)[0]
        if not path:
            return
        try:
            doc = Label.from_json(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError, KeyError, TypeError) as exc:
            QMessageBox.warning(self, "Open label", f"Cannot open this file: {exc}")
            return
        self._load(doc, path)

    def save(self) -> bool:
        if not self.path:
            return self.save_as()
        try:
            Path(self.path).write_text(self.scene.doc.to_json(), encoding="utf-8")
        except OSError as exc:
            QMessageBox.warning(self, "Save label", f"Cannot save: {exc}")
            return False
        self.undo.setClean()
        self._update_title()
        return True

    def save_as(self) -> bool:
        path, _ = QFileDialog.getSaveFileName(self, "Save label", self.path or "label.qlabel", FILE_FILTER)
        if not path:
            return False
        self.path = path if path.endswith(".qlabel") else path + ".qlabel"
        return self.save()

    def export_png(self):
        path, _ = QFileDialog.getSaveFileName(self, "Export PNG", "label.png", "PNG (*.png)")
        if path:
            render.threshold(self.printable_image()).convert("1").save(path)

    def closeEvent(self, event):
        if self._busy:
            QMessageBox.information(self, "Printer", "The printer is busy; wait for it to finish.")
            event.ignore()
        elif self._confirm_discard():
            event.accept()
        else:
            event.ignore()

    # --- preview --------------------------------------------------------------------------
    def _toggle_grid(self):
        self.view.show_grid = self.act_grid.isChecked()
        self.view.viewport().update()

    def _toggle_preview(self):
        self._update_preview()

    def _schedule_preview(self, *_):
        self._preview_timer.start()          # debounced; cheap when neither preview nor trimming is on

    def _refresh_extras(self):
        self._update_preview()
        self._update_trim_info()

    # --- trimming blank tape ----------------------------------------------------------------
    def _margin_dots(self) -> int:
        return round(self.scene.doc.trim_margin_mm * DOTS_PER_MM)

    def printable_image(self):
        """The label as it will be printed: the whole canvas, or only the inked part when trimming is on."""
        image = render.render_scene(self.scene)
        return render.trim_to_content(image, self._margin_dots()) if self.scene.doc.trim else image

    def _update_trim_info(self):
        doc = self.scene.doc
        if not doc.trim:
            self.label_settings.info.setText(f"Prints the whole {doc.length_mm:g} mm.")
            return
        extent = render.ink_extent(render.render_scene(self.scene))
        if extent is None:
            self.label_settings.info.setText("Nothing to print yet.")
            return
        printed = (extent[1] - extent[0] + 2 * self._margin_dots()) / DOTS_PER_MM
        saved = max(0.0, doc.length_mm - printed)
        self.label_settings.info.setText(f"Prints {printed:.1f} mm" + (f" (saves {saved:.1f} mm)." if saved else "."))

    def fit_length_to_content(self):
        """Move the content to the start and set the label length to its width plus margins, as one undo step."""
        extent = render.content_extent(self.scene)
        if extent is None:
            self.statusBar().showMessage("Nothing to fit: the label is empty.", 4000)
            return
        left, right = extent
        margin = self._margin_dots()
        shift_mm = (left - margin) / DOTS_PER_MM
        length = min(MAX_LENGTH_MM, max(MIN_LENGTH_MM, (right - left + 2 * margin) / DOTS_PER_MM))
        with self.scene.macro("Fit length to content"):
            for element in list(self.scene.doc.elements):
                self.scene.edit([element.id], {"x": element.x - shift_mm}, "Fit")
            self.scene.edit_label(length_mm=length)
        self.statusBar().showMessage(f"Label length set to {length:g} mm.", 4000)

    def _update_preview(self):
        on = self.act_preview.isChecked()
        if self.overlay is not None:
            self.scene.removeItem(self.overlay)
            self.overlay = None
        if not on:
            return
        bw = render.threshold(render.render_scene(self.scene)).convert("L")
        qimage = QImage(bw.tobytes(), bw.width, bw.height, bw.width, QImage.Format_Grayscale8).copy()
        pixmap = QPixmap.fromImage(qimage)
        extent = render.ink_extent(bw) if self.scene.doc.trim else None
        if extent is not None:                       # grey out what trimming will not print
            keep_from = max(0, extent[0] - self._margin_dots())
            keep_to = min(bw.width, extent[1] + self._margin_dots())
            painter = QPainter(pixmap)
            shade = QColor(110, 110, 130, 150)
            painter.fillRect(0, 0, keep_from, bw.height, shade)
            painter.fillRect(keep_to, 0, bw.width - keep_to, bw.height, shade)
            painter.end()
        self.overlay = PreviewOverlay(pixmap)
        self.overlay.setZValue(1_000_000)
        self.overlay.setAcceptedMouseButtons(Qt.NoButton)
        self.scene.addItem(self.overlay)

    # --- printer --------------------------------------------------------------------------
    def printer_mac(self) -> str:
        return self.settings.value("printer/mac", "", type=str)

    def _printer_name(self) -> str:
        return self.settings.value("printer/name", "", type=str) or "printer"

    def _show_printer(self, text: str, level: str = "info", tooltip: str = ""):
        self.printer_label.setText(text)
        self.printer_label.setToolTip(tooltip)
        color = STATUS_COLORS[level]
        self.printer_label.setStyleSheet(f"color: {color}; font-weight: bold" if color else "")

    def _update_printer_label(self):
        if not self.printer_mac():
            self._show_printer("Printer: none chosen (Printer menu)", "info")
        else:
            self._show_printer(f"\u25cf {self._printer_name()}  not checked yet", "info",
                               "Printer > Check printer refreshes the status")

    def _show_status(self, status: protocol.Status):
        """Show the printer condition in the status bar: green ready, orange warning, red cannot print."""
        low = status.battery <= LOW_BATTERY or bool(status.flags & 0x08)
        if not status.can_print:
            level, state = "error", ", ".join(status.problems)
        elif status.problems or low:
            level, state = "warn", ", ".join(status.problems) or "ready"
        else:
            level, state = "ok", "ready"
        battery = f"battery {status.battery}%" + (" - charge soon" if low and not status.flags & 0x08 else "")
        stamp = datetime.now().strftime("%H:%M:%S")
        self._show_printer(f"\u25cf {self._printer_name()}  {state} \u00b7 {battery}", level,
                           f"Checked at {stamp}. Auto-off after {status.auto_off_seconds // 60} min.")

    def _show_unreachable(self):
        self._show_printer(f"\u25cf {self._printer_name()}  not reachable", "warn",
                           "Switch the printer on (long-press the power button) and keep it close; "
                           "make sure no phone is connected to it.")

    # --- background status monitoring -------------------------------------------------------
    def _toggle_monitor(self):
        self.settings.setValue("printer/monitor", self.act_monitor.isChecked())
        if self.act_monitor.isChecked():
            self._poll_printer(force=True)

    def _should_poll(self) -> bool:
        return bool(self.printer_mac() and self.act_monitor.isChecked() and not self._busy
                    and not self._polling and self.isActiveWindow())

    def _poll_printer(self, force: bool = False):
        """Quiet status check: a short connection that only updates the status bar, never shows a dialog."""
        if not self._should_poll():
            return
        if not force and time.monotonic() - self._last_poll < MIN_POLL_GAP_S:
            return
        self._last_poll = time.monotonic()
        worker = PrinterWorker(self.printer_mac(), attempts=1)
        worker.status.connect(self._on_printer_status)
        worker.unreachable.connect(self._on_poll_unreachable)
        worker.finished.connect(self._on_poll_finished)
        self._polling, self._poll_unreachable = True, False
        run_in_thread(worker)

    def _on_poll_unreachable(self):
        self._poll_unreachable = True
        self._show_unreachable()

    def _on_poll_finished(self, ok: bool, message: str):
        self._polling = False

    def changeEvent(self, event):
        if event.type() == QEvent.ActivationChange and self.isActiveWindow():
            QTimer.singleShot(500, self._poll_printer)
        super().changeEvent(event)

    def choose_printer(self) -> str:
        dialog = FindPrintersDialog(self)
        if dialog.exec() != QDialog.Accepted:
            return ""
        names = dict(dialog.found)
        self.settings.setValue("printer/mac", dialog.mac)
        self.settings.setValue("printer/name", names.get(dialog.mac, ""))
        self._update_printer_label()
        self._poll_printer(force=True)
        return dialog.mac

    def check_printer(self):
        self._run_printer_job(None)

    def print_label(self):
        problems = self.scene.problems()
        if problems:
            QMessageBox.warning(self, "Cannot print", "Fix these first:\n\n" + "\n".join(problems))
            return
        warnings = self.scene.warnings()
        if warnings:
            answer = QMessageBox.question(self, "Print anyway?", "\n".join(warnings) + "\n\nPrint anyway?")
            if answer != QMessageBox.Yes:
                return
        if not self.scene.doc.elements:
            QMessageBox.information(self, "Print", "The label is empty.")
            return
        self._run_printer_job(self.printable_image())

    def _run_printer_job(self, image):
        if self._busy:
            return
        if self._polling:                  # the printer takes one connection at a time: wait for the status check
            QTimer.singleShot(300, lambda: self._run_printer_job(image))
            return
        mac = self.printer_mac() or self.choose_printer()
        if not mac:
            return
        doc = self.scene.doc
        worker = PrinterWorker(mac, image, copies=doc.copies, density=doc.density, rotation=doc.rotation,
                               feed_mm=doc.feed_mm)
        worker.status.connect(self._on_printer_status)   # bound methods: run on the GUI thread
        worker.progress.connect(self._on_progress)
        worker.finished.connect(self._job_done)
        worker.unreachable.connect(self._on_unreachable)
        self._job_prints = image is not None
        self._job_image = image
        self._unreachable = False
        self._busy = True
        self.act_print.setEnabled(False)
        self.act_check.setEnabled(False)
        self.progress.setRange(0, 0)
        self.progress.show()
        self.statusBar().showMessage("Connecting to the printer..." if image is not None
                                     else "Checking printer...")
        run_in_thread(worker)

    def _on_unreachable(self):
        self._unreachable = True

    def _ask_rescan(self, message: str) -> bool:
        box = QMessageBox(QMessageBox.Warning, "Printer not reachable", message, QMessageBox.NoButton, self)
        scan = box.addButton("Scan for printers...", QMessageBox.AcceptRole)
        box.addButton("Close", QMessageBox.RejectRole)
        box.exec()
        return box.clickedButton() is scan

    def _on_printer_status(self, status):
        self._show_status(status)

    def _on_progress(self, done: int, total: int):
        self.progress.setRange(0, total)
        self.progress.setValue(done)

    def _job_done(self, ok: bool, message: str):
        printing = self._job_prints
        self._busy = False
        self.act_print.setEnabled(True)
        self.act_check.setEnabled(True)
        self.progress.hide()
        if self._unreachable:
            self._show_unreachable()
        self.statusBar().showMessage("Printer not reachable" if self._unreachable else message, 8000)
        if not ok and self._unreachable:
            if self._ask_rescan(message) and self.choose_printer():
                QTimer.singleShot(0, lambda: self._run_printer_job(self._job_image))     # try again with the new choice
        elif not ok:
            QMessageBox.warning(self, "Printer" if not printing else "Print failed", message)
        elif not printing:
            QMessageBox.information(self, "Printer", message)


def main(argv=None):
    argv = list(sys.argv if argv is None else argv)
    app = QApplication(argv)
    app.setApplicationName("Qutie Label Designer")
    app.aboutToQuit.connect(shutdown)
    window = MainWindow()
    if len(argv) > 1:
        window.open_label(argv[1])
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
