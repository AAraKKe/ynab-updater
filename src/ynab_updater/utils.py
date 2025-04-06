import logging
import re
from collections import Counter

LEADING_PM_SIGNS_REGEXP = re.compile(r"([+\-\s]*)(.*)")
INVALID_CURRENCY_REGEXP = re.compile(r"[^\d\.,+\-]")
VALID_CURRENCY_REGEXP = re.compile(r"[\d\.,+\-]")


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
