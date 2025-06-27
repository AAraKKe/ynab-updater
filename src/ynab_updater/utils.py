from __future__ import annotations

import logging
import re
from collections import Counter
from typing import TYPE_CHECKING

from rich.text import Text
from textual.widget import Widget

from ynab_updater.config import CurrencyFormat

LEADING_PM_SIGNS_REGEXP = re.compile(r"([+\-\s]*)(.*)")
INVALID_CURRENCY_REGEXP = re.compile(r"[^\d\.,+\-]")
VALID_CURRENCY_REGEXP = re.compile(r"[\d\.,+\-]")


if TYPE_CHECKING:
    from ynab_updater.widgets import AccountUpdate


def parse_currency_to_milliunits(value_str: str) -> int | None:
    """Parses a currency string (e.g., '123.45', '-50', '$1,000.00') into milliunits."""
    cleaned_value = _cleanup_currency_value(value_str)

    # Basic check for empty string after cleaning
    if not cleaned_value:
        logging.warning(f"Could not parse currency value: {value_str}")
        return None

    try:
        value_without_signs = _remove_plus_minus_signs_beginning(cleaned_value)
        number_value = _string_value_to_float(value_without_signs)
        prepared_for_milis = f"{number_value:.3f}"
        return int(prepared_for_milis.replace(".", ""))
    except (ValueError, IndexError) as e:
        logging.warning(f"Could not parse currency value: {value_str} (Reason: {e})")
        return None


def format_balance(value: int, format: CurrencyFormat) -> str:
    dec_value = value / 1000

    str_value = f"{dec_value:,.{format.decimal_digits}f}"

    # We can end up with something like -0
    if str_value == "-0":
        str_value = "0"

    gruop_placeholder = "@@grup_placeholder@@"
    str_value = (
        str_value.replace(",", gruop_placeholder)
        .replace(".", format.decimal_separator)
        .replace(gruop_placeholder, format.group_separator)
    )

    if format.symbol_first:
        if str_value.startswith("-"):
            return f"-{format.currency_symbol}{str_value[1:]}"
        return f"{format.currency_symbol}{str_value}"
    return f"{str_value}{format.currency_symbol}"


def _string_value_to_float(value: str) -> float | None:
    try:
        return float(value.replace(",", "_"))
    except ValueError:
        raise ValueError(f"Cannot convert the value {value} info a number") from None


def _remove_plus_minus_signs_beginning(value: str) -> str:
    """
    Remove any leading plus and minus signs only keeping 1 minus sign in the string to
    keep the information about the string representing a negative number.
    """
    # Ensure signs are not broken
    counter = Counter(value)
    if counter.get("+", 0) > 0 and counter.get("-", 0) > 0:
        raise ValueError(f"The value {value} contains an unsupported set of +/- signs")

    stripped_value = value.lstrip()
    match = LEADING_PM_SIGNS_REGEXP.match(stripped_value)

    if not match:
        return stripped_value
    # If we have a match, extract the sign groups
    leading_signs = match[1]
    remaining_string = match[2]
    leading_sign = "-" if leading_signs and leading_signs[0] == "-" else ""

    return f"{leading_sign}{remaining_string}"


def _cleanup_currency_value(value: str) -> str:
    cleaned = INVALID_CURRENCY_REGEXP.sub("", value)
    if cleaned.startswith("."):
        cleaned = cleaned.lstrip(".").lstrip(",")
        cleaned = f"0.{cleaned}"

    # Handle invalid beginnings and ends
    return cleaned.strip(".,+")


def css_id(element: Widget | str, prefix="") -> str:
    main_id = element.id if isinstance(element, Widget) else element
    return f"#{prefix}{main_id}"


def update_balance_text(account_name: str, old_balance: int, new_balance: int, format: CurrencyFormat) -> Text:
    adjustment_amount = new_balance - old_balance

    adjustment_str = format_balance(adjustment_amount, format)
    new_balance_formatted = format_balance(new_balance, format)
    color = "green" if adjustment_amount >= 0 else "red"
    return Text.assemble(
        "Create an adjustment of ",
        (f"{adjustment_str}", color),
        f" for account {account_name!r}?\n",
        f"(New balance will be {new_balance_formatted})",
    )


def bulk_update_balance_text(updates: list[AccountUpdate], format: CurrencyFormat) -> Text:
    """
    Generates a Rich Text prompt for the bulk update confirmation modal.

    Args:
        updates: A list of tuples, where each tuple contains:
                 (account_id, account_name, old_balance_milliunits, adjustment_milliunits)

    Returns:
        A Rich Text object summarizing the changes.
    """
    prompt_text = Text("The following balance adjustments will be made:\n\n")
    for update in updates:
        adjustment = update.new_balance - update.old_balance
        new_balance = update.old_balance + adjustment
        adjustment_str = format_balance(adjustment, format)
        new_balance_str = format_balance(new_balance, format)
        # Add color to adjustment amount
        color = "green" if adjustment >= 0 else "red"
        prompt_text.append(f" • {update.account_name}: ")
        prompt_text.append(f"{adjustment_str} ", style=color)
        prompt_text.append(f"(New balance: {new_balance_str})\n")

    prompt_text.append("\nDo you want to proceed?")
    return prompt_text
