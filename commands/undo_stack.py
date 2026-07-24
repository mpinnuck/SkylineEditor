"""Generic Command-pattern undo/redo stack (REQ-27)."""
from __future__ import annotations

from typing import Callable, List, NamedTuple


class Command(NamedTuple):
    do: Callable[[], None]
    undo: Callable[[], None]
    description: str = ""


class UndoStack:
    def __init__(self) -> None:
        self._undo: List[Command] = []
        self._redo: List[Command] = []

    def do(self, command: Command) -> None:
        command.do()
        self._undo.append(command)
        self._redo.clear()

    def undo(self) -> bool:
        if not self._undo:
            return False
        command = self._undo.pop()
        command.undo()
        self._redo.append(command)
        return True

    def redo(self) -> bool:
        if not self._redo:
            return False
        command = self._redo.pop()
        command.do()
        self._undo.append(command)
        return True

    def can_undo(self) -> bool:
        return bool(self._undo)

    def can_redo(self) -> bool:
        return bool(self._redo)

    def clear(self) -> None:
        self._undo.clear()
        self._redo.clear()
