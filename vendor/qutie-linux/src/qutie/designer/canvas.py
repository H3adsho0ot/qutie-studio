"""Graphics scene, item classes and view for the label canvas. One scene unit = one printer dot."""
import math
from contextlib import contextmanager

from PIL import Image
from PySide6.QtCore import QPointF, QRect, QRectF, Qt, Signal
from PySide6.QtGui import (QAbstractTextDocumentLayout, QBrush, QColor, QFont, QImage, QPainter, QPainterPath,
                           QPalette, QPen, QTextBlockFormat, QTextCursor, QTextDocument, QTextOption, QUndoStack)
from PySide6.QtWidgets import QGraphicsItem, QGraphicsScene, QGraphicsView, QStyleOptionGraphicsItem

from .. import job
from . import codes
from .commands import AddElement, ChangeElement, ChangeLabel, MoveInStack, RemoveElement
from .model import DOTS_PER_MM, HEIGHT_MM, Barcode, Element, Label, Picture, QRCode, Shape, Text

GRID_DOTS = 4                 # 0.5 mm snap
MIN_SIZE_DOTS = 8             # 1 mm
HANDLE_PX = 8                 # handle size on screen
ROTATE_OFFSET_PX = 20
PAD = 30                      # room around an item for handles (dots)
BLACK, WHITE = QColor(0, 0, 0), QColor(255, 255, 255)
SELECT_COLOR = QColor(0, 120, 215)
DEFAULT_FONT_PX_PER_PT = 203 / 72

_OPPOSITE = {"tl": "br", "t": "b", "tr": "bl", "r": "l", "br": "tl", "b": "t", "bl": "tr", "l": "r"}


def local_point(name: str, w: float, h: float) -> QPointF:
    """Position of a handle ('tl', 't', 'r', ...) on a w x h box."""
    x = w if "r" in name else 0 if "l" in name else w / 2
    y = h if "b" in name else 0 if "t" in name else h / 2
    return QPointF(x, y)


