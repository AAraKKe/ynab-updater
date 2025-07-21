from __future__ import annotations

from typing import TYPE_CHECKING

from textual import on, work
from textual.app import ComposeResult
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.widgets import Button

from ynab_updater.config import AppConfig
from ynab_updater.modals import ConfirmModal
from ynab_updater.screens import ConfigScreen
from ynab_updater.utils import bulk_update_balance_text
from ynab_updater.ynab_client import get

from .accounts import Accounts
from .net_worth import NetWorth

if TYPE_CHECKING:
    from ynab.models.new_transaction import NewTransaction

    from .account_row import AccountUpdate


class MainView(Container):
    def __init__(self, config: AppConfig):
        self.config = config
        super().__init__()

    def compose(self) -> ComposeResult:
        # Contains:
        # Left: account list to update
        # Right: net work summary
        # Bottom: button bar
        with Vertical():
            with Horizontal():
                with VerticalScroll():
                    yield Accounts(config=self.config)
                with VerticalScroll():
                    yield NetWorth()
            with Container(id="button-bar"):
                # Place Config button directly, it will be docked left by CSS
                yield Button("Config", id="config")
                # Wrap right buttons in a Horizontal container again
                with Horizontal(id="right-button-group"):
                    yield Button("Refresh Balances", id="refresh-balances", variant="default")
                    yield Button("Update All", id="update-all", variant="primary")

    @on(Button.Pressed, "#refresh-balances")
    def on_button_pressed(self, event: Button.Pressed):
        for account in self.query_one(Accounts).accounts:
            account.update_balance()
            event.stop()

    @on(Button.Pressed, "#config")
    def on_config_button(self, event: Button.Pressed):
        accounts = self.query_one(Accounts)
        self.workers.cancel_group(accounts, group="ynab-balance-update")

        # Whend ismissed, reload the view
        async def reload_view(saved: bool | None):
            if saved:
                accounts = self.query_one(Accounts)
                await accounts.refresh_accounts()

        self.app.push_screen(ConfigScreen(self.config), reload_view)
        event.stop()

    @on(Button.Pressed, "#update-all")
    def update_all(self, event: Button.Pressed):
        accounts_to_update: list[AccountUpdate] = []
        transactions: list[NewTransaction] = []

        for update in self.query_one(Accounts).accounts_to_update:
            accounts_to_update.append(update)
            adjustment = update.new_balance - update.old_balance

            transactions.append(
                get().build_transaction(
                    account_id=update.account_id,
                    amount=adjustment,
                    cleared_status=self.config.adjustment_cleared_status,
                    memo=self.config.adjustment_memo,
                )
            )

            update.account_row.balance_label.loading = True

        def update_balances(accept: bool | None):
            if not accept:
                for update in accounts_to_update:
                    update.account_row.balance_label.loading = False
                return

            self.push_transactions(transactions, accounts_to_update)

        self.app.push_screen(
            ConfirmModal(
                "Confirm Balance Adjustments",
                bulk_update_balance_text(accounts_to_update, self.config.selected_budget.currency_format),
            ),
            update_balances,
        )

        event.stop()

    @work(thread=True)
    async def push_transactions(self, transactions: list[NewTransaction], updates: list[AccountUpdate]):
        get().create_transactions(self.config.selected_budget.id, transactions)
        self.app.notify(f"A total of {len(transactions)} adjustments have been cerated.")

        for update in updates:
            update.account_row.update_balance(update.new_balance)
            update.account_row.input_field.value = ""
            update.account_row.balance_label.loading = False
