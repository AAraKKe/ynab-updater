from __future__ import annotations

from collections.abc import Generator
from itertools import groupby
from typing import TYPE_CHECKING

from textual import work
from textual.containers import Container, Grid, Vertical
from textual.message import Message
from textual.reactive import var
from textual.widgets import Digits, Static, TabbedContent, TabPane, Tree
from wcwidth import wcswidth

from ynab_updater.config import AppConfig
from ynab_updater.utils import format_balance
from ynab_updater.ynab_client import NetWorthResult, NetworthType, get

if TYPE_CHECKING:
    from ynab_updater.config import CurrencyFormat
    from ynab_updater.ynab_client import RelativeNetWorth


class AssetsLiabilities(Vertical):
    def __init__(self, networth: NetWorthResult, currency_format: CurrencyFormat):
        super().__init__()
        self.networth = networth
        self.currency_format = currency_format
        # A mapping to make updates easier
        self.category_map = {
            "Assets": ("assets-balance", "assets-weight"),
            "Savings": ("savings-balance", "savings-weight"),
            "Cash": ("cash-balance", "cash-weight"),
            "Debt": ("debt-balance", "debt-weight"),
        }

    def compose(self):
        """Compose a 2x2 grid of stat cards."""
        with Grid(id="stats-grid"):
            with Vertical(classes="stat-card"):
                yield Static("Assets", classes="stat-title")
                yield Static("...", id="assets-balance")
                yield Static("...", id="assets-weight")
            with Vertical(classes="stat-card"):
                yield Static("Savings", classes="stat-title")
                yield Static("...", id="savings-balance")
                yield Static("...", id="savings-weight")
            with Vertical(classes="stat-card"):
                yield Static("Cash", classes="stat-title")
                yield Static("...", id="cash-balance")
                yield Static("...", id="cash-weight")
            with Vertical(classes="stat-card"):
                yield Static("Debt", classes="stat-title")
                yield Static("...", id="debt-balance")
                yield Static("...", id="debt-weight")

    def on_mount(self):
        self.update()

    def update(self):
        data = {item[0].value: (item[1], item[2]) for item in self.groups()}

        for category, (balance_id, weight_id) in self.category_map.items():
            ratio, balance = data.get(category, (0.0, 0))

            formatted_balance = format_balance(balance, self.currency_format)
            formatted_ratio = f"{ratio:.2%}"

            style = "green" if category != "Debt" else "red"

            self.query_one(f"#{balance_id}", Static).update(f"[{style}]{formatted_balance}[/]")
            self.query_one(f"#{weight_id}", Static).update(f"Weight: {formatted_ratio}")

        self.set_loading(False)

    def groups(self) -> Generator[tuple[NetworthType, float, int]]:
        sorted_by_type = sorted(self.networth.relative_net_worth(), key=lambda nw: nw["type"].value)

        aggregated_groups = []
        for group, elements_iterator in groupby(sorted_by_type, lambda nw: nw["type"]):
            elements_list = list(elements_iterator)

            ratio_sum = sum(element["ratio"] for element in elements_list)
            balance_sum = sum(element["balance"] for element in elements_list)

            aggregated_groups.append((group, ratio_sum, balance_sum))

        yield from sorted(
            aggregated_groups,
            key=lambda pair: pair[1],
            reverse=True,
        )

    def set_loading(self, value: bool):
        for card in self.query(".stat-card"):
            card.loading = value


def _sort_accounts(accounts: list, order_map: dict) -> list:
    return sorted(accounts, key=lambda x: (order_map.get(x["type"], 99), -x["ratio"]))


def _format_category_label(category: NetworthType, emoji: str, width: int) -> str:
    label_text = f"{emoji} {category.value}"
    display_width = wcswidth(label_text)
    padding = " " * (width - display_width)
    return f"{label_text}{padding}"


