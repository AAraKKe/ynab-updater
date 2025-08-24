from __future__ import annotations

from dataclasses import dataclass
from typing import cast

from textual import work
from textual.app import ComposeResult
from textual.message import Message
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Button, Input, Label

from ynab_updater.config import AppConfig, CurrencyFormat
from ynab_updater.modals import ConfirmModal
from ynab_updater.utils import css_id, format_balance, parse_currency_to_milliunits, update_balance_text
from ynab_updater.ynab_client import get


class AccountNotFound(Exception):
    pass


@dataclass
class AccountUpdate:
    account_id: str
    account_name: str
    old_balance: int
    new_balance: int
    account_row: AccountRow


class AccountRow(Widget):
    """A widget to display information for a single YNAB account."""

    balance_milliunits = reactive(0, layout=True)
    balance = reactive("", layout=True)
    account_name = reactive("", layout=True)

    class AccountRowMounted(Message):
        def __init__(self, row: AccountRow):
            self.row = row
            super().__init__()

    def __init__(
        self,
        account_id: str,
        account_name: str,
        current_balance: int,
        format: CurrencyFormat,
        config: AppConfig,
        **kwargs,
    ) -> None:
        kwargs["id"] = f"account-row-{account_id}"
        super().__init__(**kwargs)
        self.account_id = account_id
        self.format = format
        self.config = config

        # Set reactive attributes
        self.balance_milliunits = current_balance
        self.account_name = account_name

    def compose(self) -> ComposeResult:
        yield Label(self.account_name)
        yield Label(self.balance, classes="balance-label")
        yield Input(id=f"account-input-{self.account_id}", placeholder="New Balance (e.g., 123.45)")
        yield Button("Update", variant="success", id=f"update-{self.account_id}")

    def on_mount(self):
        self.post_message(AccountRow.AccountRowMounted(self))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == f"update-{self.account_id}":
            if new_balance := self.new_balance_input_value:
                self.balance_label.loading = True
                self.push_new_balance(new_balance)
            else:
                self.app.notify("Please enter a new balance first.", severity="warning", timeout=3)
            event.stop()

    def compute_balance(self) -> str:
        return format_balance(self.balance_milliunits, self.format)

    def watch_balance(self, new_balance_str: str) -> None:
        if self.is_mounted:
            self.query_one(".balance-label", Label).update(new_balance_str)

    @property
    def needs_update(self) -> bool:
        if (new_balance := self.new_balance_input_milliunits) is None:
            return False

        return new_balance != self.balance_milliunits

    @property
    def account_update(self) -> AccountUpdate | None:
        if not self.needs_update:
            return None

        return AccountUpdate(
            account_id=self.account_id,
            account_name=self.account_name,
            new_balance=cast(int, self.new_balance_input_milliunits),
            old_balance=self.balance_milliunits,
            account_row=self,
        )

    def update_balance(self, new_balance: int | None = None):
        self.balance_label.loading = True

        if new_balance is None:
            # New balance needs to be derived
            self.update_balance_from_ynab()
            return

        self.balance_milliunits = new_balance
        self.balance_label.loading = False

    @work(thread=True, group="ynab_balance_update")
    async def update_balance_from_ynab(self):
        account = get().get_account_by_id(self.config.selected_budget.id, self.account_id)
        if account is None:
            raise AccountNotFound(f"The account with id {self.account_id!r} could not be found in YNAB.")
        self.balance_milliunits = account.balance
        self.balance_label.loading = False

    def push_new_balance(self, balance: str):
        new_balance = parse_currency_to_milliunits(balance)

        if new_balance is None:
            self.app.notify(f"Invalid currentcy format: {new_balance}", severity="error")
            return

        adjustment_amount = new_balance - self.balance_milliunits

        prompt = update_balance_text(
            self.account_name, self.balance_milliunits, new_balance, self.config.selected_budget.currency_format
        )

        def push_to_ynab(accept: bool | None):
            if not accept:
                self.balance_label.loading = False
                self.input_field.value = ""
                return

            get().create_transaction(
                budget_id=self.config.selected_budget.id,
                account_id=self.account_id,
                amount=adjustment_amount,
                cleared=self.config.adjustment_cleared_status,
                memo=self.config.adjustment_memo,
            )
            self.app.notify("Transaction created", severity="information")
            self.balance_milliunits = new_balance
            self.balance_label.loading = False
            self.input_field.value = ""

        self.app.push_screen(ConfirmModal("Confirm Balance Adjustment", prompt=prompt), push_to_ynab)

    def update_input_balance(self, new_balance: str):
        self.input_field.value = new_balance

    @property
    def balance_label(self) -> Label:
        return self.query_one(".balance-label", Label)

    @property
    def input_field(self) -> Input:
        return self.query_one(css_id(self.account_id, "account-input-"), Input)

    @property
    def new_balance_input_value(self) -> str:
        return self.input_field.value.strip()

    @property
    def new_balance_input_milliunits(self) -> int | None:
        return parse_currency_to_milliunits(self.input_field.value.strip())
