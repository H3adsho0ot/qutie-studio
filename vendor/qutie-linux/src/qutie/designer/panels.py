"""Side panels: label settings and the properties of the selected element."""
from PySide6.QtCore import QSignalBlocker, Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox, QFontComboBox, QFormLayout, QGroupBox, QLabel,
                               QLineEdit, QPlainTextEdit, QPushButton, QSpinBox, QStackedWidget, QVBoxLayout, QWidget)

from . import codes
from .canvas import LabelScene
from .model import MAX_LENGTH_MM, MIN_LENGTH_MM, Barcode, Picture, QRCode, Shape, Text


def dspin(low, high, step=0.5, decimals=1, suffix=""):
    box = QDoubleSpinBox()
    box.setRange(low, high)
    box.setSingleStep(step)
    box.setDecimals(decimals)
    box.setSuffix(suffix)
    box.setKeyboardTracking(False)
    return box


def ispin(low, high, suffix=""):
    box = QSpinBox()
    box.setRange(low, high)
    box.setSuffix(suffix)
    box.setKeyboardTracking(False)
    return box


def combo(items: dict):
    box = QComboBox()
    for value, label in items.items():
        box.addItem(label, value)
    return box


class LabelSettings(QGroupBox):
    """Length, darkness, copies, feed and print direction of the whole label."""

    fitRequested = Signal()

    def __init__(self, scene: LabelScene):
        super().__init__("Label")
        self.scene = scene
        self.length = dspin(MIN_LENGTH_MM, MAX_LENGTH_MM, 1.0, 1, " mm")
        self.density = ispin(1, 255)
        self.copies = ispin(1, 99)
        self.feed = dspin(0, 60, 1.0, 0, " mm")
        self.rotation = combo({270: "clockwise (270°)", 90: "counter-clockwise (90°)"})
        self.rotation.setToolTip("Landscape design is turned by this angle before printing. If text comes out "
                                 "upside down or mirrored along the tape, switch it.")
        self.trim = QCheckBox("Trim blank space when printing")
        self.trim.setToolTip("Print only the inked part of the label plus the margin below, so no tape is wasted "
                             "before or after it. The design itself is not changed.")
        self.margin = dspin(0, 10, 0.5, 1, " mm")
        self.info = QLabel()
        self.info.setWordWrap(True)
        self.fit = QPushButton("Fit length to content")
        self.fit.setToolTip("Move the content to the start of the label and set the length to match (undoable).")
        self.fit.clicked.connect(self.fitRequested)
        form = QFormLayout(self)
        form.addRow("Length", self.length)
        form.addRow("Darkness", self.density)
        form.addRow("Copies", self.copies)
        form.addRow("Feed after", self.feed)
        form.addRow("Print direction", self.rotation)
        form.addRow(self.trim)
        form.addRow("Margin", self.margin)
        form.addRow(self.info)
        form.addRow(self.fit)
        self.length.valueChanged.connect(lambda v: scene.edit_label(length_mm=v))
        self.density.valueChanged.connect(lambda v: scene.edit_label(density=v))
        self.copies.valueChanged.connect(lambda v: scene.edit_label(copies=v))
        self.feed.valueChanged.connect(lambda v: scene.edit_label(feed_mm=v))
        self.rotation.currentIndexChanged.connect(lambda _: scene.edit_label(rotation=self.rotation.currentData()))
        self.trim.toggled.connect(lambda v: scene.edit_label(trim=v))
        self.margin.valueChanged.connect(lambda v: scene.edit_label(trim_margin_mm=v))
        scene.labelChanged.connect(self.load)
        self.load()

    def load(self):
        doc = self.scene.doc
        for widget, value in ((self.length, doc.length_mm), (self.density, doc.density), (self.copies, doc.copies),
                              (self.feed, doc.feed_mm)):
            with QSignalBlocker(widget):
                widget.setValue(value)
        with QSignalBlocker(self.trim):
            self.trim.setChecked(doc.trim)
        with QSignalBlocker(self.margin):
            self.margin.setValue(doc.trim_margin_mm)
        self.margin.setEnabled(doc.trim)
        with QSignalBlocker(self.rotation):
            self.rotation.setCurrentIndex(max(0, self.rotation.findData(doc.rotation)))


