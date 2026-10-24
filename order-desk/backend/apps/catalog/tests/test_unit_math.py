"""Arithmetic contracts only; these tests do not approve customer unit mappings."""

import unittest
from decimal import Decimal, Inexact, getcontext, localcontext

from apps.catalog.unit_math import UnitConversionError, convert_quantity


class UnitMathTests(unittest.TestCase):
    def convert(self, quantity, numerator="1", denominator="1", **options):
        return convert_quantity(
            quantity,
            numerator,
            denominator,
            scale=options.pop("scale", 3),
            max_integer_digits=options.pop("max_integer_digits", 9),
            **options,
        )

    def assert_code(self, code, *args, **options):
        with self.assertRaises(UnitConversionError) as observed:
            self.convert(*args, **options)
        self.assertEqual(observed.exception.code, code)

    def test_exact_identity_retains_configured_scale(self):
        self.assertEqual(self.convert("1.250"), "1.250")
        self.assertEqual(self.convert("00001.250", scale=4), "1.2500")
        self.assertEqual(self.convert("999999999.999"), "999999999.999")

    def test_exact_pack_and_inverse_need_no_approximate_multiplier(self):
        self.assertEqual(self.convert("12.000", "1", "12", scale=0), "1")
        self.assertEqual(self.convert("1.250", "12", "1", scale=0), "15")
        self.assertEqual(self.convert("3", "1", "3", scale=0), "1")
        self.assertEqual(self.convert("0.300", "0.1", "0.3", scale=1), "0.1")

    def test_repeating_or_discarded_precision_is_rejected(self):
        for quantity, numerator, denominator, scale in (
            ("1", "1", "12", 9),
            ("1", "1", "3", 9),
            ("1.250", "1", "1", 1),
            ("0.001", "1", "1000", 3),
        ):
            self.assert_code(
                "unit_precision", quantity, numerator, denominator, scale=scale
            )

    def test_range_is_checked_before_returning_any_quantity(self):
        self.assert_code("quantity_overflow", "999999999.999", "12")
        self.assert_code(
            "quantity_overflow",
            "1",
            "100000000000",
            "0.000000000001",
            max_integer_digits=18,
        )
        self.assertEqual(
            self.convert("999999999.999", "12", max_integer_digits=12),
            "11999999999.988",
        )

    def test_numeric_and_non_plain_source_inputs_are_rejected(self):
        for value in (
            1,
            1.25,
            True,
            Decimal("1.25"),
            "",
            "0",
            "-1",
            "+1",
            "1e3",
            "NaN",
            "Infinity",
            " 1",
            "1 ",
            "١",
            "1.0001",
            "1000000000",
        ):
            with self.subTest(value=repr(value)):
                self.assert_code("quantity_invalid", value)

    def test_ratios_must_be_explicit_positive_bounded_decimal_strings(self):
        for value in (
            1,
            1.5,
            False,
            "0",
            "-1",
            "1e2",
            "NaN",
            "",
            "1000000000000",
            "0.0000000000001",
        ):
            for numerator, denominator in ((value, "1"), ("1", value)):
                self.assert_code("unit_ratio_invalid", "1", numerator, denominator)

    def test_precision_and_range_configuration_is_bounded_and_typed(self):
        for options in (
            {"scale": True},
            {"scale": -1},
            {"scale": 10},
            {"scale": "3"},
            {"max_integer_digits": 0},
            {"max_integer_digits": 19},
            {"max_integer_digits": False},
            {"source_scale": 10},
        ):
            self.assert_code("unit_policy_invalid", "1", **options)

    def test_second_conversion_uses_explicit_supported_source_bounds(self):
        selling = self.convert("999999999.999", "12", max_integer_digits=12)
        self.assertEqual(
            self.convert(selling, "1", "12", source_max_integer_digits=12),
            "999999999.999",
        )

    def test_local_context_cannot_round_or_mutate_ambient_precision(self):
        with localcontext() as context:
            context.prec = 5
            context.Emax = 3
            context.Emin = -3
            context.traps[Inexact] = True
            before = getcontext().copy()
            self.assertEqual(
                self.convert("999999999.999", "12", max_integer_digits=12),
                "11999999999.988",
            )
            self.assert_code("unit_precision", "1", "1", "3", scale=9)
            self.assertEqual(getcontext().prec, before.prec)
            self.assertEqual(getcontext().rounding, before.rounding)
            self.assertEqual(getcontext().Emax, before.Emax)
            self.assertEqual(getcontext().traps, before.traps)


if __name__ == "__main__":
    unittest.main()
