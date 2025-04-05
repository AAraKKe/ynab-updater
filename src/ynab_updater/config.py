"""Configuration management for YNAB Updater."""

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, SecretStr, field_validator

# Define the possible cleared statuses matching YNAB API
ClearedStatus = Literal["cleared", "uncleared", "reconciled"]


class AccountConfig(BaseModel):
    """Configuration for a single YNAB account to track."""

    id: str = Field(..., description="The YNAB account ID.")
    name: str = Field(..., description="The name of the YNAB account.")
    # Add any other necessary fields retrieved from YNAB API if needed later
    # e.g., type, on_budget, etc.


class AppConfig(BaseModel):
    """Main application configuration model."""

    ynab_api_key: SecretStr | None = None
    selected_budget_id: str | None = None
    selected_budget_name: str | None = None
    selected_accounts: list[AccountConfig] = Field(default_factory=list)
    # Add fields for currency format
    currency_symbol: str | None = "$"  # Default to $ if not found
    currency_decimal_digits: int = 2  # Default
    currency_symbol_first: bool = True  # Default ($1.00 vs 1.00$)
    adjustment_memo: str = "Balance adjustment by YNAB Updater"
    adjustment_cleared_status: ClearedStatus = "cleared"

    @field_validator("adjustment_cleared_status")
    @classmethod
    def check_cleared_status(cls, value: str) -> str:
        if value in {"cleared", "uncleared", "reconciled"}:
            return value

        raise ValueError("Invalid cleared status. Must be 'cleared', 'uncleared', or 'reconciled'.")


# Determine config path (~/.config/ynab-updater/config.json)
CONFIG_DIR = Path.home() / ".config" / "ynab-updater"
CONFIG_FILE = CONFIG_DIR / "config.json"


def ensure_config_dir_exists():
    """Creates the configuration directory if it doesn't exist."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)


def load_config() -> AppConfig:
    """Loads the application configuration from the JSON file."""
    ensure_config_dir_exists()
    if not CONFIG_FILE.exists():
        return AppConfig()  # Return default config if file doesn't exist
    try:
        with open(CONFIG_FILE) as f:
            config_data = json.load(f)
            # Handle SecretStr deserialization if needed
            if "ynab_api_key" in config_data and config_data["ynab_api_key"]:
                config_data["ynab_api_key"] = SecretStr(config_data["ynab_api_key"])
            return AppConfig.model_validate(config_data)
    except (json.JSONDecodeError, FileNotFoundError, TypeError, ValueError) as e:
        # Handle potential errors during loading (e.g., corrupted file)
        # Log this error appropriately later
        print(f"Error loading config: {e}. Using default configuration.")
        return AppConfig()


def save_config(config: AppConfig):
    """Saves the application configuration to the JSON file."""
    ensure_config_dir_exists()
    try:
        # Handle SecretStr serialization
        config_dict = config.model_dump()
        # Check if api key exists before trying to get its secret value
        if config.ynab_api_key is not None:
            # Store the plain string in the JSON
            config_dict["ynab_api_key"] = config.ynab_api_key.get_secret_value()
        else:
            config_dict["ynab_api_key"] = None  # Ensure it's explicitly null if not set

        # Ensure new budget fields are included even if None
        config_dict.setdefault("selected_budget_id", None)
        config_dict.setdefault("selected_budget_name", None)
        # Handle currency fields
        config_dict.setdefault("currency_symbol", "$")
        config_dict.setdefault("currency_decimal_digits", 2)
        config_dict.setdefault("currency_symbol_first", True)

        with open(CONFIG_FILE, "w") as f:
            json.dump(config_dict, f, indent=4)
    except OSError as e:
        # Handle potential errors during saving
        # Log this error appropriately later
        print(f"Error saving config: {e}")
