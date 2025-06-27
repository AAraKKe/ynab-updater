"""Modal for entering the YNAB API Key."""

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label


class APIKeyModal(ModalScreen[str]):
    """A modal screen to prompt the user for their YNAB API key."""

    BINDINGS = [("escape", "cancel", "Cancel")]

    def compose(self) -> ComposeResult:
        with Vertical(id="api-key-dialog", classes="modal-dialog"):
            yield Label("Enter YNAB API Key", id="api-key-title")
            yield Label(
                "You can generate a Personal Access Token in your YNAB account settings under 'Developer Settings'.",
                id="api-key-description",
            )
            yield Input(placeholder="Paste your API key here", password=True, id="api-key-input")
            with Horizontal(id="api-key-buttons", classes="modal-buttons"):
                yield Button("Submit", variant="primary", id="submit-key")
                yield Button("Cancel", variant="default", id="cancel-key")

    def on_mount(self):
        """Focus the input field when the modal mounts."""
        self.query_one(Input).focus()

    def on_button_pressed(self, event: Button.Pressed):
        if event.button.id == "submit-key":
            if api_key := self.query_one("#api-key-input", Input).value:
                self.dismiss(api_key)
            else:
                self.app.notify("API Key cannot be empty.", severity="error", timeout=3)
        elif event.button.id == "cancel-key":
            self.dismiss(None)

    def action_cancel(self):
        """Called when escape is pressed."""
        self.dismiss("")
