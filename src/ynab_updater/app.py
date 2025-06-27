"""Main application screen and configuration screen."""

from collections.abc import Callable
import logging

from pydantic import SecretStr
from rich.text import Text
from textual import on, work
from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, VerticalScroll
from textual.reactive import var
from textual.widgets import Button, Footer, Header, LoadingIndicator, Static

from .config import CONFIG_FILE, Account, AppConfig
from .modals import AccountSelectModal, APIKeyModal, BudgetSelectModal, ConfirmModal, create_bulk_update_prompt
from .screens import ConfigScreen
from .utils import format_currency, parse_currency_to_milliunits
from .widgets import AccountRow
from .ynab_client import Account as YnabAccount
from .ynab_client import BudgetSummary, YNABClientError, YnabHandler


class YnabUpdater(App[None]):
    """The main YNAB Updater application."""

    TITLE = "YNAB Updater"
    SUB_TITLE = "Quickly update account balances"
    CSS_PATH = "app.tcss"
    BINDINGS = [
        ("ctrl+q", "quit", "Quit"),
        ("ctrl+r", "refresh_balances", "Refresh Balances"),
        ("f10", "reset_config_and_exit", "Reset Config (F10)"),
    ]

    config: var[AppConfig] = var(AppConfig.load)
    accounts_data: var[dict[str, YnabAccount]] = var({})
    is_loading: var[bool] = var(False)
    ynab_handler: var[YnabHandler | None] = var(None)

    def compose(self) -> ComposeResult:
        yield Header()
        with Container(id="main-container"):
            yield Static("Accounts", id="accounts-title")
            yield LoadingIndicator(id="loading-indicator")
            with VerticalScroll(id="accounts-list-container"):
                # AccountRows will be added here dynamically
                pass
            with Container(id="button-bar"):
                # Place Config button directly, it will be docked left by CSS
                yield Button("Config", id="config")
                # Wrap right buttons in a Horizontal container again
                with Horizontal(id="right-button-group"):
                    yield Button("Refresh Balances", id="refresh-balances", variant="default")
                    yield Button("Update All", id="update-all", variant="primary")
        yield Footer()

    def on_mount(self):
        """Called when the app is first mounted."""
        self.set_loading(True)
        # Run the async setup logic in a worker
        self.check_initial_setup()

    def set_loading(self, loading: bool):
        """Show/hide loading indicator and disable/enable buttons."""
        self.is_loading = loading
        indicator = self.query_one(LoadingIndicator)
        indicator.display = loading
        # Disable/enable action buttons while loading
        # for button_id in ["refresh-balances", "update-all", "config"]:
        #     with contextlib.suppress(Exception):
        #         self.query_one(f"#{button_id}", Button).disabled = loading
        # # Also disable individual account update buttons
        # for row in self.query(AccountRow):
        #     with contextlib.suppress(Exception):
        #         row.query_one(Button).disabled = loading

    @work
    async def check_initial_setup(self):
        """Check for API key and account selection on startup."""
        self.log.info("Checking initial setup...")
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
            self.log.info("Configuration found, loading accounts.")
            # Schedule loading on the main thread
            action_to_take = self.load_budget_and_accounts

        # Schedule the determined action (if any) and final loading state update
        if action_to_take is not None:
            await action_to_take()
        else:
            self.set_loading(False)

    def call_ynab[**P, R](self, callback: Callable[P, R], *args: P.args, **kwargs: P.kwargs) -> R | None:
        return_value = None

        try:
            return_value = callback(*args, **kwargs)
        except Exception as e:
            self.notify(f"There was an error communicating with YNAB: {e}")

        return return_value

    def _initialize_ynab_handler(self) -> bool:
        """Initializes the YNAB handler if possible. Returns True on success."""
        if self.ynab_handler:
            return True

        if self.config.ynab_api_key:
            try:
                self.ynab_handler = YnabHandler(self.config.ynab_api_key, logger=self.log)
                self.log.info("YnabHandler initialized.")
                return True
            except ValueError as e:
                return self._handle_initialization_error(e)
        else:
            # This should ideally not be reached if setup flow is correct
            self.log.warning("Attempted to initialize YnabHandler without API key.")
            self.call_later(self.prompt_for_api_key)
            return False

    def _handle_initialization_error(self, e: ValueError):
        self.log.error(f"Failed to initialize YnabHandler: {e}")
        self.notify(f"API Key Error: {e}", severity="error")
        # Reset key if initialization fails
        self.config.ynab_api_key = None
        self.config.refresh()
        self.call_later(self.prompt_for_api_key)
        return False

    async def prompt_for_api_key(self):
        """Displays the modal to get the YNAB API key."""

        async def check_api_key(api_key: str | None):
            if not api_key:
                self.notify("API Key setup cancelled.", severity="warning")
                self.exit()
                return

            self.config.ynab_api_key = SecretStr(api_key)
            self.config.refresh()

            if self._initialize_ynab_handler():
                self.notify("API Key saved!", severity="information")
                # Now prompt for BUDGET
                self.set_loading(True)
                self.call_later(self.prompt_for_budget)

        await self.push_screen(APIKeyModal(), check_api_key)

    async def prompt_for_budget(self):
        """Fetches budgets and prompts user to select one."""
        if not self._initialize_ynab_handler():
            self.set_loading(False)
            return

        assert self.ynab_handler is not None

        self.set_loading(True)

        self.log.info("Fetching budgets...")
        budgets = self.call_ynab(self.ynab_handler.get_budgets, include_accounts=True)

        if budgets is None:
            self.set_loading(False)
            return

        if not budgets:
            self.notify("No budgets found. Check API key or YNAB status.", severity="error")
            self.set_loading(False)
            return

        self.config.add_budgets_from_api(budgets)
        self.config.refresh()

        # Define the callback for when a budget is selected
        async def save_selected_budget(selected_budget: BudgetSummary | None):
            if selected_budget is None:
                self.notify("Budget selection cancelled.", severity="warning")
                self.set_loading(False)
                return

            # Set the selected label
            self.config.budget_by_id(selected_budget.id).selected = True

            # Load accounts for this budget
            if selected_budget.accounts is not None:
                if not selected_budget.accounts:
                    self.notify(f"The budget {selected_budget.name!r} has no accounts", severity="error")
                self.config.add_accounts_from_api(
                    [account for account in selected_budget.accounts if not account.closed]
                )

            self.config.refresh()
            self.notify(f"Budget '{selected_budget.name}' selected.", severity="information")
            # Now prompt for accounts
            self.set_loading(True)
            self.call_later(self.prompt_for_accounts)

        # Show the budget selection modal
        await self.push_screen(BudgetSelectModal(budgets), save_selected_budget)

    async def prompt_for_accounts(self):
        """Fetches accounts and displays the modal for selection."""

        if len(self.config.accounts) == 0:
            # We should have the accounts already, but lets try to get them
            if not self._initialize_ynab_handler():
                self.set_loading(False)
                return
            # Add assert to satisfy type checker
            assert self.ynab_handler is not None

            ynab_accounts = self.call_ynab(self.ynab_handler.get_accounts, self.config.selected_budget.id)

            if ynab_accounts is None:
                self.set_loading(False)
                return

            self.config.add_accounts_from_api(ynab_accounts)

        prev_selected_ids = [acc.id for acc in self.config.selected_accounts]

        async def save_selected_accounts(
            selected: list[Account] | None,
        ):
            if not selected:
                self.notify(
                    "Account selection cancelled or no accounts chosen.",
                    severity="warning",
                )
                if not self.config.selected_accounts:
                    self.exit()
            else:
                for account in selected:
                    account.selected = True

                self.notify(f"{len(selected)} accounts selected.", severity="information")
                self.config.refresh()

                self.set_loading(True)
                # Schedule loading on main thread (call_later is safe)
                self.call_later(self.load_budget_and_accounts)

        await self.push_screen(
            AccountSelectModal(self.config.accounts, prev_selected_ids),
            save_selected_accounts,
        )

    async def load_budget_and_accounts(self):
        """Loads the primary budget (if not already set) and account details."""
        if not self._initialize_ynab_handler():
            self.set_loading(False)
            return

        assert self.ynab_handler is not None

        self.set_loading(True)

        self.selected_budget_id = self.config.selected_budget.id

        self.log.info("Fetching details for selected accounts...")

        new_accounts_data: dict[str, YnabAccount] = {}
        for acc_config in self.config.selected_accounts:
            if account_detail := self.call_ynab(
                self.ynab_handler.get_account_by_id,
                self.selected_budget_id,
                acc_config.id,
            ):
                # Store the Account object
                new_accounts_data[acc_config.id] = account_detail
            else:
                self.log.warning(f"Could not fetch details for account: {acc_config.name} ({acc_config.id}).")

        self.accounts_data = new_accounts_data
        self.set_loading(False)
        # Update UI (safe as we are on main thread)
        await self.update_account_rows()

    async def update_account_rows(self) -> None:
        """Clears and repopulates the account list container with AccountRow widgets."""
        # This runs on main thread
        container = self.query_one("#accounts-list-container")
        # Clear existing rows before adding new/updated ones
        await container.remove_children()

        if not self.accounts_data:
            container.mount(Static("No account data loaded or available."))
            container.mount(Static(str(self.accounts_data)))
            return

        # Access name attribute of Account objects for sorting
        sorted_account_ids = sorted(
            self.accounts_data.keys(),
            key=lambda acc_id: self.accounts_data[acc_id].name,
        )

        for account_id in sorted_account_ids:
            if account := self.accounts_data[account_id]:
                row = AccountRow(
                    account_id=account_id,
                    account_name=account.name,
                    current_balance=account.balance,
                    id=f"account-row-{account_id}",
                    format=self.config.selected_budget.currency_format,
                )
                container.mount(row)

    # --- Action Handlers --- #

    def action_quit(self):
        """Action to quit the application."""
        self.exit()

    async def action_refresh_balances(self):
        """Action to reload account data from YNAB."""
        self.notify("Refreshing account balances...", timeout=2)
        await self.load_budget_and_accounts()

    async def action_reset_config_and_exit(self):
        """Action to reset configuration and exit the app after confirmation."""
        self.log.info("Action action_reset_config_and_exit triggered.")

        prompt = Text.assemble(
            ("Reset Configuration and Exit?\n\n", "bold red"),
            "This will delete your saved API key, budget selection, and account selections. ",
            "The application will close. Are you sure?",
        )
        # Use push_screen with a callback instead of push_screen_wait
        await self.push_screen(
            ConfirmModal("Confirm Reset", prompt, confirm_label="Reset & Exit"),
            self.handle_reset_confirmation,  # Pass the callback method
        )

    async def handle_reset_confirmation(self, confirmed: bool | None):
        """Callback to handle the result of the reset confirmation modal."""
        # Check for explicit True confirmation
        if confirmed is True:
            self.log.info("User confirmed configuration reset.")
            try:
                # Use pathlib to delete the config file
                if CONFIG_FILE.exists():
                    CONFIG_FILE.unlink()
                    self.notify("Configuration reset successfully.", severity="information")
                else:
                    self.notify("Configuration file not found (already reset?).", severity="warning")
            except OSError as e:
                self.log.error(f"Error deleting config file {CONFIG_FILE}: {e}")
                self.notify(f"Error resetting configuration: {e}", severity="error")
                return  # Don't exit if deletion failed

            # Exit the app
            self.exit(message="Configuration reset. Exiting.")
        else:
            self.log.info("User cancelled configuration reset.")
            self.notify("Configuration reset cancelled.", severity="warning")

    # --- Event Handlers --- #

    @on(Button.Pressed, "#config")
    def on_config_button_pressed(self):
        """Handle Config button press."""
        self.push_screen(ConfigScreen(self.config))

    @on(Button.Pressed, "#refresh-balances")
    async def on_refresh_button_pressed(self):
        """Handle Refresh Balances button press."""
        await self.action_refresh_balances()

    @on(AccountRow.BalanceUpdate)
    async def on_account_balance_update(self, message: AccountRow.BalanceUpdate):
        """Handle update request for a single account."""
        if (
            self.is_loading or not self.selected_budget_id or not self.ynab_handler  # Check if handler is initialized
        ):
            self.notify(
                "Cannot update balance now (loading, not configured, or YNAB client error).",
                severity="warning",
            )
            return

        assert self.ynab_handler is not None

        account_id = message.account_id
        new_balance_str = message.new_balance_str

        self.log.info(f"Received update request for account {account_id} with value '{new_balance_str}'")

        # --- 1. Get current account data --- #
        account_obj = self.accounts_data.get(account_id)

        if account_obj is None:
            self.log.error(f"Update failed: Account data not found for {account_id}")
            self.notify("Error: Account data missing.", severity="error")
            return

        # Use account object attributes
        account_name = account_obj.name
        current_balance_milliunits = account_obj.balance

        # --- 2. Parse new balance --- #
        new_balance_milliunits = parse_currency_to_milliunits(new_balance_str)
        if new_balance_milliunits is None:
            self.notify(f"Invalid balance format: '{new_balance_str}'", severity="error")
            return

        # --- 3. Calculate difference --- #
        adjustment_amount = new_balance_milliunits - current_balance_milliunits

        if adjustment_amount == 0:
            self.notify(
                "New balance is the same as the current balance. No adjustment needed.",
                severity="information",
            )
            # Optionally clear the input in the row? The row does this itself now.
            return

        # --- 4. Confirmation Modal --- #
        adjustment_str = format_currency(adjustment_amount, self.config.selected_budget.currency_format)
        new_balance_formatted = format_currency(new_balance_milliunits, self.config.selected_budget.currency_format)
        color = "green" if adjustment_amount >= 0 else "red"
        prompt = Text.assemble(
            "Create an adjustment of ",
            (f"{adjustment_str}", color),
            f" for account '{account_name}'?\n",
            f"(New balance will be {new_balance_formatted})",
        )

        # Define the callback as an inner function to capture local scope
        async def handle_confirmation(confirmed: bool | None) -> None:
            assert self.ynab_handler is not None

            # --- 5. Create Transaction if Confirmed --- #
            if confirmed is True:
                self.set_loading(True)
                try:
                    self.log.info(f"User confirmed adjustment for {account_name}.")
                    # Call method on handler instance
                    self.ynab_handler.create_transaction(
                        self.config.selected_budget.id,
                        account_id,
                        adjustment_amount,
                        self.config.adjustment_cleared_status,
                        self.config.adjustment_memo,
                    )

                    self.notify(f"Adjustment created for {account_name}.", severity="information")
                    # Update the row's displayed balance immediately
                    row = self.query_one(f"#account-row-{account_id}", AccountRow)
                    row.update_balance(new_balance_milliunits)
                    # Update the internal state as well (modify object attribute)
                    if account := self.accounts_data.get(account_id):
                        account.balance = new_balance_milliunits  # Update attribute
                    else:
                        self.log.error(f"Internal state error: Account {account_id} missing after update.")
                except (YNABClientError, AttributeError) as e:  # Catch AttributeError if handler is None
                    self.log.error(f"Failed to create adjustment for {account_name}: {e}")
                    self.notify(f"Error creating adjustment: {e}", severity="error", timeout=7)
                except Exception as e:
                    self.log.error(f"Unexpected error creating adjustment for {account_name}: {e}")
                    self.notify(f"Unexpected error: {e}", severity="error", timeout=7)
                finally:
                    self.set_loading(False)
            else:
                self.log.info(f"User cancelled adjustment for {account_name}.")
                self.notify("Adjustment cancelled.", severity="warning")

        # Use push_screen with the inner callback
        await self.push_screen(ConfirmModal("Confirm Balance Adjustment", prompt), callback=handle_confirmation)

    @on(Button.Pressed, "#update-all")
    async def on_update_all_pressed(self):
        """Handle the 'Update All' button press."""
        if (
            self.is_loading or not self.selected_budget_id or not self.ynab_handler  # Check if handler is initialized
        ):
            self.notify(
                "Cannot update balances now (loading, not configured, or YNAB client error).",
                severity="warning",
            )
            return

        self.log.info("'Update All' button pressed.")
        updates_to_make: list[tuple[str, str, int, int, int]] = []  # (id, name, current_bal, new_bal, adjustment)

        # --- 1. Collect updates from rows --- #
        account_rows = self.query(AccountRow)
        for row in account_rows:
            new_balance_str = row._balance_input.value.strip()
            account_id = row.account_id

            account_obj = self.accounts_data.get(account_id)

            if not new_balance_str or not account_obj:
                self.log.debug(f"Skipping account {account_id} in bulk update due to missing data or input.")
                continue

            account_name = account_obj.name
            current_balance = account_obj.balance
            new_balance = parse_currency_to_milliunits(new_balance_str)

            if new_balance is None:
                self.notify(
                    f"Invalid format '{new_balance_str}' for {account_name}. Skipping.",
                    severity="warning",
                )
                continue

            adjustment = new_balance - current_balance

            # Only add if adjustment is non-zero
            if adjustment != 0:
                updates_to_make.append((account_id, account_name, current_balance, new_balance, adjustment))
            # Removed the debug log for matching balances, can be added back if needed

        if not updates_to_make:
            self.notify("No accounts have new balances entered.", severity="information")
            return

        # --- 2. Confirmation Modal --- #
        # Prepare data for the bulk prompt helper
        prompt_data = [(id, name, cur_bal, adj) for id, name, cur_bal, new_bal, adj in updates_to_make]
        prompt_text = create_bulk_update_prompt(prompt_data, self.config.selected_budget.currency_format)

        # Define the callback as an inner function
        async def handle_bulk_confirmation(confirmed: bool | None) -> None:
            assert self.ynab_handler is not None
            # --- 3. Create Transactions if Confirmed --- #
            if confirmed is True:
                self.set_loading(True)
                transactions_payload = []
                transactions_payload.extend(
                    {
                        "account_id": acc_id,
                        "date": "today",  # Use today's date
                        "amount": adj_amount,
                        "payee_name": "Balance Adjustment",  # Consistent payee
                        "cleared": self.config.adjustment_cleared_status,
                        "memo": self.config.adjustment_memo,
                        "approved": True,
                    }
                    for acc_id, _, _, _, adj_amount in updates_to_make
                )
                try:
                    self.log.info(f"User confirmed bulk update for {len(transactions_payload)} accounts.")
                    # Call method on handler instance
                    self.ynab_handler.create_transactions(
                        self.config.selected_budget.id,
                        transactions_payload,
                    )
                    self.notify(
                        f"{len(transactions_payload)} balance adjustments created.",
                        severity="information",
                    )

                    # Update UI and internal state
                    for acc_id, _, _, new_bal, _ in updates_to_make:
                        try:
                            row = self.query_one(f"#account-row-{acc_id}", AccountRow)
                            row.update_balance(new_bal)
                            row._balance_input.value = ""  # Clear input
                            # Update attribute on the stored object
                            if account := self.accounts_data.get(acc_id):
                                account.balance = new_bal
                            else:
                                self.log.error(f"Internal state error: Account {acc_id} missing after bulk update.")
                        except (YNABClientError, AttributeError) as e:  # Catch AttributeError if handler is None
                            self.log.warning(f"Failed to update UI for account {acc_id} after bulk update: {e}")

                except (YNABClientError, AttributeError) as e:  # Catch AttributeError if handler is None
                    self.log.error(f"Failed to create bulk adjustments: {e}")
                    self.notify(f"Error creating bulk adjustments: {e}", severity="error", timeout=7)
                except Exception as e:
                    self.log.error(f"Unexpected error during bulk adjustment creation: {e}")
                    self.notify(f"Unexpected error: {e}", severity="error", timeout=7)
                finally:
                    self.set_loading(False)
            else:
                self.log.info("User cancelled bulk update.")
                self.notify("Bulk adjustment cancelled.", severity="warning")

        # Use push_screen with the inner callback
        await self.push_screen(
            ConfirmModal("Confirm Bulk Balance Adjustments", prompt_text), callback=handle_bulk_confirmation
        )

    @on(ConfigScreen.ConfigSaved)
    async def on_config_saved(self):
        """Handle the ConfigSaved message."""
        await self.load_budget_and_accounts()
