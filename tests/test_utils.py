import logging

import pytest
from src.ynab_updater.utils import (
    LEADING_PM_SIGNS_REGEXP,
    _cleanup_currency_value,
    _remove_plus_minus_signs_beginning,
    parse_currency_to_milliunits,
)


@pytest.mark.parametrize(
    "input_str, expected_remaining",
    [
        pytest.param("hello", "hello", id="no_leading_sign_or_space"),
        pytest.param("   world", "world", id="only_leading_space_no_signs_then_chars"),
        pytest.param("123.45", "123.45", id="starts_with_digit"),
        pytest.param("", "", id="empty_string"),
        pytest.param("+100", "100", id="single_plus_no_space"),
        pytest.param("  + 200", "200", id="single_plus_with_spaces"),
        pytest.param("+++300", "300", id="multiple_plus_no_space"),
        pytest.param("  ++  400", "400", id="multiple_plus_with_spaces"),
        pytest.param("-500", "-500", id="single_minus_no_space"),
        pytest.param(" - 600", "-600", id="single_minus_with_spaces"),
        pytest.param("---$700", "-$700", id="multiple_minus_no_space"),
        pytest.param(" --  800", "-800", id="multiple_minus_with_spaces"),
        pytest.param(" + abc", "abc", id="plus_space_chars"),
        pytest.param(" - def", "-def", id="minus_space_chars"),
        pytest.param(" ++ ", "", id="multiple_plus_spaces_only"),
        pytest.param(" -- ", "-", id="multiple_minus_spaces_only"),
        pytest.param("   +", "", id="spaces_then_single_plus"),
        pytest.param("   -", "-", id="spaces_then_single_minus"),
        pytest.param("+++", "", id="only_multiple_plus"),
        pytest.param("---", "-", id="only_multiple_minus"),
        pytest.param("   ", "", id="only_whitespace"),
        pytest.param("123", "123", id="only_numbers_no_signs"),
        pytest.param("  123", "123", id="only_numbers_leading_spaces"),
        pytest.param(" 123", "123", id="only_numbers_single_leading_space"),
    ],
)
def test_remove_plus_minus_signs_beginning_valid(input_str, expected_remaining):
    """Tests valid inputs for remove_plus_minus_signs_beginning."""
    remaining = _remove_plus_minus_signs_beginning(input_str)
    assert remaining == expected_remaining


@pytest.mark.parametrize(
    "invalid_input",
    [
        # Cases failing the initial Counter check (mixed signs anywhere)
        pytest.param("+-10", id="mixed_plus_minus_num"),
        pytest.param("-+20", id="mixed_minus_plus_num"),
        pytest.param(" ++-30", id="valid_prefix_then_mixed_minus"),
        pytest.param(" --+40", id="valid_prefix_then_mixed_plus"),
        pytest.param(" + - 50", id="plus_space_minus_num_mixed_anywhere"),
        pytest.param(" - + 60", id="minus_space_plus_num_mixed_anywhere"),
        pytest.param("abc+def-ghi", id="mixed_signs_within_text"),
        pytest.param("1+2-3", id="mixed_signs_between_digits"),
        pytest.param("  + val - val ", id="mixed_signs_spaced_out"),
    ],
)
def test_remove_plus_minus_signs_beginning_invalid_mixed_signs(invalid_input):
    """Tests invalid inputs (mixed + and - signs anywhere in the string)."""
    with pytest.raises(ValueError):
        _remove_plus_minus_signs_beginning(invalid_input)


@pytest.mark.parametrize(
    "input_str, expected_groups",
    [
        pytest.param("+1", ("+", "1"), id="match_plus_digit"),
        pytest.param("  -- abc", ("  -- ", "abc"), id="match_space_minus_space_chars"),
        pytest.param("   ", ("   ", ""), id="match_only_spaces"),
        pytest.param("-", ("-", ""), id="match_only_minus"),
        # Cases involving mixed signs (regex itself matches these)
        pytest.param("+-1", ("+-", "1"), id="match_mixed_plus_minus_digit"),
        pytest.param(" + - ", (" + - ", ""), id="match_space_plus_space_minus_space"),
    ],
)
def test_leading_pm_signs_regexp_matches(input_str, expected_groups):
    """Tests cases where LEADING_PM_SIGNS_REGEXP should match."""
    match = LEADING_PM_SIGNS_REGEXP.match(input_str)
    assert match is not None
    assert match.groups() == expected_groups


