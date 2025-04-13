"""Modal for selecting YNAB accounts to track."""

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Checkbox, Label

from ynab_updater.config import Account
from ynab_updater.modals.utils import _extract_base_id, _generate_widget_id


class AccountSelectModal(ModalScreen[list[Account]]):
    """A modal to select which accounts to track."""

    BINDINGS = [("escape", "cancel_selection", "Cancel")]

    def __init__(
        self,
        available_accounts: list[Account],
        previously_selected_ids: list[str],
    ):
        super().__init__()
        self.available_accounts = sorted(available_accounts, key=lambda acc: acc.config.name)  # Sort accounts by name
        self.previously_selected_ids = set(previously_selected_ids)

    def compose(self) -> ComposeResult:
        with Vertical(classes="modal-dialog"):
            yield Label("Select Accounts to Track")
            with VerticalScroll(id="account-list"):
                for account in self.available_accounts:
                    # Pre-check if the account was previously selected
                    is_checked = account.config.id in self.previously_selected_ids
                    # Use helper to generate ID
                    widget_id = _generate_widget_id("acc", account.config.id)
                    yield Checkbox(account.config.name, value=is_checked, id=widget_id)
            with Horizontal(classes="modal-buttons"):
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
                        continue

                    if account_data := next(
                        (acc for acc in self.available_accounts if acc.config.id == account_id),
                        None,
                    ):
                        selected_accounts.append(account_data)
            self.dismiss(selected_accounts)
        elif event.button.id == "cancel-selection":
            self.dismiss([])  # Return empty list on cancel

    def action_cancel_selection(self):
        """Called when escape is pressed."""
        self.dismiss([])
