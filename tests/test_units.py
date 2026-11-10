"""Unit tests for FiO2 normalisation and dose conversion (T-R1-a, T-R1-e).

Covers the shared definitions AC-DEF-8 (FiO2 units), AC-DEF-9 (weight-based
dose, missing weight), AC-DEF-10 (unsupported unit -> explicit error, never a
guess). Bed 1 (FiO2 charted 40 and 0.40) and bed 14 (mcg/kg/min with no
weight) are the oracle anchors.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from sanad.states import ReasonCode
from sanad.units import (
    UnsupportedUnitError,
    WeightMissingError,
    convert_dose,
    normalise_fio2,
)


# --- FiO2 normalisation (AC-DEF-8) ---------------------------------------


def test_bed1_fio2_40_percent_equals_0_40_fraction() -> None:
    # The core bed-1 equivalence: 40% and 0.40 normalise identically.
    assert normalise_fio2(40, "percent") == normalise_fio2(Decimal("0.40"), "fraction")
    assert normalise_fio2(40, "percent") == Decimal("0.40")


def test_fio2_fraction_passthrough_in_range() -> None:
    assert normalise_fio2(Decimal("0.21"), "fraction") == Decimal("0.21")
    assert normalise_fio2(Decimal("1.0"), "fraction") == Decimal("1.0")
    assert normalise_fio2(0.5, "fraction") == Decimal("0.5")


def test_fio2_percent_divided_by_100() -> None:
    assert normalise_fio2(21, "percent") == Decimal("0.21")
    assert normalise_fio2(100, "percent") == Decimal("1.0")
    assert normalise_fio2(55, "percent") == Decimal("0.55")


def test_fio2_equivalence_across_the_range() -> None:
    for pct in (21, 30, 40, 55, 80, 100):
        assert normalise_fio2(pct, "percent") == normalise_fio2(
            Decimal(pct) / Decimal(100), "fraction"
        )


def test_fio2_out_of_range_raises_unsupported() -> None:
    with pytest.raises(UnsupportedUnitError):
        normalise_fio2(Decimal("0.10"), "fraction")  # below 0.21
    with pytest.raises(UnsupportedUnitError):
        normalise_fio2(120, "percent")  # above 100
    with pytest.raises(UnsupportedUnitError):
        normalise_fio2(5, "percent")  # below 21


def test_fio2_unsupported_unit_raises_with_reason() -> None:
    with pytest.raises(UnsupportedUnitError) as exc:
        normalise_fio2(0.4, "ratio")
    assert exc.value.reason is ReasonCode.UNSUPPORTED_UNIT


# --- dose conversion (AC-DEF-9, AC-DEF-10) -------------------------------


def test_mcg_per_min_passthrough() -> None:
    # Absolute dose: no weight needed (bed 3 norepinephrine 8 mcg/min).
    assert convert_dose(8, "mcg/min", None) == Decimal("8")
    assert convert_dose(Decimal("9.5"), "mcg/min", 70) == Decimal("9.5")


def test_weight_based_dose_converts_with_weight() -> None:
    # 0.08 mcg/kg/min * 82 kg = 6.56 mcg/min.
    assert convert_dose(Decimal("0.08"), "mcg/kg/min", 82) == Decimal("6.56")


def test_bed14_weight_based_dose_missing_weight_errors() -> None:
    # Bed 14: 0.08 mcg/kg/min with weight null -> weight_missing, never guessed.
    with pytest.raises(WeightMissingError) as exc:
        convert_dose(Decimal("0.08"), "mcg/kg/min", None)
    assert exc.value.reason is ReasonCode.WEIGHT_MISSING


def test_units_per_min_has_no_mcg_conversion() -> None:
    # vasopressin 0.03 units/min is an "other agent" flag, not a mcg threshold.
    with pytest.raises(UnsupportedUnitError) as exc:
        convert_dose(Decimal("0.03"), "units/min", 90)
    assert exc.value.reason is ReasonCode.UNSUPPORTED_UNIT


def test_dose_unsupported_unit_errors() -> None:
    with pytest.raises(UnsupportedUnitError) as exc:
        convert_dose(5, "mg/hr", 70)
    assert exc.value.reason is ReasonCode.UNSUPPORTED_UNIT
