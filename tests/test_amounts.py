"""Amounts are decimal strings: floats are refused before sending, ints and Decimals are sent
as decimal strings, and the helpers convert and compare without floating point
(api-docs-and-sdks.md section 1.6)."""

from __future__ import annotations

import unittest
from decimal import Decimal
from typing import Any, Callable, List, Tuple

from nowgate import Amounts, Nowgate

from .fake import PAYMENT, Fake, answer


class AmountFields(unittest.TestCase):
    def test_a_float_or_bool_amount_is_refused_before_sending_naming_the_field(self) -> None:
        fake = Fake([])
        c: Any = fake.client
        cases: List[Tuple[Callable[[Nowgate], object], str]] = [
            (lambda n: c.payments.create(network="tron", asset="USDT", amount=25.0), "/amount is a float"),
            (lambda n: c.payments.create(network="tron", asset="USDT", price_amount=True), "/price_amount is a bool"),
            (
                lambda n: c.payout_batches.create(
                    items=[
                        {"network": "tron", "asset": "USDT", "amount": "1"},
                        {"network": "tron", "asset": "USDT", "amount": 2.0},
                    ]
                ),
                "/items/1/amount is a float",
            ),
            (
                lambda n: c.payment_links.create(title="Tips", open_amount={"currency": "USD", "presets": ["5", 10.0]}),
                "/open_amount/presets/1 is a float",
            ),
            (
                lambda n: c.rates.estimate(network="tron", asset="USDT", price_amount=12.5, price_currency="USD"),
                "/price_amount is a float",
            ),
            (
                lambda n: c.forwarding.update(
                    rules=[{"network": "tron", "asset": "USDT", "destination": "dst_1", "mode": "daily", "min_amount": 0.1}]
                ),
                "/rules/0/min_amount is a float",
            ),
        ]
        for call, message in cases:
            with self.subTest(message=message):
                with self.assertRaises(TypeError) as caught:
                    call(fake.client)
                self.assertEqual(str(caught.exception), f'{message}: amounts are decimal strings, such as "12.5"')
        self.assertEqual(fake.sent, [])

    def test_ints_and_finite_decimals_are_sent_as_decimal_strings(self) -> None:
        fake = Fake([answer(201, PAYMENT)] * 3 + [answer(200, {})])
        fake.client.payments.create(network="tron", asset="USDT", amount=25)
        fake.client.payments.create(network="tron", asset="USDT", amount=Decimal("12.50"))
        fake.client.payments.create(network="tron", asset="USDT", amount=Decimal("1E+2"))
        self.assertEqual([fake.body(i)["amount"] for i in range(3)], ["25", "12.50", "100"])
        fake.client.rates.estimate(network="tron", asset="USDT", price_amount=Decimal("0.5"), price_currency="USD")
        self.assertIn("price_amount=0.5&", fake.sent[3].url)
        for value in (Decimal("NaN"), Decimal("Infinity"), Decimal("-Infinity")):
            with self.assertRaisesRegex(ValueError, "/amount is .*: amounts are finite"):
                fake.client.payments.create(network="tron", asset="USDT", amount=value)
        self.assertEqual(len(fake.sent), 4)

    def test_amount_strings_are_sent_as_given_their_format_is_the_apis_to_check(self) -> None:
        fake = Fake([answer(201, PAYMENT)])
        fake.client.payments.create(network="tron", asset="USDT", amount="25.00", metadata={"qty": "2"})
        self.assertEqual(fake.body(0), {"network": "tron", "asset": "USDT", "amount": "25.00", "metadata": {"qty": "2"}})


class Helpers(unittest.TestCase):
    def test_to_units_gives_the_smallest_units_exactly(self) -> None:
        self.assertEqual(Amounts.to_units("1.5", 6), 1_500_000)
        self.assertEqual(Amounts.to_units("0", 18), 0)
        self.assertEqual(Amounts.to_units("12345678901234567890.123456789012345678", 18), 12345678901234567890123456789012345678)
        self.assertEqual(Amounts.to_units("1.500000000", 6), 1_500_000)
        self.assertEqual(Amounts.to_units("7", 0), 7)
        with self.assertRaisesRegex(ValueError, "more decimals than the asset's 6"):
            Amounts.to_units("1.0000001", 6)
        for bad in ("", "1.", ".5", "01", "-1", "1e3", " 1", "1,5", "١"):
            with self.subTest(bad=bad), self.assertRaises(TypeError):
                Amounts.to_units(bad, 6)
        for decimals in (-1, 256, 1.5, True):
            with self.assertRaises(TypeError):
                Amounts.to_units("1", decimals)  # type: ignore[arg-type]
        with self.assertRaises(TypeError):
            Amounts.to_units(1.5, 6)  # type: ignore[arg-type]

    def test_from_units_gives_the_apis_canonical_form(self) -> None:
        self.assertEqual(Amounts.from_units(1_500_000, 6), "1.5")
        self.assertEqual(Amounts.from_units(0, 6), "0")
        self.assertEqual(Amounts.from_units(1, 18), "0.000000000000000001")
        self.assertEqual(Amounts.from_units("1000000", 6), "1")
        self.assertEqual(Amounts.from_units(12345678901234567890123456789012345678, 18), "12345678901234567890.123456789012345678")
        self.assertEqual(Amounts.from_units(7, 0), "7")
        with self.assertRaisesRegex(ValueError, "negative"):
            Amounts.from_units(-1, 6)
        for bad in (1.5, True, "1.5", "-1", ""):
            with self.subTest(bad=bad), self.assertRaises(TypeError):
                Amounts.from_units(bad, 6)  # type: ignore[arg-type]

    def test_compare_orders_amounts_of_any_precision(self) -> None:
        self.assertEqual(Amounts.compare("1.5", "1.50"), 0)
        self.assertEqual(Amounts.compare("1.5", "1.49999999999999999999"), 1)
        self.assertEqual(Amounts.compare("9", "10"), -1)
        self.assertEqual(Amounts.compare("0", "0.000000000000000001"), -1)
        self.assertEqual(Amounts.compare("100", "99.999"), 1)
        with self.assertRaises(TypeError):
            Amounts.compare("1", "x")


if __name__ == "__main__":
    unittest.main()
