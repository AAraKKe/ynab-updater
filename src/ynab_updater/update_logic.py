"""Logic for handling single and bulk balance updates."""

import logging
from typing import TYPE_CHECKING

from rich.text import Text

from .modals import ConfirmModal, create_bulk_update_prompt
from .widgets import AccountRow, format_currency
from .ynab_client import YNABClientError

if TYPE_CHECKING:
    from .screens import YnabUpdater

logger = logging.getLogger(__name__)


async def process_single_update_request(app: "YnabUpdater", account_id: str, new_balance_str: str):
    """Handles parsing, validation, and confirmation for a single account update."""
    logger.info(f"Processing update request for account {account_id} with value '{new_balance_str}'")

    # Import parse function locally to avoid circular imports at module level
    from .screens import parse_currency_to_milliunits

    # --- 1. Get current account data --- #
    account_obj = app.accounts_data.get(account_id)
    if account_obj is None:
        logger.error(f"Update failed: Account data not found for {account_id}")
        app.notify("Error: Account data missing.", severity="error")
        return

    account_name = account_obj.name
    current_balance_milliunits = account_obj.balance

    # --- Find the specific AccountRow --- #
    try:
        row = app.query_one(f"#account-row-{account_id}", AccountRow)
    except Exception:
        logger.error(f"Could not find AccountRow widget for {account_id}. Aborting update.")
        app.notify(f"UI Error: Could not find row for {account_name}.", severity="error")
        return

    # --- 2. Parse new balance --- #
    new_balance_milliunits = parse_currency_to_milliunits(new_balance_str)
    if new_balance_milliunits is None:
        app.notify(f"Invalid balance format: '{new_balance_str}' for {account_name}", severity="error")
        row.clear_input()  # Use the new clear_input method
        row._balance_input.focus()  # Focus the input on error
        return

    # --- 3. Calculate difference --- #
    adjustment_amount = new_balance_milliunits - current_balance_milliunits

    if adjustment_amount == 0:
        app.notify(
            f"New balance for {account_name} is the same. No adjustment needed.",
            severity="information",
        )
        row.clear_input()  # Clear input if balance is the same
        return

    # --- 4. Confirmation Modal --- #
    symbol = app.config.currency_symbol or "$"
    symbol_first = app.config.currency_symbol_first

    adjustment_str = format_currency(adjustment_amount, symbol, symbol_first)
    new_balance_formatted = format_currency(new_balance_milliunits, symbol, symbol_first)
    color = "green" if adjustment_amount >= 0 else "red"
    prompt = Text.assemble(
        "Create an adjustment of ",
        (f"{adjustment_str}", color),
        f" for account '{account_name}'?\n",
        f"(New balance will be {new_balance_formatted})",
    )

    # --- Callback for confirmation --- #
    async def handle_confirmation(confirmed: bool | None):
        if confirmed is True:
            await execute_single_update(
                app,
                account_id,
                account_name,
                adjustment_amount,
                new_balance_milliunits,
                row,  # Pass the row object
            )
        else:
            logger.info(f"User cancelled adjustment for {account_name}.")
            app.notify(f"Adjustment for {account_name} cancelled.", severity="warning")
            # Don't clear input on cancel, user might want to correct it
            # row.clear_input()

    await app.push_screen(ConfirmModal("Confirm Balance Adjustment", prompt), callback=handle_confirmation)


