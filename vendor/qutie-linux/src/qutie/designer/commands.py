"""Undo/redo commands. Each one changes the document model and asks the scene to refresh."""
from PySide6.QtGui import QUndoCommand

from .model import Element, element_from_dict

_FIXED = ("id", "kind")


def apply_state(element: Element, state: dict) -> None:
    for key, value in state.items():
        if key not in _FIXED and hasattr(element, key):
            setattr(element, key, value)


class ChangeElement(QUndoCommand):
    def __init__(self, scene, element_id: str, before: dict, after: dict, text: str, merge_key=None):
        super().__init__(text)
        self.scene, self.element_id = scene, element_id
        self.before, self.after, self.merge_key = before, after, merge_key

    def _apply(self, state):
        element = self.scene.doc.find(self.element_id)
        if element is not None:
            apply_state(element, state)
            self.scene.refresh(self.element_id)

    def undo(self):
        self._apply(self.before)

    def redo(self):
        self._apply(self.after)

    def id(self):
        return 1 if self.merge_key else -1

    def mergeWith(self, other):
        if (not self.merge_key or other.merge_key != self.merge_key or other.element_id != self.element_id):
            return False
        self.after = other.after
        return True


class AddElement(QUndoCommand):
    def __init__(self, scene, state: dict, index: int | None = None, text: str = "Add"):
        super().__init__(text)
        self.scene, self.state, self.index = scene, state, index

    def redo(self):
        self.scene.insert_element(element_from_dict(self.state), self.index)

    def undo(self):
        self.scene.remove_element(self.state["id"])


class RemoveElement(QUndoCommand):
    def __init__(self, scene, element_id: str, text: str = "Delete"):
        super().__init__(text)
        self.scene, self.element_id = scene, element_id
        self.state = scene.doc.find(element_id).to_dict()
        self.index = scene.doc.elements.index(scene.doc.find(element_id))

    def redo(self):
        self.scene.remove_element(self.element_id)

    def undo(self):
        self.scene.insert_element(element_from_dict(self.state), self.index)


class MoveInStack(QUndoCommand):
    """Change the z-order of an element (index in the element list)."""

    def __init__(self, scene, element_id: str, new_index: int, text: str = "Reorder"):
        super().__init__(text)
        self.scene, self.element_id, self.new_index = scene, element_id, new_index
        self.old_index = scene.doc.elements.index(scene.doc.find(element_id))

    def redo(self):
        self.scene.reorder(self.element_id, self.new_index)

    def undo(self):
        self.scene.reorder(self.element_id, self.old_index)


class ChangeLabel(QUndoCommand):
    def __init__(self, scene, before: dict, after: dict, text="Label settings"):
        super().__init__(text)
        self.scene, self.before, self.after = scene, before, after

    def undo(self):
        self.scene.set_label_state(self.before)

    def redo(self):
        self.scene.set_label_state(self.after)

    def id(self):
        return 2

    def mergeWith(self, other):
        if set(other.after) != set(self.after):      # only repeated edits of the same setting merge
            return False
        self.after = other.after
        return True