# --- Tests for cleanup_currency_value ---
@pytest.mark.parametrize(
    "input_str, expected_output",
    [
        # Basic cases with currency symbols
        pytest.param("$1,234.56", "1,234.56", id="dollar_sign"),
        pytest.param("€99,99", "99,99", id="euro_sign"),
        pytest.param("£50.00", "50.00", id="pound_sign"),
        pytest.param("¥1000", "1000", id="yen_sign"),
        # Cases with other invalid characters
        pytest.param("1#234", "1234", id="hash_symbol"),
        pytest.param("50%", "50", id="percent_symbol"),
        pytest.param("Amount: 1,000.00", "1,000.00", id="letters_and_colon"),
        pytest.param("Value = -12.34", "-12.34", id="letters_equals_space"),
        pytest.param(" 	 1,234.56 \n", "1,234.56", id="whitespace_chars"),  # Removes spaces, tabs, newlines
        # Cases with mixed valid and invalid chars
        pytest.param("-$1,000.00", "-1,000.00", id="minus_dollar"),
        pytest.param("+€50,00", "50,00", id="plus_euro"),
        pytest.param("USD 1,234.56", "1,234.56", id="currency_code_space"),
        # Cases already clean or edge cases
        pytest.param("1234.56", "1234.56", id="already_clean_decimal"),
        pytest.param("-1,000", "-1,000", id="already_clean_negative_comma"),
        pytest.param("+500", "500", id="already_clean_positive"),
        pytest.param(".50", "0.50", id="only_decimal_part"),
        pytest.param(",123", "123", id="starts_with_comma"),
        pytest.param("", "", id="empty_string"),
        pytest.param("abc$£", "", id="only_invalid_chars"),
    ],
)
def test_cleanup_currency_value(input_str, expected_output):
    """Tests the cleanup_currency_value function."""
    cleaned = _cleanup_currency_value(input_str)
    assert cleaned == expected_output


# Define test cases for successful parsing
# Format: (input_string, expected_milliunits, test_id)
success_test_cases = [
    ("100", 100000, "positive_integer"),
    ("123.45", 123450, "positive_float"),
    ("123.4", 123400, "positive_float_single_decimal"),
    ("12.3456", 12346, "positive_float_many_decimals"),
    ("-50", -50000, "negative_integer"),
    ("-123.45", -123450, "negative_float"),
    ("-123.4", -123400, "negative_float_single_decimal"),
    ("0", 0, "zero_integer"),
    ("0.00", 0, "zero_float"),
    ("$100.50", 100500, "currency_symbol"),
    ("1,234.56", 1234560, "commas"),
    ("$1,234.56", 1234560, "commas_and_symbol"),
    ("-$1,234.56", -1234560, "negative_commas_and_symbol"),
    (".50", 500, "leading_decimal"),
    (".5", 500, "leading_decimal_single_digit"),
    ("50.", 50000, "trailing_decimal"),
    ("  123.45  ", 123450, "whitespace"),
    ("  - $ 1,234.56 ", -1234560, "whitespace_and_symbols"),
]


@pytest.mark.parametrize(
    "input_str, expected_milliunits", [pytest.param(case[0], case[1], id=case[2]) for case in success_test_cases]
)
def test_parse_currency_to_milliunits_success(input_str, expected_milliunits):
    """Test successful parsing of various currency strings."""
    assert parse_currency_to_milliunits(input_str) == expected_milliunits


# Define test cases for invalid inputs
# Format: (input_string, expected_log_substring, test_id)
invalid_test_cases = [
    ("abc", "Could not parse currency value: abc", "invalid_alpha"),
    ("", "Could not parse currency value: ", "invalid_empty"),
    ("$", "Could not parse currency value: $", "invalid_just_symbol"),
    ("-", "Could not parse currency value: -", "invalid_just_minus"),
    ("1.2.3", "Could not parse currency value: 1.2.3", "invalid_multiple_decimals"),
]


@pytest.mark.parametrize(
    "input_str, expected_log", [pytest.param(case[0], case[1], id=case[2]) for case in invalid_test_cases]
)
def test_parse_currency_to_milliunits_invalid(caplog, input_str, expected_log):
    """Test invalid inputs that should return None and log a warning."""
    caplog.set_level(logging.WARNING)
    assert parse_currency_to_milliunits(input_str) is None
    # Check if the expected log message is present
    assert expected_log in caplog.text
