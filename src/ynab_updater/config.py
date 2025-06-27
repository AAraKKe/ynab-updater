"""Configuration management for YNAB Updater."""

from __future__ import annotations

from contextlib import suppress
from enum import Enum
from functools import cached_property
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_serializer
from ynab.models.account import Account as YnabAccount
from ynab.models.budget_summary import BudgetSummary as YnabBudget

from ynab_updater.constats import DEFAULT_ADJUSTMENT_MEMO

# Determine config path (~/.config/ynab-updater/config.json)
CONFIG_FILE = Path.home() / ".config" / "ynab-updater" / "config.json"


class ClearedStatus(Enum):
    CLEARED = "cleared"
    UNCLEARED = "uncleared"
    RECONCILED = "reconciled"


class ConfigError(Exception):
    pass


class AccountConfig(BaseModel):
    id: str
    name: str

    model_config = ConfigDict(extra="ignore")

    @staticmethod
    def from_api(account: YnabAccount) -> AccountConfig:
        return AccountConfig(**account.model_dump())


class Account(BaseModel):
    config: AccountConfig
    selected: bool = False


class CurrencyFormat(BaseModel):
    decimal_digits: int
    decimal_separator: str
    group_separator: str
    symbol_first: bool
    currency_symbol: str

    model_config = ConfigDict(extra="ignore")


class BudgetConfig(BaseModel):
    id: str
    name: str
    currency_format: CurrencyFormat

    model_config = ConfigDict(extra="ignore")

    @staticmethod
    def from_api(budget: YnabBudget) -> BudgetConfig:
        return BudgetConfig(**budget.model_dump())


class Budget(BaseModel):
    config: BudgetConfig
    selected: bool = False


class AppConfig(BaseModel):
    """Main application configuration model."""

    ynab_api_key: SecretStr | None = None
    budgets: list[Budget] = Field(default_factory=list)
    accounts: list[Account] = Field(default_factory=list)
    # Add fields for currency format
    adjustment_memo: str = DEFAULT_ADJUSTMENT_MEMO
    adjustment_cleared_status: ClearedStatus = ClearedStatus.CLEARED

    @field_serializer("ynab_api_key")
    def serialize_key(self, ynab_api_key: SecretStr | None) -> str:
        return "" if ynab_api_key is None else ynab_api_key.get_secret_value()

    @cached_property
    def has_selected_budget(self) -> bool:
        return len([b.config for b in self.budgets if b.selected]) != 0

    @cached_property
    def ynab_budgets(self) -> list[BudgetConfig]:
        return [b.config for b in self.budgets]

    @cached_property
    def selected_budget(self) -> BudgetConfig:
        selected_budgets = [b.config for b in self.budgets if b.selected]
        match len(selected_budgets):
            case 0:
                raise ConfigError("No selected budgets")
            case 1:
                return next(b.config for b in self.budgets if b.selected)
            case _:
                raise ConfigError("Unexpected Error: More than 1 selected budgets")

    @cached_property
    def selected_accounts(self) -> list[AccountConfig]:
        return [a.config for a in self.accounts if a.selected]

    @cached_property
    def has_selected_accounts(self) -> bool:
        return len(self.selected_accounts) > 0

    @staticmethod
    def load(config_file=CONFIG_FILE) -> AppConfig:
        _ensure_config_dir_exists(config_file.parent)
        try:
            if config_file.exists():
                return AppConfig.model_validate_json(config_file.read_text())
            return AppConfig()
        except (FileNotFoundError, TypeError, ValueError) as e:
            raise ConfigError(str(e)) from e

    def is_valid(self) -> bool:
        """Returns true if we have a valid api key and Budget"""
        return self.ynab_api_key is not None and self.has_selected_budget

    def save(self, config_file=CONFIG_FILE):
        _ensure_config_dir_exists(config_file.parent)
        config_file.write_text(self.model_dump_json())

    def refresh(self):
        """Saves and clears cached properties."""
        self.save()
        # Clear cached properties if they have been defined already
        with suppress(AttributeError):
            del self.selected_budget
        with suppress(AttributeError):
            del self.selected_accounts
        with suppress(AttributeError):
            del self.has_selected_budget

    def add_budgets_from_api(self, budgets: list[YnabBudget]):
        self.budgets = [Budget(config=BudgetConfig.from_api(budget), selected=False) for budget in budgets]

    def add_accounts_from_api(self, accounts: list[YnabAccount]):
        ids = {acc.config.id for acc in self.accounts}

        for account in accounts:
            if account.id in ids:
                continue

            self.accounts.append(Account(config=AccountConfig.from_api(account), selected=False))

    def budget_by_id(self, id: str) -> Budget:
        selected = [b for b in self.budgets if b.config.id == id]

        if not selected:
            raise ValueError(f"There is no budget with id {id!r}")

        if len(selected) > 1:
            raise ValueError(f"More than one budgets found with id {id!r}")

        return selected[0]

    def account_by_id(self, id: str) -> Account:
        selected = [a for a in self.accounts if a.config.id == id]

        if not selected:
            raise ValueError(f"There is no account with id {id!r}")

        if len(selected) > 1:
            raise ValueError(f"More than one account found with id {id!r}")

        return selected[0]


def _ensure_config_dir_exists(config_dir: Path):
    """Creates the configuration directory if it doesn't exist."""
    config_dir.mkdir(parents=True, exist_ok=True)
