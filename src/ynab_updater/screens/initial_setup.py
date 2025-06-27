import asyncio
from typing import cast

from pydantic import SecretStr
from textual import work
from textual.message import Message
from textual.screen import Screen

from ynab_updater.config import Account, AppConfig, Budget, ConfigError
from ynab_updater.modals import AccountSelectModal, APIKeyModal, BudgetSelectModal
from ynab_updater.ynab_client import get, set


class InitScreen(Screen[AppConfig]):
    class Dismissed(Message):
        pass

    def __init__(self):
        self.config: AppConfig | None = None
        super().__init__()

    def on_mount(self):
        # First we check if AppConfig is valid and if not we start
        # prompting the user to get the information we need.
        self.config = None
        try:
            if config := AppConfig.load():
                self.config = config
                if not self.config.is_valid():
                    raise ConfigError()
                assert self.config.ynab_api_key is not None
                set(self.config.ynab_api_key, self.app.log)
                self.call_later(self.refresh_accounts)
        except ConfigError:
            self.get_initial_setup()

    @property
    def safe_config(self) -> AppConfig:
        if self.config is None:
            import traceback

            self.notify("Trying to access AppConfig when it has not yet been set.")
            stack_trace = "".join(traceback.format_stack())
            self.log.error(f"AppConfig was accessed before it was set.\n{stack_trace}")
            self.app.exit(1)
        return cast(AppConfig, self.config)

    @work
    async def get_initial_setup(self):
        """Check for API key and account selection on startup."""
        self.log.info("Configuration not valid. Prompting user for details...")
        # Sound hot happen but ensure it is not None
        if self.config is None:
            self.config = AppConfig.load()

        action_to_take = None
        if not self.config.ynab_api_key:
            self.log.info("API key not found, prompting user.")
            action_to_take = self.prompt_for_api_key
        elif not self.config.has_selected_budget:
            self.log.info("Budget not selected, prompting user.")
            action_to_take = self.prompt_for_budget
        elif not self.config.selected_accounts:
            self.log.info("No accounts selected, prompting user.")
            action_to_take = self.prompt_for_accounts
        else:
            self.log.info("Getting all accounts available in the budget")
            action_to_take = self.refresh_accounts

        await action_to_take()

    async def prompt_for_api_key(self):
        """Displays the modal to get the YNAB API key."""

        async def check_api_key(api_key: str | None):
            if api_key is None:
                self.notify("API Key setup cancelled.", severity="warning")
                await asyncio.sleep(2)
                self.app.exit()

            assert self.config is not None
            assert api_key is not None

            self.config.ynab_api_key = SecretStr(api_key)
            self.config.refresh()

            set(self.config.ynab_api_key, self.app.log)

            # Continue with the budget selection
            self.call_later(self.prompt_for_budget)

        await self.app.push_screen(APIKeyModal(), check_api_key, wait_for_dismiss=True)

    async def prompt_for_budget(self):
        """Fetches budgets and prompts user to select one."""
        self.loading = True

        self.log.info("Fetching budgets...")
        budgets = get().get_budgets()

        if budgets is None:
            self.notify("No budgets found for the supplied API Key.", severity="error")
            await asyncio.sleep(2)
            self.app.exit(1)
            return

        if not budgets:
            self.notify("No budgets found. Check API key or YNAB status.", severity="error")
            self.app.exit(1)
            return

        assert self.config is not None

        self.config.add_budgets_from_api(budgets)
        self.config.refresh()

        # Define the callback for when a budget is selected
        async def save_selected_budget(selected_budget: Budget | None):
            if selected_budget is None:
                self.notify("Budget selection cancelled.", severity="warning")
                return

            assert self.config is not None

            # Set the selected label
            selected_budget.selected = True

            self.save_accounts(selected_budget.config.id)

            self.config.refresh()
            self.notify(f"Budget '{selected_budget.config.name}' selected.", severity="information")
            # Now prompt for accounts
            # self.set_loading(True)
            self.call_later(self.prompt_for_accounts)

        # Show the budget selection modal
        self.loading = True
        await self.app.push_screen(BudgetSelectModal(self.config.budgets), save_selected_budget)
        self.loading = False

    def save_accounts(self, budget_id: str):
        accounts = get().get_accounts(budget_id=budget_id)

        assert self.config is not None
        self.config.add_accounts_from_api(accounts)
        self.config.refresh()

    async def prompt_for_accounts(self):
        if self.safe_config.has_selected_accounts:
            # If we already have selected accounts, lets not prompt
            return

        async def save_selected_accounts(
            selected: list[Account] | None,
        ):
            if not selected:
                self.notify(
                    "Account selection cancelled or no accounts chosen.",
                    severity="warning",
                )
            else:
                for account in selected:
                    account.selected = True

                self.notify(f"{len(selected)} accounts selected.", severity="information")
                self.safe_config.refresh()

            # Here we are done and can dismiss the init screen
            self.dismiss(self.config)

        await self.app.push_screen(
            AccountSelectModal(self.safe_config.accounts),
            save_selected_accounts,
        )

    async def refresh_accounts(self):
        assert self.config is not None
        self.log.info("Refreshing accounts from YNAB...")
        self.save_accounts(self.config.selected_budget.id)
        self.config.refresh()
        self.dismiss(self.config)
