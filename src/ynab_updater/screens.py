"""Main application screen and configuration screen."""

import contextlib
import logging
import re
from functools import partial

from pydantic import SecretStr
from rich.text import Text
from textual import on
from textual.app import App, ComposeResult
from textual.containers import Container, VerticalScroll
from textual.reactive import var
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, LoadingIndicator, Static

from .config import CONFIG_FILE, AccountConfig, AppConfig, load_config, save_config
from .modals import AccountSelectModal, APIKeyModal, BudgetSelectModal, ConfirmModal, create_bulk_update_prompt
from .widgets import AccountRow, format_currency
from .ynab_client import Account, BudgetSummary, YNABClientError, YnabHandler

# Remove the file-specific logger instance
# logger = logging.getLogger(__name__)

# --- Utility Function --- #


def parse_currency_to_milliunits(value_str: str) -> int | None:
    """Parses a currency string (e.g., '123.45', '-50', '$1,000.00') into milliunits."""
    # Remove common currency symbols and commas
    cleaned_value = re.sub(r"[$,]", "", value_str.strip())
    try:
        # Handle potential negative sign
        is_negative = cleaned_value.startswith("-")
        if is_negative:
            cleaned_value = cleaned_value[1:]

        # Split into dollars and cents if decimal exists
        if "." in cleaned_value:
            parts = cleaned_value.split(".")
            dollars = int(parts[0])
            # Pad cents if necessary (e.g., .5 -> 50)
            cents_str = parts[1].ljust(2, "0")[:2]  # Take only first two digits after decimal
            cents = int(cents_str)
        else:
            dollars = int(cleaned_value)
            cents = 0

        milliunits = (dollars * 1000) + (cents * 10)
        return -milliunits if is_negative else milliunits
    except (ValueError, IndexError):
        # Use self.log here if called from within the App context
        # However, this is a utility function, so standard logging might be okay
        # Or pass the app instance/log method if needed
        logging.warning(f"Could not parse currency value: {value_str}")  # Keep std log here
        return None


# --- Screens --- #


class ConfigScreen(Screen):
    """Configuration screen (currently placeholder)."""

    BINDINGS = [("escape", "app.pop_screen", "Back")]

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static("Configuration Options (Coming Soon!)", id="config-title")
        # Add config widgets here later
        yield Footer()