class PropertiesPanel(QWidget):
    replaceImageRequested = Signal()

    def __init__(self, scene: LabelScene):
        super().__init__()
        self.scene = scene
        self.ids: list[str] = []
        self.title = QLabel()
        self.title.setStyleSheet("font-weight: bold")

        # common geometry
        self.geometry = QGroupBox("Position and size")
        geo = QFormLayout(self.geometry)
        self.x, self.y = dspin(-50, 400), dspin(-50, 400)
        self.w, self.h = dspin(1, 400), dspin(1, 100)
        self.rot = dspin(0, 359, 5, 0, "°")
        for label, widget, field in (("X", self.x, "x"), ("Y", self.y, "y"), ("Width", self.w, "w"),
                                     ("Height", self.h, "h"), ("Rotation", self.rot, "rotation")):
            geo.addRow(label, widget)
            widget.valueChanged.connect(lambda v, f=field: self._geometry_edited(f, v))

        # per-type pages
        self.stack = QStackedWidget()
        self.pages = {}
        for kind, builder in (("text", self._text_page), ("shape", self._shape_page), ("image", self._image_page),
                              ("qr", self._qr_page), ("barcode", self._barcode_page)):
            page = QWidget()
            builder(QFormLayout(page))
            self.pages[kind] = page
            self.stack.addWidget(page)
        self.empty = QLabel("Select an element, or pick a tool on the left and click on the label.")
        self.empty.setWordWrap(True)
        self.empty.setAlignment(Qt.AlignTop)
        self.stack.addWidget(self.empty)

        layout = QVBoxLayout(self)
        layout.addWidget(self.title)
        layout.addWidget(self.geometry)
        layout.addWidget(self.stack, 1)
        scene.selectionChanged.connect(self.refresh)
        scene.elementsChanged.connect(self.refresh)
        self.refresh()

    # --- building the pages ---------------------------------------------------------------
    def _bind(self, widget, signal, field, read):
        signal.connect(lambda *_: self._edit(field, read(widget)))

    def _text_page(self, form):
        self.t_text = QPlainTextEdit()
        self.t_text.setFixedHeight(70)
        self.t_font = QFontComboBox()
        self.t_size = dspin(3, 96, 0.5, 1, " pt")
        self.t_bold, self.t_italic = QCheckBox("Bold"), QCheckBox("Italic")
        self.t_underline, self.t_inverse = QCheckBox("Underline"), QCheckBox("White on black")
        self.t_align = combo({"left": "Left", "center": "Centre", "right": "Right"})
        self.t_spacing = dspin(0.5, 3.0, 0.1, 1)
        for label, widget in (("Text", self.t_text), ("Font", self.t_font), ("Size", self.t_size),
                              ("", self.t_bold), ("", self.t_italic), ("", self.t_underline),
                              ("Align", self.t_align), ("Line spacing", self.t_spacing), ("", self.t_inverse)):
            form.addRow(label, widget)
        self._bind(self.t_text, self.t_text.textChanged, "text", lambda w: w.toPlainText())
        self._bind(self.t_font, self.t_font.currentFontChanged, "font", lambda w: w.currentFont().family())
        self._bind(self.t_size, self.t_size.valueChanged, "size_pt", lambda w: w.value())
        self._bind(self.t_bold, self.t_bold.toggled, "bold", lambda w: w.isChecked())
        self._bind(self.t_italic, self.t_italic.toggled, "italic", lambda w: w.isChecked())
        self._bind(self.t_underline, self.t_underline.toggled, "underline", lambda w: w.isChecked())
        self._bind(self.t_inverse, self.t_inverse.toggled, "inverse", lambda w: w.isChecked())
        self._bind(self.t_align, self.t_align.currentIndexChanged, "align", lambda w: w.currentData())
        self._bind(self.t_spacing, self.t_spacing.valueChanged, "line_spacing", lambda w: w.value())

    def _shape_page(self, form):
        self.s_shape = combo({"rect": "Rectangle", "ellipse": "Ellipse", "line": "Line"})
        self.s_stroke = dspin(0.1, 6, 0.1, 1, " mm")
        self.s_fill = QCheckBox("Filled")
        form.addRow("Shape", self.s_shape)
        form.addRow("Line width", self.s_stroke)
        form.addRow("", self.s_fill)
        self._bind(self.s_shape, self.s_shape.currentIndexChanged, "shape", lambda w: w.currentData())
        self._bind(self.s_stroke, self.s_stroke.valueChanged, "stroke_mm", lambda w: w.value())
        self._bind(self.s_fill, self.s_fill.toggled, "fill", lambda w: w.isChecked())

    def _image_page(self, form):
        self.i_threshold = ispin(0, 255)
        self.i_dither = QCheckBox("Dither (photos)")
        self.i_aspect = QCheckBox("Keep aspect ratio")
        replace = QPushButton("Replace image...")
        replace.clicked.connect(self.replaceImageRequested)
        form.addRow("Threshold", self.i_threshold)
        form.addRow("", self.i_dither)
        form.addRow("", self.i_aspect)
        form.addRow("", replace)
        self._bind(self.i_threshold, self.i_threshold.valueChanged, "threshold", lambda w: w.value())
        self._bind(self.i_dither, self.i_dither.toggled, "dither", lambda w: w.isChecked())
        self._bind(self.i_aspect, self.i_aspect.toggled, "keep_aspect", lambda w: w.isChecked())

    def _qr_page(self, form):
        self.q_data = QPlainTextEdit()
        self.q_data.setFixedHeight(70)
        self.q_ecc = combo({"L": "L (7%)", "M": "M (15%)", "Q": "Q (25%)", "H": "H (30%)"})
        self.q_error = QLabel()
        self.q_error.setStyleSheet("color: #c00")
        self.q_error.setWordWrap(True)
        form.addRow("Content", self.q_data)
        form.addRow("Error correction", self.q_ecc)
        form.addRow("", self.q_error)
        self._bind(self.q_data, self.q_data.textChanged, "data", lambda w: w.toPlainText())
        self._bind(self.q_ecc, self.q_ecc.currentIndexChanged, "ecc", lambda w: w.currentData())

    def _barcode_page(self, form):
        self.b_data = QLineEdit()
        self.b_type = combo(codes.SYMBOLOGIES)
        self.b_text = QCheckBox("Print the number under the bars")
        self.b_error = QLabel()
        self.b_error.setStyleSheet("color: #c00")
        self.b_error.setWordWrap(True)
        form.addRow("Data", self.b_data)
        form.addRow("Type", self.b_type)
        form.addRow("", self.b_text)
        form.addRow("", self.b_error)
        self._bind(self.b_data, self.b_data.textChanged, "data", lambda w: w.text())
        self._bind(self.b_type, self.b_type.currentIndexChanged, "symbology", lambda w: w.currentData())
        self._bind(self.b_text, self.b_text.toggled, "show_text", lambda w: w.isChecked())

    # --- editing --------------------------------------------------------------------------
    def _edit(self, field, value):
        if not self.ids or self._loading:
            return
        self.scene.edit(self.ids, {field: value}, f"Edit {field}", field)

    def _geometry_edited(self, field, value):
        if not self.ids or self._loading:
            return
        changes = {field: value}
        if len(self.ids) == 1 and isinstance(self.scene.doc.find(self.ids[0]), QRCode) and field in ("w", "h"):
            changes = {"w": value, "h": value}
        self.scene.edit(self.ids, changes, f"Edit {field}", field)

    _loading = False

    def refresh(self):
        self.ids = self.scene.selected_ids()
        self._loading = True
        try:
            self._load()
        finally:
            self._loading = False

    def _load(self):
        count = len(self.ids)
        self.geometry.setVisible(count == 1)
        if count != 1:
            self.title.setText("Nothing selected" if count == 0 else f"{count} elements selected")
            self.stack.setCurrentWidget(self.empty)
            self.empty.setText("Select an element, or pick a tool on the left and click on the label."
                               if count == 0 else "Use the Edit menu to align, duplicate or delete.")
            return
        element = self.scene.doc.find(self.ids[0])
        self.title.setText(element.kind.capitalize())
        for widget, value in ((self.x, element.x), (self.y, element.y), (self.w, element.w), (self.h, element.h),
                              (self.rot, element.rotation)):
            with QSignalBlocker(widget):
                widget.setValue(value)
        self.stack.setCurrentWidget(self.pages[element.kind])
        item = self.scene.item_for(element.id)
        if isinstance(element, Text):
            self._set_text(self.t_text, element.text)
            self._set(self.t_font, lambda w: w.setCurrentFont(QFont(element.font)))
            self._set(self.t_size, lambda w: w.setValue(element.size_pt))
            self._set(self.t_bold, lambda w: w.setChecked(element.bold))
            self._set(self.t_italic, lambda w: w.setChecked(element.italic))
            self._set(self.t_underline, lambda w: w.setChecked(element.underline))
            self._set(self.t_inverse, lambda w: w.setChecked(element.inverse))
            self._set(self.t_align, lambda w: w.setCurrentIndex(w.findData(element.align)))
            self._set(self.t_spacing, lambda w: w.setValue(element.line_spacing))
        elif isinstance(element, Shape):
            self._set(self.s_shape, lambda w: w.setCurrentIndex(w.findData(element.shape)))
            self._set(self.s_stroke, lambda w: w.setValue(element.stroke_mm))
            self._set(self.s_fill, lambda w: w.setChecked(element.fill))
        elif isinstance(element, Picture):
            self._set(self.i_threshold, lambda w: w.setValue(element.threshold))
            self._set(self.i_dither, lambda w: w.setChecked(element.dither))
            self._set(self.i_aspect, lambda w: w.setChecked(element.keep_aspect))
        elif isinstance(element, QRCode):
            self._set_text(self.q_data, element.data)
            self._set(self.q_ecc, lambda w: w.setCurrentIndex(w.findData(element.ecc)))
            self.q_error.setText(item.error or item.warning or "")
        elif isinstance(element, Barcode):
            self._set(self.b_data, lambda w: w.setText(element.data) if w.text() != element.data else None)
            self._set(self.b_type, lambda w: w.setCurrentIndex(w.findData(element.symbology)))
            self._set(self.b_text, lambda w: w.setChecked(element.show_text))
            self.b_error.setText(item.error or item.warning or "")

    @staticmethod
    def _set(widget, apply):
        with QSignalBlocker(widget):
            apply(widget)

    @staticmethod
    def _set_text(widget, value):
        if widget.toPlainText() != value:
            with QSignalBlocker(widget):
                widget.setPlainText(value)
