"""Configuration management for YNAB Updater."""

from __future__ import annotations

from contextlib import suppress
from enum import Enum
from functools import cached_property
from pathlib import Path
from typing import Self, assert_never

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_serializer, model_validator
from ynab.models.account import Account as YnabAccount
from ynab.models.account_type import AccountType
from ynab.models.budget_summary import BudgetSummary as YnabBudget

from ynab_updater.constats import DEFAULT_ADJUSTMENT_MEMO

# Determine config path (~/.config/ynab-updater/config.json)
CONFIG_FILE = Path.home() / ".config" / "ynab-updater" / "config.json"


class NetworthType(Enum):
    CASH = "Cash"
    SAVINGS = "Savings"
    DEBT = "Debt"
    ASSETS = "Assets"

    @staticmethod
    def from_account_type(account_type: AccountType) -> NetworthType:
        match account_type:
            case AccountType.CASH | AccountType.CHECKING:
                return NetworthType.CASH
            case AccountType.SAVINGS:
                return NetworthType.SAVINGS
            case (
                AccountType.CREDITCARD
                | AccountType.LINEOFCREDIT
                | AccountType.OTHERLIABILITY
                | AccountType.MORTGAGE
                | AccountType.AUTOLOAN
                | AccountType.STUDENTLOAN
                | AccountType.PERSONALLOAN
                | AccountType.MEDICALDEBT
                | AccountType.OTHERDEBT
            ):
                return NetworthType.DEBT
            case AccountType.OTHERASSET:
                return NetworthType.ASSETS
            case never:
                assert_never(never)


class ClearedStatus(Enum):
    CLEARED = "cleared"
    UNCLEARED = "uncleared"
    RECONCILED = "reconciled"


class ConfigError(Exception):
    pass


class AccountConfig(BaseModel):
    id: str
    name: str
    networth_type: NetworthType = NetworthType.CASH  # Default to cash and refresh on startup
    model_config = ConfigDict(extra="ignore")

    @staticmethod
    def from_api(account: YnabAccount) -> AccountConfig:
        networth_type = NetworthType.from_account_type(account_type=account.type)
        return AccountConfig(**account.model_dump(), networth_type=networth_type)


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


class DebtAccountMapping(BaseModel):
    debt_account_id: str
    mapping_accounts: list[str]


class NetWorthConfig(BaseModel):
    debt_assingmet: list[DebtAccountMapping]


class AppConfig(BaseModel):
    """Main application configuration model."""

    ynab_api_key: SecretStr | None = None
    budgets: list[Budget] = Field(default_factory=list)
    accounts: list[Account] = Field(default_factory=list)
    # Add fields for currency format
    adjustment_memo: str = DEFAULT_ADJUSTMENT_MEMO
    adjustment_cleared_status: ClearedStatus = ClearedStatus.CLEARED
    networth_config: NetWorthConfig = NetWorthConfig(debt_assingmet=[])

    @model_validator(mode="after")
    def fill_networth_config(self) -> Self:
        _asignment_ids = {debt.debt_account_id: debt for debt in self.networth_config.debt_assingmet}
        for account in self.accounts:
            if account.config.id not in _asignment_ids and account.config.networth_type is NetworthType.DEBT:
                self.networth_config.debt_assingmet.append(
                    DebtAccountMapping(debt_account_id=account.config.id, mapping_accounts=[])
                )
        return self

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
        # Reload the config to ensure any validator runs over the new data
        self.__init__(**self.model_dump())
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
        ids = {acc.config.id: acc for acc in self.accounts}

        _accounts: list[Account] = []
        for account in accounts:
            selected = ids[account.id].selected if account.id in ids else False
            _accounts.append(Account(config=AccountConfig.from_api(account), selected=selected))

        self.accounts = _accounts

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

    def debt_mapping_by_account_id(self, account_id: str) -> DebtAccountMapping:
        try:
            return next(
                debt_mapping
                for debt_mapping in self.networth_config.debt_assingmet
                if debt_mapping.debt_account_id == account_id
            )
        except StopIteration as e:
            raise ValueError(f"There is no debt mapping for account with id {account_id!r}") from e

    def debt_account_mapped_to_account_id(self, account_id: str) -> list[str]:
        return [
            debt_mapping.debt_account_id
            for debt_mapping in self.networth_config.debt_assingmet
            if account_id in debt_mapping.mapping_accounts
        ]

    def add_account_to_debt_mapping(self, account_id: str, debt_account_id: str):
        debt_mapping = self.debt_mapping_by_account_id(debt_account_id)
        debt_mapping.mapping_accounts.append(account_id)

    def is_account_mapped_to_debt_account(self, account_id: str, debt_account_id: str) -> bool:
        return debt_account_id in self.debt_account_mapped_to_account_id(account_id)


def _ensure_config_dir_exists(config_dir: Path):
    """Creates the configuration directory if it doesn't exist."""
    config_dir.mkdir(parents=True, exist_ok=True)
