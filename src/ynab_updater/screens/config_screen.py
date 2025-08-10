from __future__ import annotations

from typing import TYPE_CHECKING

from textual.app import ComposeResult
from textual.containers import Container, Grid, Horizontal, VerticalScroll
from textual.message import Message
from textual.screen import Screen
from textual.widgets import Button, Checkbox, Collapsible, Footer, Header, Input, Label, Select

from ynab_updater.config import ClearedStatus
from ynab_updater.widgets import DebtAccountMappingRow

if TYPE_CHECKING:
    # Revert to absolute imports for type checking
    from ynab_updater.config import AppConfig


class ConfigScreen(Screen[bool]):
    """Screen for configuring application settings."""

    class ConfigSaved(Message):
        """Message sent when the config is saved."""

        pass

    TITLE = "YNAB Updater"
    SUB_TITLE = "Quickly update account balances"
    BINDINGS = [
        ("escape", "back", "Back"),
    ]

    def __init__(
        self,
        config: AppConfig,
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(name, id, classes)
        self.config = config

    def compose(self) -> ComposeResult:
        """Create child widgets for the screen."""
        yield Header()
        with VerticalScroll(id="main-config-container"):
            with Collapsible(title="Updater Configuration", classes="config-collapsible", collapsed=False):
                with VerticalScroll(id="config-form"):
                    with Container(classes="config-container") as container:
                        container.border_title = "[bold]Adjustment Memo[/bold]"
                        yield Label(
                            "[dim]his is the memo added to the adjustment transaction[/dim]",
                            classes="config-description",
                        )
                        yield Input(
                            value=self.config.adjustment_memo,
                            placeholder=self.config.adjustment_memo,
                            id="adjustment-memo",
                        )

                    with Container(classes="config-container") as container:
                        container.border_title = "[bold]Adjustment Cleared Status[/bold]"
                        yield Label(
                            "[dim]This is the cleared status to be used for the adjustment transactions[/dim]",
                            classes="config-description",
                        )
                        yield Select(
                            options=[(status.value.title(), status) for status in ClearedStatus],
                            value=self.config.adjustment_cleared_status,
                            id="adjustment-cleared-status",
                        )

                    with VerticalScroll(classes="config-container") as container:
                        container.border_title = "[bold]Selected Accounts[/bold]"
                        with Grid(id="accounts-grid"):
                            for account in self.config.accounts:
                                yield Checkbox(
                                    account.config.name,
                                    value=account.selected,
                                    id=f"account-{account.config.id}",
                                )

            with Collapsible(title="Net Worth", classes="config-collapsible"):
                with VerticalScroll(id="config-form"):
                    with Container(classes="config-container") as container:
                        container.border_title = "[bold]Debt account mapping[/bold]"
                        yield Label(
                            "[dim]Link each debt to one or more asset, savings, or cash accounts. If multiple accounts "
                            "are selected, the debt balance will be distributed among them.\n\n"
                            "This total is then subtracted from the linked accounts to show their "
                            "true net value.[/dim]",
                            classes="config-description",
                        )
                        for debt_mapping in self.config.networth_config.debt_assingmet:
                            yield DebtAccountMappingRow(account_id=debt_mapping.debt_account_id, config=self.config)

        with Horizontal(classes="modal-buttons"):
            yield Button("Cancel", id="cancel")
            yield Button("Save", id="save", variant="primary")

        yield Footer()

    def on_mount(self) -> None:
        """Called when the screen is mounted."""
        # Set focus to the first input field
        self.query_one("#adjustment-memo", Input).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button press events."""
        if event.button.id == "cancel":
            self.action_back()
        elif event.button.id == "save":
            self.action_save()

    def action_back(self) -> None:
        """Called when the Cancel button is pressed or escape is hit."""
        self.dismiss(False)

    def action_save(self) -> None:
        """Called when the Save button is pressed."""
        # Update config from form values
        self.config.adjustment_memo = self.query_one("#adjustment-memo", Input).value

        selected_status = self.query_one("#adjustment-cleared-status", Select).value
        if selected_status and isinstance(selected_status, ClearedStatus):
            self.config.adjustment_cleared_status = selected_status
        else:
            self.config.adjustment_cleared_status = ClearedStatus.CLEARED

        needs_refresh = False
        # Update selected accounts
        for account in self.config.accounts:
            checkbox = self.query_one(f"#account-{account.config.id}", Checkbox)
            if account.selected != checkbox.value:
                needs_refresh = True
            account.selected = checkbox.value

        # Save and refresh config
        self.config.refresh()
        self.app.notify("Configuration saved.")
        self.dismiss(needs_refresh)