class ElementItem(QGraphicsItem):
    handle_names = ("tl", "t", "tr", "r", "br", "b", "bl", "l")
    keep_square = False

    def __init__(self, element: Element):
        super().__init__()
        self.element = element
        self.error: str | None = None
        self.warning: str | None = None
        self._lod = 1.0
        self._syncing = False
        self._drag: dict | None = None
        self.setFlags(QGraphicsItem.ItemIsSelectable | QGraphicsItem.ItemIsMovable
                      | QGraphicsItem.ItemSendsGeometryChanges)
        self.sync()

    # --- geometry -------------------------------------------------------------------------
    @property
    def width(self) -> float:
        return max(1.0, self.element.w * DOTS_PER_MM)

    @property
    def height(self) -> float:
        return max(1.0, self.element.h * DOTS_PER_MM)

    def sync(self):
        """Pull geometry and content from the model."""
        self.prepareGeometryChange()
        self._syncing = True
        self.setTransformOriginPoint(self.width / 2, self.height / 2)
        self.setPos(self.element.x * DOTS_PER_MM, self.element.y * DOTS_PER_MM)
        self.setRotation(self.element.rotation)
        self._syncing = False
        self.prepare()
        self.update()

    def prepare(self):
        """Recompute cached content (codes, bitmaps). Subclasses override."""

    def boundingRect(self) -> QRectF:
        return QRectF(-PAD, -PAD, self.width + 2 * PAD, self.height + 2 * PAD)

    def shape(self) -> QPainterPath:
        path = QPainterPath()
        path.addRect(self.boundingRect() if self.isSelected() else QRectF(-2, -2, self.width + 4, self.height + 4))
        return path

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemPositionChange and not self._syncing and self.scene() is not None:
            value = QPointF(round(value.x() / GRID_DOTS) * GRID_DOTS, round(value.y() / GRID_DOTS) * GRID_DOTS)
        elif change == QGraphicsItem.ItemPositionHasChanged and not self._syncing:
            self.element.x = self.pos().x() / DOTS_PER_MM
            self.element.y = self.pos().y() / DOTS_PER_MM
        return super().itemChange(change, value)

    # --- painting -------------------------------------------------------------------------
    def draw(self, painter: QPainter, w: float, h: float):
        raise NotImplementedError

    def paint(self, painter, option, widget=None):
        self._lod = QStyleOptionGraphicsItem.levelOfDetailFromTransform(painter.worldTransform())
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, False)
        painter.setRenderHint(QPainter.TextAntialiasing, True)
        if self.error:
            self._draw_error(painter)
        else:
            self.draw(painter, self.width, self.height)
        painter.restore()
        scene = self.scene()
        if scene is not None and not scene.printing:
            self._draw_overlay(painter)

    def _draw_error(self, painter):
        painter.fillRect(QRectF(0, 0, self.width, self.height), QColor(255, 230, 230))
        painter.setPen(QPen(QColor(200, 0, 0), 1))
        painter.drawRect(QRectF(0, 0, self.width - 1, self.height - 1))
        painter.drawLine(0, 0, int(self.width), int(self.height))
        painter.drawLine(0, int(self.height), int(self.width), 0)

    def handle_rect(self, name: str) -> QRectF:
        size = HANDLE_PX / self._lod
        if name == "rot":
            c = QPointF(self.width / 2, -ROTATE_OFFSET_PX / self._lod)
        else:
            c = local_point(name, self.width, self.height)
        return QRectF(c.x() - size / 2, c.y() - size / 2, size, size)

    def _draw_overlay(self, painter):
        if self.warning or self.error:
            painter.setPen(QPen(QColor(200, 120, 0), 1 / self._lod))
            painter.drawRect(QRectF(0, 0, self.width, self.height))
        if not self.isSelected():
            return
        pen = QPen(SELECT_COLOR, 1 / self._lod, Qt.DashLine)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawRect(QRectF(0, 0, self.width, self.height))
        painter.setPen(QPen(SELECT_COLOR, 1 / self._lod))
        painter.setBrush(QBrush(WHITE))
        if self.scene() is not None and len(self.scene().selectedItems()) == 1:
            painter.drawLine(QPointF(self.width / 2, 0), self.handle_rect("rot").center())
            for name in self.handle_names:
                painter.drawRect(self.handle_rect(name))
            painter.drawEllipse(self.handle_rect("rot"))

    # --- handles --------------------------------------------------------------------------
    def handle_at(self, pos: QPointF) -> str | None:
        if self.scene() is None or len(self.scene().selectedItems()) != 1:
            return None
        for name in ("rot",) + self.handle_names:
            if self.handle_rect(name).adjusted(-3, -3, 3, 3).contains(pos):
                return name
        return None

    def mousePressEvent(self, event):
        name = self.handle_at(event.pos()) if event.button() == Qt.LeftButton else None
        if name is None:
            super().mousePressEvent(event)
            return
        self._drag = {"name": name}
        if name != "rot":
            self._drag["anchor"] = self.mapToScene(local_point(_OPPOSITE[name], self.width, self.height))
        self.scene().drag_kind = "Rotate" if name == "rot" else "Resize"
        event.accept()

    def mouseMoveEvent(self, event):
        if self._drag is None:
            super().mouseMoveEvent(event)
            return
        if self._drag["name"] == "rot":
            self._rotate_to(event.scenePos(), bool(event.modifiers() & Qt.ShiftModifier))
        else:
            # event.pos() can lag one step behind after the item moved itself, so map the scene position
            self._resize_to(self.mapFromScene(event.scenePos()))
        event.accept()

    def mouseReleaseEvent(self, event):
        if self._drag is None:
            super().mouseReleaseEvent(event)
            return
        self._drag = None
        event.accept()
        self.scene().finish_drag()

    def _rotate_to(self, scene_pos: QPointF, coarse: bool):
        centre = self.mapToScene(QPointF(self.width / 2, self.height / 2))
        angle = math.degrees(math.atan2(scene_pos.y() - centre.y(), scene_pos.x() - centre.x())) + 90
        step = 15 if coarse else 1
        angle = round(angle / step) * step
        if abs(angle - round(angle / 15) * 15) < 2:
            angle = round(angle / 15) * 15
        self.element.rotation = angle % 360
        self.sync()

    def _resize_to(self, local: QPointF):
        name, w, h = self._drag["name"], self.width, self.height
        new_w, new_h = w, h
        if "r" in name:
            new_w = local.x()
        elif "l" in name:
            new_w = w - local.x()
        if "b" in name:
            new_h = local.y()
        elif "t" in name:
            new_h = h - local.y()
        snap = lambda v: max(MIN_SIZE_DOTS, round(v / GRID_DOTS) * GRID_DOTS)
        new_w, new_h = snap(new_w), snap(new_h)
        if self.keep_square:
            new_w = new_h = max(new_w, new_h)
        if name in ("l", "r"):
            new_h = h
        if name in ("t", "b"):
            new_w = w
        self.element.w, self.element.h = new_w / DOTS_PER_MM, new_h / DOTS_PER_MM
        self._syncing = True
        self.prepareGeometryChange()
        self.setTransformOriginPoint(self.width / 2, self.height / 2)
        delta = self._drag["anchor"] - self.mapToScene(local_point(_OPPOSITE[name], self.width, self.height))
        self.setPos(self.pos() + delta)
        self._syncing = False
        self.element.x, self.element.y = self.pos().x() / DOTS_PER_MM, self.pos().y() / DOTS_PER_MM
        self.prepare()
        self.update()


