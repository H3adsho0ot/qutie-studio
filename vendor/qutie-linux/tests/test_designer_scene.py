import pytest

pytest.importorskip("PySide6")
from PySide6.QtCore import QPoint, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QUndoStack  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402

from qutie.designer import model, render  # noqa: E402
from qutie.designer.canvas import LabelScene, LabelView  # noqa: E402


@pytest.fixture
def scene():
    render.ensure_app()
    return LabelScene(model.Label(length_mm=40), QUndoStack())


def add(scene, element):
    """Add through the undo stack and return the live element (the scene recreates it from saved state)."""
    scene.add_new(element)
    QTest.qWait(20)         # a user always clicks after the event loop has run (scene index, first paint)
    return scene.doc.find(element.id)


def rect(x=5.0, y=2.0, w=10.0, h=6.0):
    return model.Shape(x=x, y=y, w=w, h=h)


def test_add_delete_undo_redo(scene):
    el = rect()
    el = add(scene, el)
    assert scene.doc.elements == [el] and scene.selected_ids() == [el.id]
    scene.delete_selected()
    assert scene.doc.elements == []
    scene.undo.undo()
    assert [e.id for e in scene.doc.elements] == [el.id] and scene.item_for(el.id) is not None
    scene.undo.undo()
    assert scene.doc.elements == []
    scene.undo.redo()
    scene.undo.redo()
    assert scene.doc.elements == []


def test_edit_changes_model_and_undoes(scene):
    el = rect()
    el = add(scene, el)
    scene.edit([el.id], {"x": 9.0, "stroke_mm": 1.5}, "Edit")
    assert (el.x, el.stroke_mm) == (9.0, 1.5)
    scene.undo.undo()
    assert (el.x, el.stroke_mm) == (5.0, 0.5)


def test_repeated_edits_of_one_field_merge_into_one_step(scene):
    el = model.Text(text="a")
    el = add(scene, el)
    for value in ("ab", "abc", "abcd"):
        scene.edit([el.id], {"text": value}, "Edit text", "text")
    assert scene.undo.count() == 2
    scene.undo.undo()
    assert el.text == "a"


def test_editing_several_elements_is_one_undo_step(scene):
    a, b = rect(), rect(x=20)
    a = add(scene, a)
    b = add(scene, b)
    scene.edit([a.id, b.id], {"y": 4.0}, "Move")
    assert (a.y, b.y) == (4.0, 4.0)
    scene.undo.undo()
    assert (a.y, b.y) == (2.0, 2.0)


def test_z_order_commands(scene):
    a, b, c = rect(), rect(x=10), rect(x=20)
    for e in (a, b, c):
        scene.add_new(e)
    scene.change_order(a.id, to=10**6)
    assert [e.id for e in scene.doc.elements] == [b.id, c.id, a.id]
    assert scene.item_for(a.id).zValue() > scene.item_for(c.id).zValue()
    scene.undo.undo()
    assert [e.id for e in scene.doc.elements] == [a.id, b.id, c.id]
    scene.change_order(c.id, delta=-1)
    assert [e.id for e in scene.doc.elements] == [a.id, c.id, b.id]


def test_label_settings_undo(scene):
    scene.edit_label(length_mm=60.0)
    assert scene.doc.length_mm == 60.0 and scene.sceneRect().width() > 480
    scene.undo.undo()
    assert scene.doc.length_mm == 40.0


def test_problems_and_warnings(scene):
    scene.add_new(model.QRCode(data=""))
    assert scene.problems() and "QR" in scene.problems()[0]


# --- real mouse interaction ----------------------------------------------------------------------
ZOOM = 4.0


@pytest.fixture
def view(scene):
    v = LabelView(scene)
    v.zoom_to(ZOOM)
    v.resize(1400, 500)
    v.show()
    v.verticalScrollBar().setValue(0)
    v.horizontalScrollBar().setValue(0)
    QTest.qWait(30)
    return v


def vp(view, x, y):
    return view.mapFromScene(QPointF(x, y))


def drag(view, start, end):
    QTest.mousePress(view.viewport(), Qt.LeftButton, Qt.NoModifier, start)
    QTest.mouseMove(view.viewport(), (start + end) / 2)
    QTest.mouseMove(view.viewport(), end)
    QTest.mouseRelease(view.viewport(), Qt.LeftButton, Qt.NoModifier, end)


def test_dragging_moves_snaps_and_undoes_in_one_step(scene, view):
    el = rect()
    el = add(scene, el)
    scene.clearSelection()
    centre = vp(view, 80, 40)                     # element box is x 40..120, y 16..64 dots
    drag(view, centre, centre + QPoint(int(16 * ZOOM), int(8 * ZOOM)))
    assert (el.x, el.y) == (7.0, 3.0)
    assert scene.undo.undoText() == "Move"
    scene.undo.undo()
    assert (el.x, el.y) == (5.0, 2.0)


def test_resize_handle_on_the_right_edge(scene, view):
    el = rect()
    el = add(scene, el)                            # selected after add
    handle = vp(view, 120, 40)                     # right-middle handle
    drag(view, handle, handle + QPoint(int(16 * ZOOM), 0))
    assert (el.x, el.w, el.h) == (5.0, 12.0, 6.0)
    assert scene.undo.undoText() == "Resize"
    scene.undo.undo()
    assert el.w == 10.0


def test_resize_from_top_left_keeps_the_opposite_corner_fixed(scene, view):
    el = rect()
    el = add(scene, el)
    handle = vp(view, 40, 16)
    drag(view, handle, handle + QPoint(-int(8 * ZOOM), -int(8 * ZOOM)))
    assert (el.x, el.y, el.w, el.h) == (4.0, 1.0, 11.0, 7.0)
    assert (el.x + el.w, el.y + el.h) == (15.0, 8.0)


def test_qr_resize_stays_square(scene, view):
    qr = model.QRCode(x=5, y=1, w=8, h=8)
    qr = add(scene, qr)
    handle = vp(view, 40 + 64, 8 + 64)             # bottom-right corner
    drag(view, handle, handle + QPoint(int(8 * ZOOM), 0))
    assert qr.w == qr.h == 9.0


def test_rotation_handle_rotates_about_the_centre(scene, view):
    el = rect()
    el = add(scene, el)
    handle = vp(view, 80, 16 - 20 / ZOOM)           # rotation handle sits above the top edge
    drag(view, handle, vp(view, 80 + 60, 40))       # pull it to the right of the centre -> 90 degrees
    assert el.rotation == pytest.approx(90.0, abs=1.0)
    assert (el.x, el.y, el.w, el.h) == (5.0, 2.0, 10.0, 6.0)      # rotation does not move the box
    assert scene.undo.undoText() == "Rotate"


def test_arrow_key_nudge_signal(scene, view):
    el = rect()
    el = add(scene, el)
    got = []
    view.nudgeRequested.connect(lambda dx, dy: got.append((dx, dy)))
    QTest.keyClick(view.viewport() if False else view, Qt.Key_Right)
    QTest.keyClick(view, Qt.Key_Up, Qt.ShiftModifier)
    assert got == [(0.5, 0), (0, -2.0)]


def test_label_setting_undo_is_per_field_and_repeats_merge(scene):
    scene.edit_label(length_mm=50.0)
    scene.edit_label(length_mm=55.0)          # same field again: merges
    scene.edit_label(copies=4)                # different field: its own step
    assert scene.undo.count() == 2
    scene.undo.undo()
    assert (scene.doc.copies, scene.doc.length_mm) == (1, 55.0)
    scene.undo.undo()
    assert scene.doc.length_mm == 40.0
