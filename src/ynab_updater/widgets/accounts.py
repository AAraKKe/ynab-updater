from collections.abc import Generator
from functools import cached_property

from textual import on
from textual.app import ComposeResult
from textual.containers import Container, VerticalScroll
from textual.css.query import NoMatches
from textual.reactive import reactive
from textual.widgets import Static

from ynab_updater.config import AppConfig
from ynab_updater.utils import css_id

from .account_row import AccountRow, AccountUpdate


class Accounts(Container):
    is_loading: reactive[bool] = reactive(True)

    def __init__(self, config: AppConfig, accounts: list[AccountRow] | None = None):
        self.default_accounts = accounts
        self.config = config
        super().__init__()

    def compose(self) -> ComposeResult:
        yield Static("Accounts", id="accounts-title")
        with VerticalScroll(id="accounts-list-container"):
            if self.default_accounts is not None:
                yield from self.default_accounts

    def on_mount(self):
        self.populate_accounts()

    @on(AccountRow.AccountRowMounted)
    def on_account_row_mounted(self, event: AccountRow.AccountRowMounted):
        event.row.balance_label.loading = True
        event.row.update_balance()

    def populate_accounts(self):
        for account in sorted(self.config.selected_accounts, key=lambda acc: acc.name):
            account_row = AccountRow(
                account_id=account.id,
                account_name=account.name,
                current_balance=0,
                format=self.config.selected_budget.currency_format,
                config=self.config,
            )
            # Once the account row is mounted it will send a message that signals
            # it is ready to operate
            self.add_account(account_row)

    @cached_property
    def accounts_container(self) -> VerticalScroll:
        container = self.query_one("#accounts-list-container", VerticalScroll)
        # Cannot be None because NoMatches would be raised
        assert container is not None
        return container

    @property
    def accounts(self) -> Generator[AccountRow]:
        yield from self.query(AccountRow)

    def add_account(self, account: AccountRow):
        self.accounts_container.mount(account)

    async def clear_account_rows(self):
        await self.accounts_container.remove_children()

    async def refresh_accounts(self):
        await self.clear_account_rows()
        self.populate_accounts()

    def update_account(self, account: AccountRow):
        try:
            selected_account = self.query_one(css_id(account), AccountRow)
            self.log.debug(f"Account found: {selected_account}")
            selected_account.balance_milliunits = account.balance_milliunits
            selected_account.account_name = account.account_name
            self.log.debug(f"Balance udpated: {account.balance_milliunits}")
            self.log.debug(f"Name updated:    {account.account_name}")
        except NoMatches:
            # The account is not there yet
            self.add_account(account)

    @property
    def accounts_to_update(self) -> Generator[AccountUpdate]:
        for account_row in self.accounts:
            if (account_update := account_row.account_update) is not None:
                yield account_update