class TextItem(ElementItem):
    def draw(self, painter, w, h):
        el = self.element
        font = QFont(el.font)
        font.setPixelSize(max(4, round(el.size_pt * DEFAULT_FONT_PX_PER_PT)))
        font.setBold(el.bold)
        font.setItalic(el.italic)
        font.setUnderline(el.underline)
        doc = QTextDocument()
        doc.setDocumentMargin(0)
        doc.setDefaultFont(font)
        option = QTextOption()
        option.setAlignment({"left": Qt.AlignLeft, "center": Qt.AlignHCenter, "right": Qt.AlignRight}[el.align])
        option.setWrapMode(QTextOption.WordWrap)
        doc.setDefaultTextOption(option)
        doc.setTextWidth(w)
        doc.setPlainText(el.text)
        fmt = QTextBlockFormat()
        fmt.setLineHeight(el.line_spacing * 100, QTextBlockFormat.LineHeightTypes.ProportionalHeight.value)
        cursor = QTextCursor(doc)
        cursor.select(QTextCursor.Document)
        cursor.mergeBlockFormat(fmt)
        if el.inverse:
            painter.fillRect(QRectF(0, 0, w, h), BLACK)
        context = QAbstractTextDocumentLayout.PaintContext()
        palette = QPalette()
        palette.setColor(QPalette.Text, WHITE if el.inverse else BLACK)
        context.palette = palette
        context.clip = QRectF(0, 0, w, h)
        painter.setClipRect(QRectF(0, 0, w, h))
        doc.documentLayout().draw(painter, context)
        self.warning = "text does not fit in its box" if doc.size().height() > h + 0.5 else None


class ShapeItem(ElementItem):
    def __init__(self, element):
        super().__init__(element)
        if element.shape == "line":
            self.handle_names = ("l", "r")

    def draw(self, painter, w, h):
        el = self.element
        pen_w = max(1, round(el.stroke_mm * DOTS_PER_MM))
        pen = QPen(BLACK, pen_w, Qt.SolidLine, Qt.FlatCap, Qt.MiterJoin)
        painter.setPen(pen)
        painter.setBrush(QBrush(BLACK) if el.fill and el.shape != "line" else Qt.NoBrush)
        half = pen_w / 2
        if el.shape == "line":
            painter.drawLine(QPointF(0, h / 2), QPointF(w, h / 2))
        elif el.shape == "ellipse":
            painter.drawEllipse(QRectF(half, half, w - pen_w, h - pen_w))
        else:
            painter.drawRect(QRectF(half, half, w - pen_w, h - pen_w))