async def execute_single_update(
    app: "YnabUpdater",
    account_id: str,
    account_name: str,
    adjustment_amount: int,
    new_balance_milliunits: int,
    row: AccountRow,  # Receive the row object
):
    """Performs the YNAB API call and updates state for a confirmed single update."""
    if not app.ynab_handler or not app.selected_budget_id:
        logger.error("execute_single_update called without YNAB handler or budget ID.")
        app.notify("Cannot create transaction: YNAB connection lost.", severity="error")
        return

    app.set_loading(True)
    try:
        logger.info(f"Executing confirmed adjustment for {account_name}.")
        app.ynab_handler.create_transaction(
            app.selected_budget_id,
            account_id,
            adjustment_amount,
            app.config.adjustment_cleared_status,
            app.config.adjustment_memo,
        )

        app.notify(f"Adjustment created for {account_name}.", severity="information")
        # Update the row's displayed balance immediately
        row.update_balance(new_balance_milliunits)
        row.clear_input()  # Clear input on success
        # Update the internal state as well
        if account := app.accounts_data.get(account_id):
            account.balance = new_balance_milliunits
        else:
            # This case should be unlikely if we found the account object earlier
            logger.error(f"Internal state error: Account {account_id} missing after update.")
    except YNABClientError as e:
        logger.error(f"Failed to create adjustment for {account_name}: {e}")
        app.notify(f"Error creating adjustment: {e}", severity="error", timeout=7)
        # Don't clear input on API error, user might want to retry
    except Exception as e:
        logger.exception(f"Unexpected error creating adjustment for {account_name}: {e}")
        app.notify(f"Unexpected error: {e}", severity="error", timeout=7)
        # Don't clear input on unexpected error
    finally:
        app.set_loading(False)


async def process_bulk_update_request(app: "YnabUpdater"):
    """Handles collection, parsing, validation, and confirmation for bulk updates."""
    logger.info("Processing 'Update All' request.")
    # Store tuples of (row, current_bal_milliunits, new_bal_milliunits, adjustment)
    updates_to_process: list[tuple[AccountRow, int, int, int]] = []
    rows_with_invalid_input: list[AccountRow] = []
    rows_with_no_change: list[AccountRow] = []

    # Import parse function locally
    from .screens import parse_currency_to_milliunits

    # --- 1. Collect and parse updates from rows --- #
    account_rows = app.query(AccountRow)

    for row in account_rows:
        new_balance_str = row._balance_input.value.strip()
        account_id = row.account_id
        account_obj = app.accounts_data.get(account_id)

        if not account_obj:
            logger.warning(f"Skipping row {account_id} in bulk update: Account data missing.")
            continue

        if not new_balance_str:
            # Skip rows with no input
            continue

        account_name = account_obj.name
        current_balance = account_obj.balance
        new_balance = parse_currency_to_milliunits(new_balance_str)

        if new_balance is None:
            app.notify(
                f"Invalid format '{new_balance_str}' for {account_name}. Skipping in bulk update.",
                severity="warning",
                timeout=5,
            )
            row.clear_input()
            row._balance_input.focus()  # Focus the invalid input
            rows_with_invalid_input.append(row)
            continue

        adjustment = new_balance - current_balance

        if adjustment != 0:
            updates_to_process.append((row, current_balance, new_balance, adjustment))
        else:
            # Input was valid but matched current balance
            row.clear_input()
            rows_with_no_change.append(row)

    if not updates_to_process:
        if not rows_with_invalid_input:
            app.notify("No accounts have new balances entered requiring adjustment.", severity="information")
        # If there were invalid inputs, notifications were already shown
        return

    # --- 2. Confirmation Modal --- #
    # Prepare data for the bulk prompt helper: (id, name, current_bal, adjustment)
    prompt_data = [
        (r.account_id, app.accounts_data[r.account_id].name, cur_b, adj) for r, cur_b, new_b, adj in updates_to_process
    ]
    prompt_text = create_bulk_update_prompt(prompt_data)

    # --- Callback for confirmation --- #
    async def handle_bulk_confirmation(confirmed: bool | None):
        if confirmed is True:
            await execute_bulk_update(app, updates_to_process)
        else:
            logger.info("User cancelled bulk update.")
            app.notify("Bulk adjustment cancelled.", severity="warning")
            # Don't clear inputs on cancel, user might want to correct entries
            # Focus the first input that was going to be processed?
            if updates_to_process:
                updates_to_process[0][0]._balance_input.focus()

    await app.push_screen(
        ConfirmModal("Confirm Bulk Balance Adjustments", prompt_text), callback=handle_bulk_confirmation
    )


