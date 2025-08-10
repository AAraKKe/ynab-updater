from __future__ import annotations

from typing import TYPE_CHECKING

from textual import on
from textual.containers import Horizontal
from textual.reactive import var
from textual.widgets import Button, Label, SelectionList
from textual.widgets.selection_list import Selection

from ynab_updater.config import NetworthType

if TYPE_CHECKING:
    # Revert to absolute imports for type checking
    from ynab_updater.config import AppConfig


class SelectableLabel(Label):
    selected = var(False)

    def select(self):
        self.selected = True

    def deselect(self):
        self.selected = False

    def watch_selected(self, old_value: bool, new_value: bool):
        if new_value:
            self.add_class()


class DebtAccountMappingRow(Horizontal):
    def __init__(self, account_id: str, config: AppConfig):
        self.config = config
        self.mapping = self.config.debt_mapping_by_account_id(account_id)

        super().__init__()

    def compose(self):
        with Horizontal(id="debt-account-mapping-row-container"):
            yield Label(self.config.account_by_id(self.mapping.debt_account_id).config.name)
            yield Label("—-— Mapped to accounts ———>", classes="dim")
            yield Label(self.selected_accounts_str, id="selected-accounts-label")
        with Horizontal(id="interactive-horizontal"):
            yield SelectionList()
            yield Button("Select Accounts", id="add-mapped-account")

    @property
    def selected_accounts_str(self) -> str:
        return ", ".join(
            self.config.account_by_id(account_id).config.name for account_id in self.mapping.mapping_accounts
        )

    def on_mount(self):
        selection_list = self.query_one(SelectionList)
        selection_list.display = False

    def build_selection_list(self):
        accounts = [
            account for account in self.config.accounts if account.config.networth_type is not NetworthType.DEBT
        ]

        selection_list = self.query_one(SelectionList)
        selection_list.clear_options()
        for account in accounts:
            is_own = account.config.id in self.mapping.mapping_accounts
            is_disabled = not is_own and len(self.config.debt_account_mapped_to_account_id(account.config.id)) > 0
            select_value = account.config.name
            select_key = account.config.id

            selection_list.add_option(Selection(select_value, select_key, is_own, disabled=is_disabled))

    def on_button_pressed(self, event: Button.Pressed):
        if event.button.id != "add-mapped-account":
            return

        selection_list = self.query_one(SelectionList)
        if selection_list.display:
            selection_list.display = False
            event.button.label = "Select Accounts"
        else:
            self.build_selection_list()
            selection_list.display = True
            event.button.label = "Save Selection"

    @on(SelectionList.SelectedChanged)
    def on_selection_changed(self, message: SelectionList.SelectedChanged):
        self.mapping.mapping_accounts = message.selection_list.selected
        self.query_one("#selected-accounts-label", Label).update(self.selected_accounts_str)