class PictureItem(ElementItem):
    def prepare(self):
        self._bitmap = None
        el = self.element
        source = el.pil()
        if source is None:
            self.error = "no image"
            return
        self.error = None
        try:
            flat = job.rotate(source, 0).convert("L")
            w, h = round(self.width), round(self.height)
            if el.keep_aspect:
                scale = min(w / flat.width, h / flat.height)
                size = (max(1, round(flat.width * scale)), max(1, round(flat.height * scale)))
            else:
                size = (w, h)
            flat = flat.resize(size, Image.LANCZOS)
            if el.dither:
                flat = flat.convert("1", dither=Image.FLOYDSTEINBERG).convert("L")
            else:
                flat = flat.point(lambda v: 255 if v >= el.threshold else 0)
            data = flat.tobytes()
            self._bitmap = QImage(data, flat.width, flat.height, flat.width, QImage.Format_Grayscale8).copy()
        except Exception as exc:       # unreadable or corrupt image data
            self.error = f"image error: {exc}"

    def draw(self, painter, w, h):
        if self._bitmap is not None:
            painter.drawImage(int((w - self._bitmap.width()) / 2), int((h - self._bitmap.height()) / 2), self._bitmap)


class QRItem(ElementItem):
    keep_square = True
    handle_names = ("tl", "tr", "br", "bl")

    def prepare(self):
        self._matrix = None
        self.warning = None
        try:
            self._matrix = codes.qr_matrix(self.element.data, self.element.ecc)
            self.error = None
        except ValueError as exc:
            self.error = str(exc)

    def draw(self, painter, w, h):
        matrix = self._matrix
        n = len(matrix)
        scale = codes.fit_scale(n, codes.QUIET_MODULES_QR, int(w), int(h))
        if scale < 1:
            self.warning = "QR code too small"
            self._draw_error(painter)
            return
        self.warning = "QR modules under 2 dots may not scan" if scale < 2 else None
        side = n * scale
        ox, oy = (int(w) - side) // 2, (int(h) - side) // 2
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(BLACK))
        for y, row in enumerate(matrix):
            x = 0
            while x < n:
                if row[x]:
                    start = x
                    while x < n and row[x]:
                        x += 1
                    painter.drawRect(QRect(ox + start * scale, oy + y * scale, (x - start) * scale, scale))
                else:
                    x += 1


class BarcodeItem(ElementItem):
    def prepare(self):
        self._modules, self._text = None, ""
        try:
            self._modules, self._text = codes.barcode_modules(self.element.symbology, self.element.data)
            self.error = None
        except ValueError as exc:
            self.error = str(exc)

    def draw(self, painter, w, h):
        modules = self._modules
        scale = codes.fit_scale(len(modules), 0, int(w))
        if scale < 1:
            self.warning = "barcode too wide for its box"
            self._draw_error(painter)
            return
        self.warning = "bars under 2 dots may not scan" if scale < 2 else None
        text_h = 0
        if self.element.show_text:
            font = QFont("DejaVu Sans Mono")
            font.setPixelSize(min(20, max(10, int(h / 3))))
            painter.setFont(font)
            text_h = painter.fontMetrics().height()
        bars_h = max(1, int(h) - text_h - (2 if text_h else 0))
        ox = (int(w) - len(modules) * scale) // 2
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(BLACK))
        x = 0
        while x < len(modules):
            if modules[x]:
                start = x
                while x < len(modules) and modules[x]:
                    x += 1
                painter.drawRect(QRect(ox + start * scale, 0, (x - start) * scale, bars_h))
            else:
                x += 1
        if text_h:
            painter.setPen(QPen(BLACK))
            painter.drawText(QRectF(0, bars_h + 2, w, text_h), Qt.AlignHCenter | Qt.AlignTop, self._text)


ITEM_FOR = {Text: TextItem, Shape: ShapeItem, Picture: PictureItem, QRCode: QRItem, Barcode: BarcodeItem}


