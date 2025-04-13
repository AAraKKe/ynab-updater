"""Client for interacting with the YNAB API using the official SDK."""

import logging
from datetime import date
from typing import Any

from pydantic import SecretStr
from ynab.api import accounts_api, budgets_api, transactions_api
from ynab.api_client import ApiClient
from ynab.configuration import Configuration
from ynab.exceptions import ApiException, NotFoundException
from ynab.models.account import Account
from ynab.models.budget_summary import BudgetSummary
from ynab.models.bulk_response import BulkResponse
from ynab.models.new_transaction import NewTransaction
from ynab.models.post_transactions_wrapper import PostTransactionsWrapper
from ynab.models.save_transactions_response import SaveTransactionsResponse
from ynab.models.transaction_cleared_status import TransactionClearedStatus
from ynab.models.transaction_detail import TransactionDetail

# Configure logging
logger = logging.getLogger(__name__)


# Define custom exception for easier handling upstream
class YNABClientError(Exception):
    """Custom exception for YNAB Client errors."""

    pass


class YnabHandler:
    """Handles interactions with the YNAB API using the official SDK."""

    def __init__(self, api_key: SecretStr):
        """Initializes the handler with the API key and creates an API client."""
        if not api_key:
            raise ValueError("API key cannot be empty for YnabHandler.")
        self._api_key_str = api_key.get_secret_value()
        self._client = self._create_api_client()

    def _create_api_client(self) -> ApiClient:
        """Configures and returns a YNAB API client instance."""
        configuration = Configuration(access_token=self._api_key_str)
        return ApiClient(configuration)

    # Map string representation to SDK Enum (kept private/static-like within class)
    @staticmethod
    def _get_cleared_enum(cleared_str: str) -> TransactionClearedStatus:
        cleared_str_lower = cleared_str.lower()
        if cleared_str_lower == "cleared":
            return TransactionClearedStatus.CLEARED
        elif cleared_str_lower == "uncleared":
            return TransactionClearedStatus.UNCLEARED
        elif cleared_str_lower == "reconciled":
            return TransactionClearedStatus.RECONCILED
        else:
            logger.warning(f"Invalid cleared status '{cleared_str}', defaulting to uncleared.")
            return TransactionClearedStatus.UNCLEARED

    # --- Methods corresponding to previous functions --- #

    def get_budgets(self, include_accounts=False) -> list[BudgetSummary]:
        """Fetches the list of budgets for the user using the YNAB SDK."""
        logger.info("Calling get_budgets")
        client_api = budgets_api.BudgetsApi(self._client)
        try:
            response = client_api.get_budgets(include_accounts=include_accounts)
            logger.info(response)
            return response.data.budgets
        except ApiException as e:
            logger.error(f"YNAB API error fetching budgets: {e}")
            raise YNABClientError(f"Failed to fetch budgets: {e}") from e
        except Exception as e:
            logger.error(f"Unexpected error fetching budgets: {e}")
            raise YNABClientError(f"An unexpected error occurred: {e}") from e

    def get_accounts(self, budget_id: str) -> list[Account]:
        """Fetches the list of accounts for a specific budget using the YNAB SDK."""
        client_api = accounts_api.AccountsApi(self._client)
        try:
            response = client_api.get_accounts(budget_id)
            return response.data.accounts
        except ApiException as e:
            logger.error(f"YNAB API error fetching accounts for budget {budget_id}: {e}")
            raise YNABClientError(f"Failed to fetch accounts: {e}") from e
        except Exception as e:
            logger.error(f"Unexpected error fetching accounts: {e}")
            raise YNABClientError(f"An unexpected error occurred: {e}") from e

    def get_account_by_id(self, budget_id: str, account_id: str) -> Account | None:
        """Fetches details for a specific account using the YNAB SDK."""
        client_api = accounts_api.AccountsApi(self._client)
        try:
            response = client_api.get_account_by_id(budget_id, account_id)
            return response.data.account
        except NotFoundException:
            logger.warning(f"Account {account_id} not found in budget {budget_id}.")
            return None
        except ApiException as e:
            logger.error(f"YNAB API error fetching account {account_id}: {e}")
            raise YNABClientError(f"Failed to fetch account {account_id}: {e}") from e
        except Exception as e:
            logger.error(f"Unexpected error fetching account {account_id}: {e}")
            raise YNABClientError(f"An unexpected error occurred: {e}") from e

    def create_transaction(
        self,
        budget_id: str,
        account_id: str,
        amount: int,
        cleared: str,
        memo: str | None = None,
        payee_name: str | None = "Balance Adjustment",
    ) -> TransactionDetail:
        """Creates a single transaction using the YNAB SDK."""
        client_api = transactions_api.TransactionsApi(self._client)

        new_transaction = NewTransaction(
            account_id=account_id,
            date=date.today(),
            amount=amount,
            payee_name=payee_name,
            cleared=self._get_cleared_enum(cleared),
            memo=memo,
            approved=True,
        )
        wrapper = PostTransactionsWrapper(transaction=new_transaction)

        try:
            logger.info(f"Creating adjustment for account {account_id}: amt={amount}, memo={memo}")
            response: SaveTransactionsResponse = client_api.create_transaction(budget_id, wrapper)

            if response.data and response.data.transaction:
                return response.data.transaction
            elif response.data and response.data.transactions and response.data.transactions[0]:
                return response.data.transactions[0]
            else:
                logger.warning("Create transaction response did not contain expected transaction data.")
                raise YNABClientError("Could not parse created transaction from YNAB response.")

        except ApiException as e:
            logger.error(f"YNAB API error creating transaction for account {account_id}: {e}")
            raise YNABClientError(f"Failed to create transaction: {e}") from e
        except Exception as e:
            logger.error(f"Unexpected error creating transaction: {e}")
            raise YNABClientError(f"An unexpected error occurred: {e}") from e

    def create_transactions(
        self,
        budget_id: str,
        transactions_data: list[dict[str, Any]],
    ) -> BulkResponse:
        """Creates multiple transactions in bulk using the YNAB SDK's create_transaction method."""
        client_api = transactions_api.TransactionsApi(self._client)

        new_transactions_list: list[NewTransaction] = []
        for tx_data in transactions_data:
            try:
                if any(k not in tx_data for k in ("account_id", "amount", "cleared")):
                    raise ValueError("Missing required keys in transaction data")

                new_tx = NewTransaction(
                    account_id=str(tx_data["account_id"]),
                    date=date.today(),
                    amount=int(tx_data["amount"]),
                    cleared=self._get_cleared_enum(str(tx_data["cleared"])),
                    payee_name=str(tx_data.get("payee_name", "Balance Adjustment")),
                    memo=str(tx_data.get("memo")) if tx_data.get("memo") else None,
                    approved=bool(tx_data.get("approved", True)),
                )
                new_transactions_list.append(new_tx)
            except (KeyError, ValueError, TypeError) as e:
                logger.error(f"Error processing transaction data for bulk import: {tx_data}. Error: {e}")
                raise YNABClientError(f"Invalid transaction data provided for bulk import: {e}") from e

        if not new_transactions_list:
            logger.warning("No valid transactions provided for bulk creation.")
            raise YNABClientError("No valid transactions to create.")

        bulk_payload = PostTransactionsWrapper(transactions=new_transactions_list)

        try:
            logger.info(f"Creating {len(new_transactions_list)} bulk adjustment transactions.")
            response: SaveTransactionsResponse = client_api.create_transaction(budget_id, bulk_payload)

            if response.data:
                # Return the SaveTransactionsResponseData, rely on structural compatibility
                # with BulkResponse type hint where this is used.
                # Caller might need to adapt if specific BulkResponse fields are needed.
                return response.data
            logger.warning("Bulk create response did not contain expected data.")
            raise YNABClientError("Could not parse bulk response from YNAB.")

        except ApiException as e:
            logger.error(f"YNAB API error creating bulk transactions: {e}")
            raise YNABClientError(f"Failed to create bulk transactions: {e}") from e
        except Exception as e:
            logger.error(f"Unexpected error creating bulk transactions: {e}")
            raise YNABClientError(f"An unexpected error occurred: {e}") from e