class UpdaterApp(App[None]):
    """The main YNAB Updater application."""

    TITLE = "YNAB Updater"
    SUB_TITLE = "Quickly update account balances"
    CSS_PATH = "app.css"  # We'll create this file next
    BINDINGS = [
        ("ctrl+q", "quit", "Quit"),
        ("ctrl+r", "refresh_balances", "Refresh Balances"),
        ("f10", "reset_config_and_exit", "Reset Config (F10)"),
        # Add more bindings as needed
    ]

    config: var[AppConfig] = var(load_config)
    accounts_data: var[dict[str, Account]] = var({})
    selected_budget_id: var[str | None] = var(None)
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
                yield Button("Refresh Balances", id="refresh-balances", variant="default")
                yield Button("Update All", id="update-all", variant="primary")
                yield Button("Config", id="config")
        yield Footer()

    def on_mount(self):
        """Called when the app is first mounted."""
        self.set_loading(True)
        # Run the async setup logic in a worker
        self.run_worker(self.check_initial_setup, thread=True)

    def set_loading(self, loading: bool):
        """Show/hide loading indicator and disable/enable buttons."""
        self.is_loading = loading
        indicator = self.query_one(LoadingIndicator)
        indicator.display = loading
        # Disable/enable action buttons while loading
        for button_id in ["refresh-balances", "update-all", "config"]:
            with contextlib.suppress(Exception):
                self.query_one(f"#{button_id}", Button).disabled = loading
        # Also disable individual account update buttons
        for row in self.query(AccountRow):
            with contextlib.suppress(Exception):
                row.query_one(Button).disabled = loading

    # This method runs in a worker thread
    async def check_initial_setup(self):
        """Check for API key and account selection on startup."""
        self.log.info("Checking initial setup...")
        action_to_take = None
        if not self.config.ynab_api_key:
            self.log.info("API key not found, prompting user.")
            action_to_take = self.prompt_for_api_key
        elif not self.config.selected_budget_id:
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
        if action_to_take:
            self.call_from_thread(action_to_take)
        else:  # Should ideally always have an action, but just in case
            # Schedule setting loading state off on the main thread
            self.call_from_thread(self.set_loading, False)

        # Note: We no longer call self.set_loading(False) directly here.
        # The scheduled action (e.g., load_budget_and_accounts) is responsible
        # for calling set_loading(False) when it completes *on the main thread*.

    def _initialize_ynab_handler(self) -> bool:
        """Initializes the YNAB handler if possible. Returns True on success."""
        if self.ynab_handler:
            return True  # Already initialized
        if self.config.ynab_api_key:
            try:
                self.ynab_handler = YnabHandler(self.config.ynab_api_key)
                self.log.info("YnabHandler initialized.")
                return True
            except ValueError as e:
                return self._handle_initialization_error(e)
        else:
            # This should ideally not be reached if setup flow is correct
            self.log.warning("Attempted to initialize YnabHandler without API key.")
            self.call_later(self.prompt_for_api_key)
            return False

    # TODO Rename this here and in `_initialize_ynab_handler`
    def _handle_initialization_error(self, e: ValueError):
        self.log.error(f"Failed to initialize YnabHandler: {e}")
        self.notify(f"API Key Error: {e}", severity="error")
        # Reset key if initialization fails
        self.config.ynab_api_key = None
        save_config(self.config)
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
            save_config(self.config)
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
        try:
            self.log.info("Fetching budgets...")
            budgets = self.ynab_handler.get_budgets()

            if not budgets:
                self.notify("No budgets found. Check API key or YNAB status.", severity="error")
                self.set_loading(False)
                # TODO: Consider re-prompting for API key?
                return

            # Define the callback for when a budget is selected
            async def save_selected_budget(selected_budget: BudgetSummary | None):
                if selected_budget:
                    self.config.selected_budget_id = selected_budget.id
                    self.config.selected_budget_name = selected_budget.name
                    # Extract and save currency format
                    if cf := selected_budget.currency_format:
                        self.config.currency_symbol = cf.currency_symbol
                        self.config.currency_decimal_digits = cf.decimal_digits
                        self.config.currency_symbol_first = cf.symbol_first
                        self.log.info(f"Set currency format: {cf.iso_code}, Symbol: {cf.currency_symbol}")
                    else:
                        # Use defaults if format is missing (shouldn't happen)
                        self.log.warning(f"Currency format missing for budget {selected_budget.name}. Using defaults.")
                        self.config.currency_symbol = "$"
                        self.config.currency_decimal_digits = 2
                        self.config.currency_symbol_first = True

                    save_config(self.config)
                    self.notify(f"Budget '{self.config.selected_budget_name}' selected.", severity="information")
                    # Now prompt for accounts
                    self.set_loading(True)
                    self.call_later(self.prompt_for_accounts)
                else:
                    self.notify("Budget selection cancelled.", severity="warning")
                    # If no budget previously selected, maybe exit or re-prompt?
                    if not self.config.selected_budget_id:
                        self.exit()
                    else:  # Keep existing selection if user cancels
                        self.set_loading(False)  # Ensure loading is off

            # Show the budget selection modal
            await self.push_screen(BudgetSelectModal(budgets), save_selected_budget)

        except (YNABClientError, AttributeError) as e:
            self.notify(f"YNAB API Error fetching budgets: {e}", severity="error", timeout=7)
            self.set_loading(False)
            # Handle potential invalid key
            if "Unauthorized" in str(e):
                self.config.ynab_api_key = None
                self.config.selected_budget_id = None  # Also clear budget selection
                self.config.selected_budget_name = None
                # Also reset currency settings
                self.config.currency_symbol = "$"
                self.config.currency_decimal_digits = 2
                self.config.currency_symbol_first = True
                save_config(self.config)
                await self.prompt_for_api_key()
        except Exception as e:
            self.log.error(f"Error during budget selection: {e}")
            self.notify(f"Error fetching budgets: {e}", severity="error", timeout=7)
            self.set_loading(False)

    async def prompt_for_accounts(self):
        """Fetches accounts and displays the modal for selection."""
        # Ensure handler is initialized first
        if not self._initialize_ynab_handler():
            self.set_loading(False)  # Ensure loading is off if handler init fails
            return
        # Add assert to satisfy type checker
        assert self.ynab_handler is not None

        try:
            if not self.config.selected_budget_id:
                self.log.error("Cannot select accounts: No budget selected.")
                self.notify("No budget selected. Please configure first.", severity="error")
                # Maybe prompt for budget again?
                self.call_later(self.prompt_for_budget)
                return

            self.selected_budget_id = self.config.selected_budget_id  # Use stored ID
            self.log.info(
                f"Fetching accounts for selected budget: {self.config.selected_budget_name} ({self.selected_budget_id})"
            )

            # --- Fetch Accounts --- #
            self.log.info(f"Fetching accounts for budget {self.selected_budget_id}...")
            # Call method on handler instance
            all_accounts = self.run_worker(
                partial(self.ynab_handler.get_accounts, self.selected_budget_id),
                thread=True,
            )

            prev_selected_ids = [acc.id for acc in self.config.selected_accounts]

            # --- Define callback for AccountSelectModal --- #
            async def save_selected_accounts(
                selected: list[AccountConfig],
            ):
                # This callback runs on the main thread after modal dismiss
                if not selected:
                    self.notify(
                        "Account selection cancelled or no accounts chosen.",
                        severity="warning",
                    )
                    if not self.config.selected_accounts:
                        self.exit()
                else:
                    self.config.selected_accounts = selected
                    save_config(self.config)
                    self.notify(f"{len(selected)} accounts selected.", severity="information")
                    self.set_loading(True)
                    # Schedule loading on main thread (call_later is safe)
                    self.call_later(self.load_budget_and_accounts)

            all_accounts = await all_accounts.wait()

            await self.push_screen(
                AccountSelectModal(all_accounts, prev_selected_ids),
                save_selected_accounts,
            )

        except (YNABClientError, AttributeError) as e:  # Catch AttributeError if handler is None
            self.notify(f"YNAB API Error: {e}", severity="error", timeout=7)
            if "Unauthorized" in str(e):
                self.config.ynab_api_key = None
                self.config.selected_budget_id = None
                self.config.selected_budget_name = None
                # Also reset currency settings
                self.config.currency_symbol = "$"
                self.config.currency_decimal_digits = 2
                self.config.currency_symbol_first = True
                save_config(self.config)
                await self.prompt_for_api_key()
        except Exception as e:
            self.log.error(f"An unexpected error occurred during account selection setup: {e}")
            self.notify(f"Error selecting accounts: {e}", severity="error", timeout=7)
        # No finally block needed here as set_loading(False) is handled by callbacks/next steps

    async def load_budget_and_accounts(self):
        """Loads the primary budget (if not already set) and account details."""
        # This now runs on the main thread via call_from_thread or call_later
        # Ensure handler is initialized
        if not self._initialize_ynab_handler():
            self.set_loading(False)
            return
        # Add assert to satisfy type checker
        assert self.ynab_handler is not None

        self.set_loading(True)
        try:
            if not self.config.ynab_api_key:
                await self.prompt_for_api_key()
                return
            if not self.config.selected_accounts:
                await self.prompt_for_accounts()
                return

            # Ensure budget ID is set
            if not self.config.selected_budget_id:
                self.log.warning("load_budget_and_accounts called without selected budget.")
                await self.prompt_for_budget()
                return

            self.selected_budget_id = self.config.selected_budget_id  # Ensure reactive var matches config

            self.log.info("Fetching details for selected accounts...")
            # Store Account objects directly
            new_accounts_data: dict[str, Account] = {}
            for acc_config in self.config.selected_accounts:
                if account_detail := self.ynab_handler.get_account_by_id(
                    self.selected_budget_id,
                    acc_config.id,
                ):
                    # Store the Account object
                    new_accounts_data[acc_config.id] = account_detail
                else:
                    self.log.warning(f"Could not fetch details for account: {acc_config.name} ({acc_config.id}).")

            self.accounts_data = new_accounts_data
            # Update UI (safe as we are on main thread)
            await self.update_account_rows()

        except (YNABClientError, AttributeError) as e:  # Catch AttributeError if handler is None
            self.notify(f"YNAB API Error loading accounts: {e}", severity="error", timeout=7)
            if "Unauthorized" in str(e):
                self.config.ynab_api_key = None
                self.config.selected_budget_id = None  # Also clear budget selection
                self.config.selected_budget_name = None
                # Also reset currency settings
                self.config.currency_symbol = "$"
                self.config.currency_decimal_digits = 2
                self.config.currency_symbol_first = True
                save_config(self.config)
                await self.prompt_for_api_key()
            self.log.error(e)
        except Exception as e:
            self.log.error(f"Error loading account data: {e}")
            self.notify(f"Error loading accounts: {e}", severity="error", timeout=7)
        finally:
            # Ensure loading is off now that we're done on the main thread
            self.set_loading(False)

    async def update_account_rows(self) -> None:
        """Clears and repopulates the account list container with AccountRow widgets."""
        # This runs on main thread
        container = self.query_one("#accounts-list-container")
        # Clear existing rows before adding new/updated ones
        await container.remove_children()

        if not self.accounts_data:
            container.mount(Static("No account data loaded or available."))
            return

        # Access name attribute of Account objects for sorting
        sorted_account_ids = sorted(
            self.accounts_data.keys(),
            key=lambda acc_id: self.accounts_data[acc_id].name,
        )

        for account_id in sorted_account_ids:
            account: Account = self.accounts_data[account_id]
            # Account object guarantees name and balance attributes exist
            if account:
                row = AccountRow(
                    account_id=account_id,
                    account_name=account.name,
                    current_balance=account.balance,
                    id=f"account-row-{account_id}",
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
        self.push_screen(ConfigScreen())

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
        # Use stored currency settings
        # Assign to vars to help type checker
        symbol = self.config.currency_symbol or "$"
        symbol_first = self.config.currency_symbol_first

        adjustment_str = format_currency(
            adjustment_amount,
            symbol,
            symbol_first,
        )
        new_balance_formatted = format_currency(
            new_balance_milliunits,
            symbol,
            symbol_first,
        )
        color = "green" if adjustment_amount >= 0 else "red"
        prompt = Text.assemble(
            "Create an adjustment of ",
            (f"{adjustment_str}", color),
            f" for account '{account_name}'?\n",
            f"(New balance will be {new_balance_formatted})",
        )

        # Define the callback as an inner function to capture local scope
        async def handle_confirmation(confirmed: bool | None) -> None:
            # --- 5. Create Transaction if Confirmed --- #
            if confirmed is True:
                self.set_loading(True)
                try:
                    self.log.info(f"User confirmed adjustment for {account_name}.")
                    # Call method on handler instance
                    self.ynab_handler.create_transaction(
                        self.selected_budget_id,
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
                self.log.warning(f"Skipping account {account_id} in bulk update due to missing data or input.")
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
        prompt_text = create_bulk_update_prompt(prompt_data)

        # Define the callback as an inner function
        async def handle_bulk_confirmation(confirmed: bool | None) -> None:
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
                        self.selected_budget_id,
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