class LabelScene(QGraphicsScene):
    elementsChanged = Signal()     # content or structure changed
    labelChanged = Signal()        # length / density / copies / rotation changed

    def __init__(self, doc: Label, undo: QUndoStack | None = None):
        super().__init__()
        self.doc = doc
        self.undo = undo or QUndoStack(self)
        self.printing = False
        self.drag_kind = "Move"
        self._snap: dict[str, dict] = {}
        self._items: dict[str, ElementItem] = {}
        self.rebuild()

    # --- structure ------------------------------------------------------------------------
    def rebuild(self):
        self.clear()
        self._items.clear()
        for element in self.doc.elements:
            self._add_item(element)
        self._restack()
        self.update_rect()

    def _add_item(self, element: Element):
        item = ITEM_FOR[type(element)](element)
        self.addItem(item)
        self._items[element.id] = item

    def _restack(self):
        for z, element in enumerate(self.doc.elements):
            self._items[element.id].setZValue(z)

    def update_rect(self):
        w, h = self.doc.size_dots
        self.setSceneRect(QRectF(-PAD, -PAD, w + 2 * PAD, h + 2 * PAD))

    def item_for(self, element_id: str) -> ElementItem | None:
        return self._items.get(element_id)

    def insert_element(self, element: Element, index: int | None = None):
        index = len(self.doc.elements) if index is None else index
        self.doc.elements.insert(index, element)
        self._add_item(element)
        self._restack()
        self.elementsChanged.emit()

    def remove_element(self, element_id: str):
        element = self.doc.find(element_id)
        if element is not None:
            self.doc.elements.remove(element)
        item = self._items.pop(element_id, None)
        if item is not None:
            self.removeItem(item)
        self.elementsChanged.emit()

    def reorder(self, element_id: str, new_index: int):
        element = self.doc.find(element_id)
        self.doc.elements.remove(element)
        self.doc.elements.insert(new_index, element)
        self._restack()
        self.elementsChanged.emit()

    def refresh(self, element_id: str):
        item = self._items.get(element_id)
        if item is not None:
            item.sync()
        self.elementsChanged.emit()

    def set_label_state(self, state: dict):
        for key, value in state.items():
            setattr(self.doc, key, value)
        self.update_rect()
        self.update()
        self.labelChanged.emit()

    # --- editing API (everything the UI changes goes through the undo stack) ---------------
    @contextmanager
    def macro(self, text: str):
        """Group the commands pushed inside the block into one undo step, even if the block raises."""
        self.undo.beginMacro(text)
        try:
            yield
        finally:
            self.undo.endMacro()

    def selected_ids(self) -> list[str]:
        try:
            return [i.element.id for i in self.selectedItems() if isinstance(i, ElementItem)]
        except RuntimeError:       # signal delivered while Qt is tearing the scene down at exit
            return []

    def select_only(self, element_id: str | None):
        self.clearSelection()
        if element_id and element_id in self._items:
            self._items[element_id].setSelected(True)

    def add_new(self, element: Element):
        self.undo.push(AddElement(self, element.to_dict(), text=f"Add {element.kind}"))
        self.select_only(element.id)

    def delete_selected(self):
        ids = self.selected_ids()
        if not ids:
            return
        with self.macro("Delete"):
            for element_id in ids:
                self.undo.push(RemoveElement(self, element_id))

    def edit(self, ids: list[str], changes: dict, text: str = "Edit", merge_key: str | None = None):
        """Change fields of one or more elements as one undo step (a single element merges repeated edits)."""
        commands = []
        for element_id in ids:
            before = self.doc.find(element_id).to_dict()
            commands.append(ChangeElement(self, element_id, before, {**before, **changes}, text, merge_key))
        if len(commands) == 1:
            self.undo.push(commands[0])
            return
        with self.macro(text):
            for command in commands:
                self.undo.push(command)

    def edit_label(self, **changes):
        before = {k: getattr(self.doc, k) for k in changes}
        self.undo.push(ChangeLabel(self, before, changes))

    def change_order(self, element_id: str, delta: int | None = None, to: int | None = None):
        count = len(self.doc.elements)
        index = self.doc.elements.index(self.doc.find(element_id))
        target = max(0, min(count - 1, to if to is not None else index + delta))
        if target != index:
            self.undo.push(MoveInStack(self, element_id, target))

    # --- mouse-driven changes are committed once, on release ----------------------------------
    def mousePressEvent(self, event):
        self.drag_kind = "Move"
        super().mousePressEvent(event)
        self._snap = {i: self.doc.find(i).to_dict() for i in self.selected_ids()}

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        self.finish_drag()

    def finish_drag(self):
        snap, self._snap = self._snap, {}
        changes = []
        for element_id, before in snap.items():
            element = self.doc.find(element_id)
            if element is not None and element.to_dict() != before:
                changes.append((element_id, before, element.to_dict()))
        if not changes:
            return
        with self.macro(self.drag_kind):
            for element_id, before, after in changes:
                self.undo.push(ChangeElement(self, element_id, before, after, self.drag_kind))
        self.drag_kind = "Move"

    # --- checks used before printing ------------------------------------------------------
    def problems(self) -> list[str]:
        out = []
        for element in self.doc.elements:
            item = self._items[element.id]
            if item.error:
                out.append(f"{element.kind}: {item.error}")
        return out

    def warnings(self) -> list[str]:
        return [f"{e.kind}: {self._items[e.id].warning}" for e in self.doc.elements if self._items[e.id].warning]


