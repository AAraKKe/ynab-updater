from textual.app import ComposeResult
from textual.screen import Screen
from textual.widgets import Footer, Header, Static


class ConfigScreen(Screen):
    """Configuration screen (currently placeholder)."""

    BINDINGS = [("escape", "app.pop_screen", "Back")]

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static("Configuration Options (Coming Soon!)", id="config-title")
        # Add config widgets here later
        yield Footer()
