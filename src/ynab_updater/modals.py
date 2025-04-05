"""Modals used in the YNAB Updater app."""

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Grid, Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Checkbox, Input, Label, RadioButton, RadioSet, Static

from .config import AccountConfig  # Assuming AccountConfig is defined here
from .widgets import format_currency  # Import currency formatting
from .ynab_client import Account, BudgetSummary

# --- ID Helper Functions --- #


def _generate_widget_id(prefix: str, base_id: str) -> str:
    """Generates a Textual-safe widget ID with a prefix."""
    # Ensure base_id doesn't have characters invalidating the combined ID
    # (Basic check: usually hyphens in UUIDs are okay if not at start)
    return f"{prefix}-{base_id}"


def _extract_base_id(prefix: str, widget_id: str | None) -> str | None:
    """Extracts the base ID from a widget ID if the prefix matches."""
    expected_prefix = f"{prefix}-"
    if widget_id and widget_id.startswith(expected_prefix):
        return widget_id[len(expected_prefix) :]
    return None


class APIKeyModal(ModalScreen[str]):
    """A modal screen to prompt the user for their YNAB API key."""

    BINDINGS = [("escape", "cancel", "Cancel")]

    def compose(self) -> ComposeResult:
        with Grid(id="api-key-dialog"):
            yield Label("Enter YNAB API Key", id="api-key-title")
            yield Label(
                "You can generate a Personal Access Token in your YNAB account settings under 'Developer Settings'.",
                id="api-key-description",
            )
            yield Input(placeholder="Paste your API key here", password=True, id="api-key-input")
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
            self.dismiss("")  # Return empty string on cancel

    def action_cancel(self):
        """Called when escape is pressed."""
        self.dismiss("")


class AccountSelectModal(ModalScreen[list[AccountConfig]]):
    """A modal to select which accounts to track."""

    BINDINGS = [("escape", "cancel_selection", "Cancel")]

    def __init__(
        self,
        available_accounts: list[Account],
        previously_selected_ids: list[str],
    ):
        super().__init__()
        self.available_accounts = sorted(available_accounts, key=lambda acc: acc.name)  # Sort accounts by name
        self.previously_selected_ids = set(previously_selected_ids)

    def compose(self) -> ComposeResult:
        with Vertical(id="account-select-dialog"):
            yield Label("Select Accounts to Track", id="account-select-title")
            with VerticalScroll(id="account-list"):
                for account in self.available_accounts:
                    # Pre-check if the account was previously selected
                    is_checked = account.id in self.previously_selected_ids
                    # Use helper to generate ID
                    widget_id = _generate_widget_id("acc", account.id)
                    yield Checkbox(account.name, value=is_checked, id=widget_id)
            with Horizontal(id="account-select-buttons"):
                yield Button("Save Selection", variant="primary", id="save-selection")
                yield Button("Cancel", variant="default", id="cancel-selection")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "save-selection":
            selected_accounts = []
            checkboxes = self.query(Checkbox)
            for cb in checkboxes:
                # Ensure checkbox is checked AND has a valid ID before processing
                if cb.value and cb.id is not None:
                    # Use helper to extract base ID
                    account_id = _extract_base_id("acc", cb.id)
                    if not account_id:
                        self.log.warning(f"Could not extract account ID from widget ID: {cb.id}")
                        continue  # Skip this checkbox

                    # Use walrus operator for cleaner lookup
                    if account_data := next(
                        (acc for acc in self.available_accounts if acc.id == account_id),
                        None,
                    ):
                        selected_accounts.append(AccountConfig(id=account_data.id, name=account_data.name))
            self.dismiss(selected_accounts)
        elif event.button.id == "cancel-selection":
            self.dismiss([])  # Return empty list on cancel

    def action_cancel_selection(self):
        """Called when escape is pressed."""
        self.dismiss([])


class BudgetSelectModal(ModalScreen[BudgetSummary | None]):
    """A modal to select a single budget."""

    BINDINGS = [("escape", "cancel_selection", "Cancel")]

    def __init__(self, available_budgets: list[BudgetSummary]):
        super().__init__()
        # Store both sorted list for display and dict for lookup
        self.sorted_budgets = sorted(available_budgets, key=lambda b: b.name)
        self.budgets_by_id = {b.id: b for b in available_budgets}

    def compose(self) -> ComposeResult:
        with Vertical(id="budget-select-dialog", classes="modal-dialog"):
            yield Label("Select YNAB Budget", id="budget-select-title")
            with VerticalScroll(id="budget-list"):
                with RadioSet(id="budget-radio-set"):
                    for i, budget in enumerate(self.sorted_budgets):
                        # Use helper to generate ID
                        widget_id = _generate_widget_id("budget", budget.id)
                        yield RadioButton(
                            budget.name,
                            id=widget_id,
                            value=(i == 0),  # Select first one initially
                        )
            with Horizontal(id="budget-select-buttons", classes="modal-buttons"):
                yield Button("Select Budget", variant="primary", id="select-budget")
                yield Button("Cancel", variant="default", id="cancel-selection")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "select-budget":
            radio_set = self.query_one(RadioSet)
            if radio_set.pressed_button and radio_set.pressed_button.id:
                # Use helper to extract base ID
                selected_id = _extract_base_id("budget", radio_set.pressed_button.id)

                if selected_id:
                    # Find the full budget data using the dictionary
                    selected_budget = self.budgets_by_id.get(selected_id)
                    self.dismiss(selected_budget)
                else:
                    # Log error if ID extraction failed
                    self.log.error(f"Could not extract budget ID from radio button ID: {radio_set.pressed_button.id}")
                    self.notify("Internal error selecting budget.", severity="error")
            else:
                self.notify("Please select a budget.", severity="warning")
        elif event.button.id == "cancel-selection":
            self.dismiss(None)

    def action_cancel_selection(self):
        """Called when escape is pressed."""
        self.dismiss(None)


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
        with Grid(id="confirm-dialog"):
            yield Label(self._title, id="confirm-title")
            # Use Static for potentially rich text prompts
            yield Static(self._prompt, id="confirm-prompt")
            yield Button(self._confirm_label, variant="primary", id="confirm")
            yield Button(self._cancel_label, variant="error", id="cancel")

    def on_button_pressed(self, event: Button.Pressed):
        if event.button.id == "confirm":
            self.dismiss(True)
        elif event.button.id == "cancel":
            self.dismiss(False)

    def action_reject(self):
        """Called when escape is pressed."""
        self.dismiss(False)


# --- Helper function to create confirmation prompt for bulk updates --- #


def create_bulk_update_prompt(updates: list[tuple[str, str, int, int]]) -> Text:
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
        adjustment_str = format_currency(adjustment)
        new_balance_str = format_currency(new_balance)
        # Add color to adjustment amount
        color = "green" if adjustment >= 0 else "red"
        prompt_text.append(f" • {name}: ")
        prompt_text.append(f"{adjustment_str} ", style=color)
        prompt_text.append(f"(New balance: {new_balance_str})\n")

    prompt_text.append("\nDo you want to proceed?")
    return prompt_text
