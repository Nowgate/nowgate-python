"""Amounts are decimal strings in the asset's units, as the API sends and takes them. These
helpers convert and compare them without floating point, and the client uses check_amount
to turn what an amount field takes into what the API reads."""

from __future__ import annotations

import re
from decimal import Decimal
from typing import Literal, Tuple, Union

_DECIMAL = re.compile(r"(0|[1-9][0-9]*)(?:\.([0-9]+))?")


def _parts(amount: str, name: str) -> Tuple[str, str]:
    match = _DECIMAL.fullmatch(amount) if isinstance(amount, str) else None
    if match is None:
        raise TypeError(f'{name} must be a decimal string, such as "12.5"')
    return match.group(1), match.group(2) or ""


def _check_decimals(decimals: int) -> None:
    if isinstance(decimals, bool) or not isinstance(decimals, int) or not 0 <= decimals <= 255:
        raise TypeError("decimals must be the asset's decimals, a whole number from 0 to 255")


class Amounts:
    """Amount helpers, exact for any amount: no floating point."""

    @staticmethod
    def to_units(amount: str, decimals: int) -> int:
        """An amount in the asset's smallest units: to_units("1.5", 6) is 1500000. An
        asset's decimals come from assets.list(). An amount more precise than that is
        refused with a ValueError."""
        _check_decimals(decimals)
        whole, fraction = _parts(amount, "amount")
        if re.search(r"[1-9]", fraction[decimals:]):
            raise ValueError(f"{amount} has more decimals than the asset's {decimals}")
        return int(whole + fraction[:decimals].ljust(decimals, "0"))

    @staticmethod
    def from_units(units: Union[int, str], decimals: int) -> str:
        """An amount of smallest units, in the API's canonical form: from_units(1500000, 6)
        is "1.5"."""
        _check_decimals(decimals)
        if isinstance(units, int) and not isinstance(units, bool):
            n = units
        elif isinstance(units, str) and re.fullmatch(r"[0-9]+", units):
            n = int(units)
        else:
            raise TypeError("units must be a whole number: an int or digits")
        if n < 0:
            raise ValueError("units can't be negative")
        digits = str(n).rjust(decimals + 1, "0")
        whole = digits[: len(digits) - decimals]
        fraction = digits[len(digits) - decimals :].rstrip("0")
        return f"{whole}.{fraction}" if fraction else whole

    @staticmethod
    def compare(a: str, b: str) -> Literal[-1, 0, 1]:
        """Compares two amounts: -1 when a is less than b, 0 when they're equal, 1 when
        it's more."""
        a_whole, a_fraction = _parts(a, "a")
        b_whole, b_fraction = _parts(b, "b")
        if len(a_whole) != len(b_whole):
            return -1 if len(a_whole) < len(b_whole) else 1
        if a_whole != b_whole:
            return -1 if a_whole < b_whole else 1
        length = max(len(a_fraction), len(b_fraction))
        x = a_fraction.ljust(length, "0")
        y = b_fraction.ljust(length, "0")
        if x == y:
            return 0
        return -1 if x < y else 1


def amount_text(value: object, at: str) -> object:
    """What the API reads for an amount field's value: an int or a finite Decimal as its
    decimal string, and anything else as it is (the API checks the format). A float or a
    bool is refused before sending, naming the field."""
    if isinstance(value, bool) or isinstance(value, float):
        kind = type(value).__name__
        raise TypeError(f'{at} is a {kind}: amounts are decimal strings, such as "12.5"')
    if isinstance(value, int):
        return str(value)
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError(f"{at} is {value}: amounts are finite")
        return format(value, "f")
    return value
