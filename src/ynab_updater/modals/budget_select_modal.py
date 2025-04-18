"""Modal for selecting a YNAB budget."""

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Label, Select, Static

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
            yield Static("Select the budget you want to use for balance updates.")

            # Create a list of (value, label) tuples for the Select widget
            # Using the widget ID generator to maintain consistent ID format
            budget_options = [(budget.name, _generate_widget_id("budget", budget.id)) for budget in self.sorted_budgets]

            # For Select widget, don't set initial value - let it be auto-selected
            yield Select(options=budget_options, id="budget-select")

            with Horizontal(id="budget-select-buttons", classes="modal-buttons"):
                yield Button("Cancel", variant="default", id="cancel-selection")
                yield Button("Select Budget", variant="primary", id="select-budget")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "select-budget":
            select = self.query_one(Select)
            if select.value is not None and str(select.value):
                # Extract the base ID using the utility function
                if selected_id := _extract_base_id("budget", str(select.value)):
                    # Find the full budget data using the dictionary
                    selected_budget = self.budgets_by_id.get(selected_id)
                    self.dismiss(selected_budget)
                else:
                    # Log error if ID extraction failed
                    self.log.error(f"Could not extract budget ID from select value: {select.value}")
                    self.notify("Internal error selecting budget.", severity="error")
            else:
                self.notify("Please select a budget.", severity="warning")
        elif event.button.id == "cancel-selection":
            self.dismiss(None)

    def action_cancel_selection(self):
        """Called when escape is pressed."""
        self.dismiss(None)
