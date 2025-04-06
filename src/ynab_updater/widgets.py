"""Custom Textual widgets for the YNAB Updater app."""

from textual.app import ComposeResult
from textual.message import Message
from textual.widget import Widget
from textual.widgets import Button, Input, Label


def format_currency(milliunits: int, currency_symbol: str = "$", symbol_first: bool = True) -> str:
    """Formats an integer amount in milliunits into a currency string."""
    # Determine sign first
    is_negative = milliunits < 0
    abs_milliunits = abs(milliunits)

    # Convert absolute milliunits to dollars and cents
    total_cents = abs_milliunits // 10
    dollars = total_cents // 100
    cents = total_cents % 100

    # Format the absolute value
    value_part = f"{dollars}.{cents:02d}"

    # Add currency symbol based on flag
    formatted_value = f"{currency_symbol}{value_part}" if symbol_first else f"{value_part}{currency_symbol}"

    # Prepend the negative sign if necessary
    return f"-{formatted_value}" if is_negative else formatted_value


class AccountRow(Widget):
    """A widget to display information for a single YNAB account."""

    DEFAULT_CSS = """
    AccountRow {
        layout: horizontal;
        align: center middle;
        padding: 1;
        border: round $accent;
        margin-bottom: 1;
        height: auto; /* Let content plus child heights determine row height */
        /* min-height: 5; <- Remove or comment out, let explicit heights work */
    }
    AccountRow > Static { /* General style for direct children if needed */
        width: 1fr; /* Distribute space - maybe remove if specific widths below cover all */
        margin-right: 2;
        height: 3; /* Explicit height for alignment */
    }
    AccountRow > Input {
        width: 15; /* Fixed width for balance input */
        margin-right: 2;
        height: 3; /* Explicit height for alignment */
    }
    AccountRow > Button {
        width: 12; /* Fixed width for button */
        margin-right: 1;
        min-width: 12;
        height: 3; /* Explicit height for alignment */
    }
    AccountRow > Label {
        width: 25; /* Width for account name */
        content-align: left middle;
        margin-right: 2;
        height: 3; /* Explicit height for alignment */
    }
    AccountRow > .balance-label {
        width: 15; /* Width for current balance */
        content-align: right middle;
        /* height: 3; <- Inherited from AccountRow > Label */
    }
    """

    class BalanceUpdate(Message):
        """Message sent when the update button for this account is pressed."""

        def __init__(self, account_id: str, new_balance_str: str):
            self.account_id = account_id
            self.new_balance_str = new_balance_str
            super().__init__()

    def __init__(self, account_id: str, account_name: str, current_balance: int, **kwargs) -> None:
        super().__init__(**kwargs)
        self.account_id = account_id
        self.account_name = account_name
        self.current_balance_milliunits = current_balance

        self._name_label = Label(account_name)
        self._balance_label = Label(format_currency(current_balance), classes="balance-label")
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
        self._balance_label.update(format_currency(new_balance_milliunits))

    @property
    def new_balance_input_value(self) -> str:
        """Returns the current value of the balance input field."""
        return self._balance_input.value.strip()