async def execute_bulk_update(
    app: "YnabUpdater",
    updates: list[tuple[AccountRow, int, int, int]],  # (row, current_bal, new_bal, adjustment)
):
    """Performs the YNAB API call and updates state for confirmed bulk updates."""
    if not app.ynab_handler or not app.selected_budget_id:
        logger.error("execute_bulk_update called without YNAB handler or budget ID.")
        app.notify("Cannot create transactions: YNAB connection lost.", severity="error")
        return

    app.set_loading(True)
    transactions_payload = [
        {
            "account_id": row.account_id,
            "date": "today",
            "amount": adj_amount,
            "payee_name": "Balance Adjustment",
            "cleared": app.config.adjustment_cleared_status,
            "memo": app.config.adjustment_memo,
            "approved": True,
        }
        for row, _, _, adj_amount in updates
    ]

    successful_updates: list[AccountRow] = []
    failed_updates: list[str] = []  # Store names of failed accounts

    try:
        logger.info(f"Executing confirmed bulk update for {len(transactions_payload)} accounts.")
        # Note: The bulk endpoint might partially succeed. The response indicates
        # which transactions were created, but we assume success here unless an exception occurs.
        # A more robust implementation would check the response.
        response = app.ynab_handler.create_transactions(
            app.selected_budget_id,
            transactions_payload,
        )
        # Simple check: if response isn't None or empty (adjust based on actual response structure)
        if response and response.get("transaction_ids"):  # Example check
            num_created = len(response["transaction_ids"])
            logger.info(f"YNAB API reported {num_created} transactions created.")
            app.notify(f"{num_created} balance adjustments created.", severity="information")
            # Assume all passed if API call succeeded without error for now
            successful_updates = [row for row, _, _, _ in updates]
        else:
            # Handle case where API call succeeded but created 0 transactions (unexpected)
            logger.warning("YNAB API call succeeded but no transactions were reported as created.")
            app.notify("Bulk update call succeeded, but YNAB reported no changes.", severity="warning")
            # Consider all as failed in this ambiguous case
            failed_updates = [app.accounts_data.get(row.account_id, "Unknown").name for row, _, _, _ in updates]

    except YNABClientError as e:
        logger.error(f"Failed to create bulk adjustments: {e}")
        app.notify(f"Error creating bulk adjustments: {e}", severity="error", timeout=7)
        # Assume all failed on API error
        failed_updates = [app.accounts_data.get(row.account_id, "Unknown").name for row, _, _, _ in updates]
    except Exception as e:
        logger.exception(f"Unexpected error during bulk adjustment creation: {e}")
        app.notify(f"Unexpected error: {e}", severity="error", timeout=7)
        # Assume all failed on unexpected error
        failed_updates = [app.accounts_data.get(row.account_id, "Unknown").name for row, _, _, _ in updates]

    # --- Update UI and internal state for successful updates --- #
    for row, _, new_bal, _ in updates:
        if row in successful_updates:
            try:
                account_id = row.account_id
                row.update_balance(new_bal)
                row.clear_input()
                if account := app.accounts_data.get(account_id):
                    account.balance = new_bal
                else:
                    # This is unlikely if row exists, but log defensively
                    logger.error(f"Internal state error: Account {account_id} missing after bulk update success.")
            except Exception as ui_err:
                account_name = app.accounts_data.get(row.account_id, "Unknown").name
                logger.exception(
                    f"Failed to update UI for account {account_name} after successful bulk update: {ui_err}"
                )
                app.notify(f"Failed to update UI for {account_name}. Check logs.", severity="warning")
        else:
            # Don't clear input for failed updates
            pass

    if failed_updates:
        app.notify(f"Failed to update: {', '.join(failed_updates)}", severity="error", timeout=10)

    # --- Final loading state --- #
    app.set_loading(False)
