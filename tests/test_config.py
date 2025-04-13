from pathlib import Path

import pytest

from ynab_updater.config import Account, AccountConfig, AppConfig, ClearedStatus, ConfigError


def test_load_valid_json(config_file: Path):
    config = AppConfig.load(config_file)

    # Some properties
    assert len(config.accounts) == 3
    assert len(config.budgets) == 3
    assert config.ynab_api_key is not None
    assert config.ynab_api_key.get_secret_value() == "mykey"
    assert config.accounts[0].config.name == "Account 1"
    assert config.accounts[1].config.name == "Account 2"
    assert config.accounts[0].selected is True
    assert config.accounts[2].selected is False
    assert config.adjustment_cleared_status is ClearedStatus.CLEARED

    # Cached properties
    assert len(config.selected_accounts) == 2
    accs = list(config.selected_accounts)
    assert accs[0].name == "Account 1"
    assert accs[1].name == "Account 2"

    assert config.has_selected_budget
    budget = config.selected_budget
    assert budget.name == "Budget 2"


@pytest.mark.parametrize(
    "config_file,expected_error",
    [
        (
            "config_no_budgets.json",
            "No selected budgets",
        ),
        (
            "config_multiple_selected_budgets.json",
            "Unexpected Error: More than 1 selected budgets",
        ),
        (
            "config_incomplete_budget.json",
            "1 validation error for AppConfig",
        ),
        (
            "config_invalid_cleared_status.json",
            "Input should be 'cleared', 'uncleared' or 'reconciled'",
        ),
    ],
    ids=["no_budgets", "multiple_selected_budgets", "incomplete_budget_config", "invalid_cleared_status"],
)
def test_invalid_config_files(config_file: str, expected_error: str, assets: Path):
    config_path = assets / config_file
    with pytest.raises(ConfigError) as exc_info:
        config = AppConfig.load(config_path)
        _ = config.selected_budget
        _ = config.selected_accounts
    assert expected_error in str(exc_info.value)


def test_load_file_does_not_exist(tmp_path: Path):
    config_path = tmp_path / "non_existent_file.json"
    config = AppConfig.load(config_path)
    assert config is not None
    assert config.ynab_api_key is None
    assert config.accounts == []
    assert config.budgets == []
    assert config.adjustment_cleared_status is ClearedStatus.CLEARED


def test_save_config(tmp_path: Path, config_file: Path):
    config = AppConfig.load(config_file)

    config.adjustment_cleared_status = ClearedStatus.RECONCILED

    config.save(tmp_path / "newconfig.json")

    new_config = AppConfig.load(tmp_path / "newconfig.json")
    assert new_config.adjustment_cleared_status is ClearedStatus.RECONCILED


def test_refresh_clears_cached_properties(tmp_path: Path):
    config = AppConfig.load(tmp_path / "config.json")

    assert config.selected_accounts == []

    config.accounts.append(Account(config=AccountConfig(id="1", name="Test Account"), selected=True))
    config.accounts.append(Account(config=AccountConfig(id="2", name="Test Account 2"), selected=False))

    assert config.selected_accounts == []
    config.refresh()
    accs = config.selected_accounts
    assert len(accs) == 1
    assert accs[0].name == "Test Account"
