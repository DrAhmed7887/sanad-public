"""Loader scenario tests (T-loader).

Assert the loader reads all 18 fictional encounters and the five record files
into typed records, parses tz-aware times, and keeps ``daily_totals`` loaded
but segregated so rules can be shown to ignore it (AC-R2b-no-dailytotals).
These exercise the real fixed dataset under ``data/ward_seed42/``; they read
only, never write (safety steering).
"""

from __future__ import annotations

from datetime import timezone

import pytest

from sanad.loader import load_dataset
from sanad.model import (
    DailyTotal,
    Dataset,
    Encounter,
    Event,
    FluidTx,
    Infusion,
    Observation,
)


@pytest.fixture(scope="module")
def ds() -> Dataset:
    return load_dataset()


def test_loads_all_18_encounters(ds: Dataset) -> None:
    assert len(ds.encounters) == 18
    assert ds.meta["encounters"] == 18
    # Bed 13 carries two encounters (a reassignment); 17 distinct beds.
    assert len(ds.by_bed) == 17
    assert {e.encounter for e in ds.by_bed[13]} == {"E13A-1120", "E13B-1120"}
    # Every encounter is indexed and typed.
    assert all(isinstance(e, Encounter) for e in ds.encounters)
    assert set(ds.by_encounter) == {e.encounter for e in ds.encounters}


def test_loads_five_record_files_with_expected_counts(ds: Dataset) -> None:
    # Counts match data/DATA_CARD.md.
    assert len(ds.observations) == 4893
    assert len(ds.infusions) == 4
    assert len(ds.events) == 218
    assert len(ds.fluids) == 1003
    assert len(ds.daily_totals) == 84
    assert all(isinstance(o, Observation) for o in ds.observations)
    assert all(isinstance(i, Infusion) for i in ds.infusions)
    assert all(isinstance(e, Event) for e in ds.events)
    assert all(isinstance(f, FluidTx) for f in ds.fluids)
    assert all(isinstance(d, DailyTotal) for d in ds.daily_totals)


def test_times_are_timezone_aware(ds: Dataset) -> None:
    assert ds.observations[0].t.tzinfo is not None
    assert ds.observations[0].t.utcoffset() is not None
    f = ds.fluids[0]
    assert f.event_time.tzinfo is not None and f.documented_time.tzinfo is not None
    # Dataset zone is +01:00.
    assert ds.observations[0].t.utcoffset().total_seconds() == 3600


def test_daily_totals_loaded_but_flagged_unused(ds: Dataset) -> None:
    # Present (so its absence cannot hide a bug) ...
    assert ds.daily_totals, "daily_totals must be loaded"
    # ... but segregated from the ledger the rules reduce over: it is reachable
    # ONLY via Dataset.daily_totals, not mixed into fluids. The distractor
    # resets at 07:00; the real ledger (fluids) does not carry that field.
    assert all(isinstance(d, DailyTotal) for d in ds.daily_totals)
    assert not hasattr(ds.fluids[0], "charting_day_from_0700")
    assert not hasattr(ds.fluids[0], "net_ml")


def test_event_tagged_union_parses_each_type(ds: Dataset) -> None:
    by_type: dict[str, Event] = {}
    for e in ds.events:
        by_type.setdefault(e.type, e)
    # Every documented event type from the dataset is represented and parsed.
    for etype in ("vent_check", "sat", "rass", "planned_change",
                  "feed_status", "deferral", "staff_action",
                  "admission", "discharge"):
        assert etype in by_type, f"missing event type {etype}"

    vc = next(e for e in ds.events if e.type == "vent_check")
    # A valid vent_check carries all three fields plus two distinct times.
    assert vc.effort is not None
    assert vc.haemodynamics is not None
    assert vc.cuff_pressure_cmH2O is not None
    assert vc.event_time == vc.performed_at
    assert vc.documented_time == vc.documented_at
    assert vc.documented_time >= vc.event_time

    deferral = next(e for e in ds.events if e.type == "deferral")
    assert deferral.until is not None and deferral.owner is not None
    assert deferral.rule is not None and deferral.reason is not None


def test_bed14_weight_missing_is_none_not_guessed(ds: Dataset) -> None:
    bed14 = ds.by_encounter["E14-1120"]
    assert bed14.weight_kg is None


def test_bed1_fio2_charted_both_ways(ds: Dataset) -> None:
    # Bed 1 charts FiO2 as 0.5/0.40 (fraction) and 40 (percent) on alternate
    # rows; the loader normalises both to a fraction (AC-DEF-8).
    bed1 = [o for o in ds.observations if o.encounter == "E01-1120"]
    units = {o.fio2_unit for o in bed1}
    assert "fraction" in units and "percent" in units
    for o in bed1:
        if o.fio2_unit == "percent":
            # 40 percent normalises to 0.40 fraction.
            assert o.fio2_fraction == o.fio2 / 100
        else:
            assert o.fio2_fraction == o.fio2


def test_load_is_deterministic(ds: Dataset) -> None:
    # Re-loading yields identical ordered records (determinism; re-run safe).
    again = load_dataset()
    assert again.observations == ds.observations
    assert again.fluids == ds.fluids
    assert again.events == ds.events
    assert again.infusions == ds.infusions
    assert again.encounters == ds.encounters
