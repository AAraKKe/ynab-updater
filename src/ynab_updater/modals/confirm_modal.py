"""Generic confirmation modal and helpers."""

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Label, Static


class ConfirmModal(ModalScreen[bool]):
    """A modal screen for confirming an action."""

    BINDINGS = [("escape", "reject", "Cancel")]

    def __init__(
        self,
        title: str,
        prompt: str | Text,
        confirm_label: str = "Confirm",
        cancel_label: str = "Cancel",
    ):
        super().__init__()
        self._title = title
        self._prompt = prompt
        self._confirm_label = confirm_label
        self._cancel_label = cancel_label

    def compose(self) -> ComposeResult:
        with Vertical(classes="modal-dialog"):
            yield Label(self._title)
            yield Static(self._prompt)
            with Horizontal(classes="modal-buttons"):
                yield Button(self._cancel_label, variant="error", id="cancel")
                yield Button(self._confirm_label, variant="primary", id="confirm")

    def on_button_pressed(self, event: Button.Pressed):
        if event.button.id == "confirm":
            self.dismiss(True)
        elif event.button.id == "cancel":
            self.dismiss(False)

    def action_reject(self):
        """Called when escape is pressed."""
        self.dismiss(False)
