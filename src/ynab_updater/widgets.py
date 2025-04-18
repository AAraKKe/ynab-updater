"""Custom Textual widgets for the YNAB Updater app."""

from textual.app import ComposeResult
from textual.message import Message
from textual.widget import Widget
from textual.widgets import Button, Input, Label

from ynab_updater.config import CurrencyFormat
from ynab_updater.utils import format_currency


class AccountRow(Widget):
    """A widget to display information for a single YNAB account."""

    class BalanceUpdate(Message):
        """Message sent when the update button for this account is pressed."""

        def __init__(self, account_id: str, new_balance_str: str):
            self.account_id = account_id
            self.new_balance_str = new_balance_str
            super().__init__()

    def __init__(
        self, account_id: str, account_name: str, current_balance: int, format: CurrencyFormat, **kwargs
    ) -> None:
        super().__init__(**kwargs)
        self.account_id = account_id
        self.account_name = account_name
        self.current_balance_milliunits = current_balance
        self.format = format

        self._name_label = Label(account_name)
        self._balance_label = Label(format_currency(current_balance, format), classes="balance-label")
        self._balance_input = Input(placeholder="New Balance (e.g., 123.45)")
        self._update_button = Button("Update", variant="success", id=f"update-{account_id}")

    def compose(self) -> ComposeResult:
        yield self._name_label
        yield self._balance_label
        yield self._balance_input
        yield self._update_button

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == f"update-{self.account_id}":
            if new_balance := self._balance_input.value.strip():
                self.post_message(self.BalanceUpdate(self.account_id, new_balance))
                self._balance_input.value = ""  # Clear input after sending
            else:
                self.app.notify("Please enter a new balance first.", severity="warning", timeout=3)

    def update_balance(self, new_balance_milliunits: int) -> None:
        """Updates the displayed current balance."""
        self.current_balance_milliunits = new_balance_milliunits
        self._balance_label.update(format_currency(new_balance_milliunits, self.format))

    @property
    def new_balance_input_value(self) -> str:
        """Returns the current value of the balance input field."""
        return self._balance_input.value.strip()