def _format_account_label(account: RelativeNetWorth, currency_format: CurrencyFormat, width: int) -> str:
    raw_name = account["account"]
    balance_str = format_balance(account["balance"], currency_format)
    ratio_str = f"{account['ratio']:.2%}"
    style = "green" if account["balance"] >= 0 else "red"

    display_width = wcswidth(raw_name)
    padding = " " * (width - display_width)
    padded_name = f"{raw_name}{padding}"

    return f"{padded_name} [{style}]{balance_str:>15}[/] [dim]{ratio_str:>8}[/]"


class AccountsBreakdown(Vertical):
    CATEGORY_ORDER = [NetworthType.ASSETS, NetworthType.SAVINGS, NetworthType.CASH, NetworthType.DEBT]

    def __init__(self, networth: NetWorthResult, currency_format: CurrencyFormat):
        super().__init__()
        self.networth = networth
        self.currency_format = currency_format
        self.order_map = {category: i for i, category in enumerate(self.CATEGORY_ORDER)}

    def compose(self):
        yield Tree("Accounts", id="accounts-tree")

    def on_mount(self):
        self.update()

    def update(self):
        tree = self.query_one(Tree)
        tree.clear()
        tree.root.expand()

        NAME_COLUMN_WIDTH = 32
        emoji_map = {
            NetworthType.ASSETS: "💰",
            NetworthType.SAVINGS: "🏦",
            NetworthType.CASH: "💵",
            NetworthType.DEBT: "💳",
        }

        sorted_accounts = _sort_accounts(self.networth.relative_net_worth(), self.order_map)

        for category, accounts in groupby(sorted_accounts, key=lambda x: x["type"]):
            emoji = emoji_map.get(category, "📁")

            category_label = _format_category_label(category, emoji, NAME_COLUMN_WIDTH)
            category_node = tree.root.add(category_label, expand=True)

            for account in accounts:
                account_label = _format_account_label(account, self.currency_format, NAME_COLUMN_WIDTH)
                category_node.add_leaf(account_label)

        self.set_loading(False)

    def set_loading(self, value: bool):
        self.query_one(Tree).loading = value


class NetWorth(Container):
    total_net_worth = var(0)

    class DataLoaded(Message):
        def __init__(self, networth_data: NetWorthResult):
            self.networth_data = networth_data
            super().__init__()

    def __init__(self, config: AppConfig):
        super().__init__()
        self.config = config
        self.networth = NetWorthResult([], [], [], [])
        self.total_net_wroth_str = format_balance(self.total_net_worth, self.config.selected_budget.currency_format)

    def compose(self):
        yield Static("Net Worth", id="net-worth-title")
        yield Digits(self.total_net_wroth_str, name="Total Net Worth", id="net-worth-value")
        with TabbedContent(initial="networth-assets-liabilities"):
            with TabPane("Overview", id="networth-assets-liabilities"):
                yield AssetsLiabilities(self.networth, self.config.selected_budget.currency_format)
            with TabPane("Accounts", id="accounts"):
                yield AccountsBreakdown(self.networth, self.config.selected_budget.currency_format)

    def on_mount(self):
        self.update_networth()

    def update_networth(self):
        self.query_one(Digits).loading = True
        self.query_one(AssetsLiabilities).set_loading(True)
        self.query_one(AccountsBreakdown).set_loading(True)
        self.load_networth_result()

    @work(thread=True)
    def load_networth_result(self):
        networth_data = get().net_worth(self.config.selected_budget.id)
        self.post_message(self.DataLoaded(networth_data))

    def on_net_worth_data_loaded(self, message: NetWorth.DataLoaded):
        self.networth.update(message.networth_data)

        self.total_net_worth = self.networth.net_wroth()
        self.query_one(Digits).loading = False

        self.query_one(AssetsLiabilities).update()
        self.query_one(AccountsBreakdown).update()

    def watch_total_net_worth(self, old_value: int, new_value: int):
        if self.is_mounted:
            self.total_net_wroth_str = format_balance(new_value, self.config.selected_budget.currency_format)
            self.query_one(Digits).update(self.total_net_wroth_str)
            self.query_one(AssetsLiabilities).update()
            self.query_one(AccountsBreakdown).update()