class LabelView(QGraphicsView):
    """Shows the label as paper on a grey table, with a dot grid and zoom."""

    placeRequested = Signal(QPointF)     # a click while an "add element" tool is active (scene coordinates)
    nudgeRequested = Signal(float, float)   # arrow keys, in mm

    def __init__(self, scene: LabelScene):
        super().__init__(scene)
        self.place_mode = False
        self.setRenderHint(QPainter.Antialiasing, False)
        self.setDragMode(QGraphicsView.RubberBandDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setBackgroundBrush(QBrush(QColor(90, 90, 96)))
        self.show_grid = True
        self.zoom_to(0.9 * 4)

    def zoom_to(self, factor: float):
        self.resetTransform()
        self.scale(factor, factor)

    def zoom_by(self, ratio: float):
        self.scale(ratio, ratio)

    def zoom_fit(self):
        rect = QRectF(0, 0, *self.scene().doc.size_dots).adjusted(-10, -10, 10, 10)
        self.fitInView(rect, Qt.KeepAspectRatio)

    def mousePressEvent(self, event):
        if self.place_mode and event.button() == Qt.LeftButton:
            self.placeRequested.emit(self.mapToScene(event.pos()))
            event.accept()
            return
        super().mousePressEvent(event)

    def keyPressEvent(self, event):
        step = 2.0 if event.modifiers() & Qt.ShiftModifier else 0.5
        moves = {Qt.Key_Left: (-step, 0), Qt.Key_Right: (step, 0), Qt.Key_Up: (0, -step), Qt.Key_Down: (0, step)}
        if event.key() in moves and self.scene().selected_ids():
            self.nudgeRequested.emit(*moves[event.key()])
            event.accept()
            return
        super().keyPressEvent(event)

    def wheelEvent(self, event):
        if event.modifiers() & Qt.ControlModifier:
            self.zoom_by(1.15 if event.angleDelta().y() > 0 else 1 / 1.15)
        else:
            super().wheelEvent(event)

    def drawBackground(self, painter, rect):
        super().drawBackground(painter, rect)
        w, h = self.scene().doc.size_dots
        painter.fillRect(QRectF(0, 0, w, h), WHITE)
        if self.show_grid:
            lod = self.transform().m11()
            if lod >= 3:
                painter.setPen(QPen(QColor(205, 205, 215), 0))
                for x in range(0, w + 1, DOTS_PER_MM):
                    painter.drawLine(x, 0, x, h)
                for y in range(0, h + 1, DOTS_PER_MM):
                    painter.drawLine(0, y, w, y)
        painter.setPen(QPen(QColor(60, 60, 60), 0))
        painter.drawRect(QRectF(0, 0, w, h))
