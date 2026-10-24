"""Bounded, exact product-unit ratios; never infer or silently round a quantity."""

import re
from decimal import ROUND_DOWN, Context, Decimal, localcontext


class UnitConversionError(ValueError):
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


def _positive(value, *, integer_digits, scale, code):
    if not isinstance(value, str) or not re.fullmatch(
        rf"[0-9]{{1,{integer_digits}}}(?:\.[0-9]{{1,{scale}}})?"
        if scale
        else rf"[0-9]{{1,{integer_digits}}}",
        value,
    ):
        raise UnitConversionError(code, "Use a bounded, plain positive decimal string.")
    result = Decimal(value)
    if result <= 0:
        raise UnitConversionError(
            code, "Quantity and approved ratios must be positive."
        )
    return result


def _limits(scale, max_integer_digits):
    if (
        type(scale) is not int
        or not 0 <= scale <= 9
        or type(max_integer_digits) is not int
        or not 1 <= max_integer_digits <= 18
    ):
        raise UnitConversionError(
            "unit_policy_invalid",
            "Choose a supported explicit quantity precision/range.",
        )


def convert_quantity(
    quantity,
    numerator,
    denominator,
    *,
    scale,
    max_integer_digits,
    source_scale=3,
    source_max_integer_digits=9,
):
    """Return fixed-scale text only when the approved rational result fits exactly.

    A case mapping can use numerator1/denominator12; twelve each then becomes one
    case without storing a rounded inverse multiplier. The caller supplies the
    approved product/unit identities and preserves the original requested fields.
    """
    _limits(scale, max_integer_digits)
    _limits(source_scale, source_max_integer_digits)
    requested = _positive(
        quantity,
        integer_digits=source_max_integer_digits,
        scale=source_scale,
        code="quantity_invalid",
    )
    multiply = _positive(
        numerator, integer_digits=12, scale=12, code="unit_ratio_invalid"
    )
    divide = _positive(
        denominator, integer_digits=12, scale=12, code="unit_ratio_invalid"
    )
    # At most51 significant digits are needed by the supported bounds. A local
    # context isolates exact verification from unrelated Decimal configuration.
    with localcontext(Context(prec=80, Emin=-999999, Emax=999999)):
        scaled_numerator = requested * multiply
        result = scaled_numerator / divide
        if result >= Decimal(10) ** max_integer_digits:
            raise UnitConversionError(
                "quantity_overflow", "Converted quantity exceeds the approved range."
            )
        candidate = result.quantize(Decimal(1).scaleb(-scale), rounding=ROUND_DOWN)
        # Even a repeating quotient truncated by Decimal precision cannot pass
        # this test. Reject instead of accepting a rounded approximation.
        if candidate * divide != scaled_numerator:
            raise UnitConversionError(
                "unit_precision",
                "This quantity cannot fit the approved unit precision exactly.",
            )
        if candidate <= 0:
            raise UnitConversionError(
                "quantity_invalid", "Converted quantity must remain positive."
            )
        return format(candidate, "f")
