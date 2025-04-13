"""Modal for selecting a YNAB budget."""

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Label, RadioButton, RadioSet, TextArea

from ..ynab_client import BudgetSummary
from .utils import _extract_base_id, _generate_widget_id


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
            yield TextArea("These are the budgets present in your YNAB account.")
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
                yield Button("Cancel", variant="default", id="cancel-selection")
                yield Button("Select Budget", variant="primary", id="select-budget")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "select-budget":
            radio_set = self.query_one(RadioSet)
            if radio_set.pressed_button and radio_set.pressed_button.id:
                if selected_id := _extract_base_id("budget", radio_set.pressed_button.id):
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
