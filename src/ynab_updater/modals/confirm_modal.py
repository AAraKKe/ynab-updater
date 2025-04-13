"""Generic confirmation modal and helpers."""

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Label, Static

from ynab_updater.config import CurrencyFormat
from ynab_updater.utils import format_currency


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


# --- Helper function to create confirmation prompt for bulk updates --- #


def create_bulk_update_prompt(updates: list[tuple[str, str, int, int]], format: CurrencyFormat) -> Text:
    """
    Generates a Rich Text prompt for the bulk update confirmation modal.

    Args:
        updates: A list of tuples, where each tuple contains:
                 (account_id, account_name, old_balance_milliunits, adjustment_milliunits)

    Returns:
        A Rich Text object summarizing the changes.
    """
    prompt_text = Text("The following balance adjustments will be made:\n\n")
    for _, name, old_balance, adjustment in updates:
        new_balance = old_balance + adjustment
        adjustment_str = format_currency(adjustment, format)
        new_balance_str = format_currency(new_balance, format)
        # Add color to adjustment amount
        color = "green" if adjustment >= 0 else "red"
        prompt_text.append(f" • {name}: ")
        prompt_text.append(f"{adjustment_str} ", style=color)
        prompt_text.append(f"(New balance: {new_balance_str})\n")

    prompt_text.append("\nDo you want to proceed?")
    return prompt_text
