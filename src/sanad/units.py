"""Unit handling: FiO2 normalisation and weight-based dose conversion.

Threshold-sensitive arithmetic uses :class:`~decimal.Decimal` so that a value
charted as a fraction and the same value charted as a percent normalise to the
*identical* number (AC-DEF-8, PBT-2) and no float rounding can nudge a reading
across a threshold.

The rules of the baseline (``docs/EVIDENCE.md`` line 19):

* FiO2 is accepted as a fraction (0.21-1.0) or a percent (21-100) and
  normalised to a fraction.
* A weight-based dose is converted only with a recorded weight; a missing
  weight -> ``unknown`` (never a guessed weight).
* An unsupported unit -> an explicit error, never a guessed conversion.

The functions raise typed errors; callers (rule modules) translate them into
``unknown`` results with the matching reason code.

Stdlib only.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Optional, Union

from .states import ReasonCode

__all__ = [
    "UnitError",
    "UnsupportedUnitError",
    "WeightMissingError",
    "normalise_fio2",
    "convert_dose",
    "SUPPORTED_FIO2_UNITS",
    "SUPPORTED_DOSE_UNITS",
]

# FiO2 physiological bounds, as Decimals so comparisons stay exact.
_FIO2_FRACTION_MIN = Decimal("0.21")
_FIO2_FRACTION_MAX = Decimal("1.0")
_FIO2_PERCENT_MIN = Decimal("21")
_FIO2_PERCENT_MAX = Decimal("100")
_ONE_HUNDRED = Decimal("100")

SUPPORTED_FIO2_UNITS = frozenset({"fraction", "percent"})
SUPPORTED_DOSE_UNITS = frozenset({"mcg/min", "mcg/kg/min", "units/min"})

Number = Union[int, float, str, Decimal]


class UnitError(Exception):
    """Base class for unit problems. Carries a :class:`ReasonCode`."""

    def __init__(self, message: str, reason: ReasonCode) -> None:
        super().__init__(message)
        self.reason = reason


class UnsupportedUnitError(UnitError):
    """A value carried a unit the engine does not support (AC-DEF-10)."""

    def __init__(self, message: str) -> None:
        super().__init__(message, ReasonCode.UNSUPPORTED_UNIT)


class WeightMissingError(UnitError):
    """A weight-based dose needs a weight that was not recorded (AC-DEF-9)."""

    def __init__(self, message: str) -> None:
        super().__init__(message, ReasonCode.WEIGHT_MISSING)


def _to_decimal(value: Number) -> Decimal:
    """Convert a raw value to Decimal without going through binary float.

    ``float`` inputs are routed through ``repr`` so e.g. ``0.4`` becomes
    ``Decimal("0.4")`` rather than the long binary expansion, keeping
    fraction/percent equivalence exact.
    """

    if isinstance(value, Decimal):
        return value
    if isinstance(value, float):
        return Decimal(repr(value))
    return Decimal(str(value))


def normalise_fio2(value: Number, unit: str) -> Decimal:
    """Normalise a FiO2 reading to a fraction in [0.21, 1.0].

    ``fraction`` values in range pass through; ``percent`` values in range are
    divided by 100. Equal physical values in the two units return the identical
    Decimal, so ``normalise_fio2(40, "percent") == normalise_fio2(0.40,
    "fraction")`` (AC-DEF-8; bed 1 charts both forms). Out-of-range values or
    any other unit raise :class:`UnsupportedUnitError` -- never a guess
    (AC-DEF-10).
    """

    if unit not in SUPPORTED_FIO2_UNITS:
        raise UnsupportedUnitError(f"unsupported FiO2 unit {unit!r}")

    dec = _to_decimal(value)

    if unit == "fraction":
        if not (_FIO2_FRACTION_MIN <= dec <= _FIO2_FRACTION_MAX):
            raise UnsupportedUnitError(
                f"FiO2 fraction {dec} out of range [0.21, 1.0]"
            )
        return dec

    # percent
    if not (_FIO2_PERCENT_MIN <= dec <= _FIO2_PERCENT_MAX):
        raise UnsupportedUnitError(
            f"FiO2 percent {dec} out of range [21, 100]"
        )
    # Divide exactly, then normalise so 40/100 == 0.40 as Decimals.
    return (dec / _ONE_HUNDRED).normalize() + Decimal(0)


def convert_dose(
    dose: Number, unit: str, weight_kg: Optional[Number]
) -> Decimal:
    """Convert an infusion dose to absolute mcg/min where that is meaningful.

    * ``mcg/min``     : already absolute -> pass through.
    * ``mcg/kg/min``  : weight-based -> multiply by ``weight_kg``; a missing
      weight raises :class:`WeightMissingError` (AC-DEF-9; bed 14).
    * ``units/min``   : an "other agent" unit (e.g. vasopressin); it is *not* a
      mcg threshold, so there is no numeric conversion and this raises
      :class:`UnsupportedUnitError`. The rule layer flags the agent rather than
      comparing a mcg value.
    * anything else   : :class:`UnsupportedUnitError` (AC-DEF-10).
    """

    if unit not in SUPPORTED_DOSE_UNITS:
        raise UnsupportedUnitError(f"unsupported dose unit {unit!r}")

    dec = _to_decimal(dose)

    if unit == "mcg/min":
        return dec

    if unit == "mcg/kg/min":
        if weight_kg is None:
            raise WeightMissingError(
                "weight-based dose (mcg/kg/min) with no recorded weight"
            )
        return dec * _to_decimal(weight_kg)

    # units/min: no mcg conversion exists; the caller must flag, not convert.
    raise UnsupportedUnitError(
        "unit 'units/min' has no mcg/min conversion; flag the agent instead"
    )
