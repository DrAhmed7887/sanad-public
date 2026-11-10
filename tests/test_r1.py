"""R1 tests: the SBT-screen scenario oracle and the four build-time unit cases.

Scenario-oracle part asserts the engine's R1 output against the per-bed
expectations in ``data/SCENARIOS.md`` (the frozen oracle), on the 5-minute grid:

* bed 1  -- ``met`` from 22:20 (clock from the 20:15 SAT), exactly one prompt;
* bed 2  -- ``unknown`` all night (``sat_not_recorded``);
* bed 3  -- ``unknown`` all night (``sat_not_recorded`` before 19:30, then
  ``haemo_unconfirmed``), both agents displayed;
* bed 11 -- ``not_applicable`` (VV-ECMO);
* bed 12 -- DNR is not an exclusion; ``met`` from 23:05;
* bed 14 -- ``unknown`` all night (``weight_missing``);
* bed 15 -- ``met`` 20:35-20:40, ``suppressed`` 20:45-01:25, ``met`` again at
  01:30 (two prompts, no midnight reset), ``unknown`` from 06:35.

The unit part covers the four cases the oracle cannot (SCENARIOS.md footnote):
the R1-c NMBA criterion, the R1-f context gate (RR > 35, pH < 7.30),
confirmation expiry on a vasoactive dose change (AC-DEF-12), and an unsupported
unit. These build synthetic contexts only.

Reads the fixed dataset read-only (safety steering); never writes.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from sanad.loader import load_dataset
from sanad.model import Dataset, Event, Infusion, Observation
from sanad.r1 import (
    R1Context,
    context_for,
    evaluate_r1,
    r1_prompt_times,
)
from sanad.states import EvaluationState, R1_MET_TEXT, ReasonCode
from sanad.timeline import grid

TZ = timezone(timedelta(hours=1))


def dt(d=20, h=19, mi=0) -> datetime:
    return datetime(2026, 11, d, h, mi, tzinfo=TZ)


@pytest.fixture(scope="module")
def ds() -> Dataset:
    return load_dataset()


def _night_grid() -> list[datetime]:
    # The board window 19:00 (20 Nov) .. 07:00 (21 Nov), inclusive.
    return grid(dt(d=20, h=19), dt(d=21, h=7))


# ==========================================================================
# Bed 1: met from 22:20 (clock from 20:15), exactly one prompt.
# ==========================================================================


def test_bed1_met_from_2220_clock_from_sat(ds: Dataset) -> None:
    ctx = context_for(ds, "E01-1120")
    # Not yet met one grid step before (span == 120 min, "more than" is strict).
    r_before = evaluate_r1(ctx, dt(d=20, h=22, mi=15))
    assert r_before.state is EvaluationState.NOT_MET
    # Met at 22:20 with the exact approved wording.
    r_at = evaluate_r1(ctx, dt(d=20, h=22, mi=20))
    assert r_at.state is EvaluationState.MET
    assert r_at.message == R1_MET_TEXT
    # Stays met for the rest of the night window.
    for t in grid(dt(d=20, h=22, mi=20), dt(d=21, h=7)):
        assert evaluate_r1(ctx, t).state is EvaluationState.MET


def test_bed1_exactly_one_prompt(ds: Dataset) -> None:
    ctx = context_for(ds, "E01-1120")
    prompts = r1_prompt_times(ctx, _night_grid())
    assert prompts == [dt(d=20, h=22, mi=20)]


def test_bed1_fio2_units_mixed_are_equivalent(ds: Dataset) -> None:
    # Bed 1 charts FiO2 as 0.40 and 40 on alternate rows; both must read as the
    # same fraction, so the 19:05 (percent) row is just as "met-eligible".
    ctx = context_for(ds, "E01-1120")
    percent_row = next(
        o for o in ctx.observations if o.t == dt(d=20, h=19, mi=5)
    )
    fraction_row = next(
        o for o in ctx.observations if o.t == dt(d=20, h=19, mi=0)
    )
    assert percent_row.fio2_unit == "percent"
    assert fraction_row.fio2_unit == "fraction"
    assert percent_row.fio2_fraction == fraction_row.fio2_fraction == Decimal("0.4")


# ==========================================================================
# Bed 2: unknown all night, sat_not_recorded.
# ==========================================================================


def test_bed2_unknown_sat_not_recorded_all_night(ds: Dataset) -> None:
    ctx = context_for(ds, "E02-1120")
    for t in _night_grid():
        r = evaluate_r1(ctx, t)
        assert r.state is EvaluationState.UNKNOWN
        assert r.reason is ReasonCode.SAT_NOT_RECORDED


# ==========================================================================
# Bed 3: unknown all night; sat_not_recorded before 19:30, then
# haemo_unconfirmed; both agents displayed.
# ==========================================================================


def test_bed3_unknown_switches_from_sat_to_haemo(ds: Dataset) -> None:
    ctx = context_for(ds, "E03-1120")
    # SAT passes at 19:30: before that, criterion 0 is the blocking unknown.
    before = evaluate_r1(ctx, dt(d=20, h=19, mi=25))
    assert before.state is EvaluationState.UNKNOWN
    assert before.reason is ReasonCode.SAT_NOT_RECORDED
    # From 19:30 the SAT is satisfied, so the unconfirmed extra pressor blocks.
    after = evaluate_r1(ctx, dt(d=20, h=19, mi=30))
    assert after.state is EvaluationState.UNKNOWN
    assert after.reason is ReasonCode.HAEMO_UNCONFIRMED
    # Both agents are shown (one drug must not hide another).
    assert "norepinephrine" in after.detail
    assert "vasopressin" in after.detail


def test_bed3_unknown_all_night(ds: Dataset) -> None:
    ctx = context_for(ds, "E03-1120")
    for t in _night_grid():
        assert evaluate_r1(ctx, t).state is EvaluationState.UNKNOWN


# ==========================================================================
# Bed 11: not_applicable (VV-ECMO).
# ==========================================================================


def test_bed11_not_applicable_ecmo(ds: Dataset) -> None:
    ctx = context_for(ds, "E11-1120")
    for t in _night_grid():
        r = evaluate_r1(ctx, t)
        assert r.state is EvaluationState.NOT_APPLICABLE
        assert r.reason is ReasonCode.PATHWAY_EXCLUDED
        assert "ecmo" in r.detail.lower()


# ==========================================================================
# Bed 12: DNR is not an exclusion; met from 23:05.
# ==========================================================================


def test_bed12_dnr_met_from_2305(ds: Dataset) -> None:
    ctx = context_for(ds, "E12-1120")
    assert evaluate_r1(ctx, dt(d=20, h=23, mi=0)).state is EvaluationState.NOT_MET
    r = evaluate_r1(ctx, dt(d=20, h=23, mi=5))
    assert r.state is EvaluationState.MET
    assert r.message == R1_MET_TEXT
    # DNR alone never yields not_applicable.
    for t in _night_grid():
        assert evaluate_r1(ctx, t).state is not EvaluationState.NOT_APPLICABLE


def test_bed12_one_prompt(ds: Dataset) -> None:
    ctx = context_for(ds, "E12-1120")
    assert r1_prompt_times(ctx, _night_grid()) == [dt(d=20, h=23, mi=5)]


# ==========================================================================
# Bed 14: unknown all night, weight_missing (never a guessed weight).
# ==========================================================================


def test_bed14_unknown_weight_missing(ds: Dataset) -> None:
    ctx = context_for(ds, "E14-1120")
    # SAT passes 19:30; from then the weight-based pressor cannot be resolved.
    r = evaluate_r1(ctx, dt(d=20, h=20, mi=0))
    assert r.state is EvaluationState.UNKNOWN
    assert r.reason is ReasonCode.WEIGHT_MISSING
    # Never met at any point.
    for t in _night_grid():
        assert evaluate_r1(ctx, t).state is not EvaluationState.MET


# ==========================================================================
# Bed 15: met 20:35-20:40, suppressed 20:45-01:25, met again 01:30
# (two prompts, no midnight reset), unknown from 06:35.
# ==========================================================================


def test_bed15_first_episode_and_deferral(ds: Dataset) -> None:
    ctx = context_for(ds, "E15-1120")
    # First met at 20:35 (clock from the 18:30 SAT).
    assert evaluate_r1(ctx, dt(d=20, h=20, mi=30)).state is EvaluationState.NOT_MET
    assert evaluate_r1(ctx, dt(d=20, h=20, mi=35)).state is EvaluationState.MET
    assert evaluate_r1(ctx, dt(d=20, h=20, mi=40)).state is EvaluationState.MET
    # Deferral documented 20:45 "until 01:30" -> suppressed across midnight.
    for t in grid(dt(d=20, h=20, mi=45), dt(d=21, h=1, mi=25)):
        r = evaluate_r1(ctx, t)
        assert r.state is EvaluationState.SUPPRESSED
        assert r.reason is ReasonCode.HELD_DEFERRED
        assert "01:30" in r.detail


def test_bed15_second_episode_at_0130_no_midnight_reset(ds: Dataset) -> None:
    ctx = context_for(ds, "E15-1120")
    # The hold lapses at 01:30 and the rule re-evaluates -> met again.
    assert evaluate_r1(ctx, dt(d=21, h=1, mi=30)).state is EvaluationState.MET


def test_bed15_sat_expires_unknown_from_0635(ds: Dataset) -> None:
    ctx = context_for(ds, "E15-1120")
    # SAT at 18:30 + 12 h = 06:30: still within at 06:30, stale from 06:35.
    assert evaluate_r1(ctx, dt(d=21, h=6, mi=30)).state is EvaluationState.MET
    r = evaluate_r1(ctx, dt(d=21, h=6, mi=35))
    assert r.state is EvaluationState.UNKNOWN
    assert r.reason is ReasonCode.SAT_NOT_RECORDED


def test_bed15_exactly_two_prompts(ds: Dataset) -> None:
    ctx = context_for(ds, "E15-1120")
    prompts = r1_prompt_times(ctx, _night_grid())
    assert prompts == [dt(d=20, h=20, mi=35), dt(d=21, h=1, mi=30)]


# ==========================================================================
# Unit tests: the four cases no bed covers (SCENARIOS.md footnote).
# ==========================================================================


def _obs(
    t: datetime, *, fio2="0.40", unit="fraction", peep=5, rr=18, sbp=120,
) -> Observation:
    frac = Decimal(str(fio2)) if unit == "fraction" else Decimal(str(fio2)) / 100
    return Observation(
        bed=99, encounter="SYN", t=t,
        fio2=Decimal(str(fio2)), fio2_unit=unit, fio2_fraction=frac,
        peep=peep, peep_unit="cmH2O", spo2=96, spo2_quality="good",
        rr=rr, sbp=sbp, hr=80, spont_effort_flag=True,
    )


def _check(performed: datetime, *, effort="adequate", haemo="acceptable") -> Event:
    return Event(
        bed=99, encounter="SYN", type="vent_check",
        performed_at=performed, documented_at=performed + timedelta(minutes=4),
        effort=effort, haemodynamics=haemo, cuff_pressure_cmH2O=25,
    )


def _sat(t: datetime, result="pass") -> Event:
    return Event(bed=99, encounter="SYN", type="sat", t=t, result=result)


def _synthetic_ctx(
    *, observations, infusions=(), events=(), weight_kg=80, pathways=(),
    code_status="full", ph=None,
) -> R1Context:
    return R1Context(
        encounter="SYN", bed=99, weight_kg=weight_kg, code_status=code_status,
        pathways=tuple(pathways), observations=tuple(observations),
        infusions=tuple(infusions), events=tuple(events), ph=ph,
    )


def _held_observations(start: datetime, end: datetime) -> list[Observation]:
    # A steady, screen-passing observation every 5 min across [start, end],
    # plus a matching reference 12 h earlier so criterion b resolves.
    out: list[Observation] = []
    t = start - timedelta(hours=12)
    while t <= end:
        out.append(_obs(t))
        t += timedelta(minutes=5)
    return out


def _checks_every_2h(first: datetime, end: datetime) -> list[Event]:
    # Ventilation checks at ``first`` and every 2 h up to ``end`` so a valid
    # effort/haemodynamics confirmation covers the whole duration window on the
    # 5-minute grid (each is valid for 2 h).
    out: list[Event] = []
    t = first
    while t <= end:
        out.append(_check(t))
        t += timedelta(hours=2)
    return out


# --- R1-c: NMBA infusing -> not_met (nmba_infusing) ------------------------


def test_unit_r1c_nmba_infusing_is_not_met() -> None:
    t = dt(d=20, h=23, mi=0)
    obs = _held_observations(dt(d=20, h=17, mi=0), t)
    nmba = Infusion(
        bed=99, encounter="SYN", drug="cisatracurium", dose=Decimal("2"),
        unit="mcg/kg/min", start=dt(d=20, h=18, mi=0), end=dt(d=21, h=7, mi=0),
    )
    ctx = _synthetic_ctx(
        observations=obs, infusions=[nmba],
        events=[_sat(dt(d=20, h=17, mi=0))]
        + _checks_every_2h(dt(d=20, h=17, mi=0), t),
    )
    r = evaluate_r1(ctx, t)
    assert r.state is EvaluationState.NOT_MET
    assert r.reason is ReasonCode.NMBA_INFUSING


def test_unit_r1c_no_nmba_is_satisfied() -> None:
    # Same context without the NMBA reaches met (criteria + duration hold).
    t = dt(d=20, h=23, mi=0)
    obs = _held_observations(dt(d=20, h=17, mi=0), t)
    ctx = _synthetic_ctx(
        observations=obs,
        events=[_sat(dt(d=20, h=17, mi=0))]
        + _checks_every_2h(dt(d=20, h=17, mi=0), t),
    )
    assert evaluate_r1(ctx, t).state is EvaluationState.MET


# --- R1-f: context gate RR > 35 or pH < 7.30 -> not_met (context_review) ---


def test_unit_r1f_high_rr_gate_not_met() -> None:
    t = dt(d=20, h=23, mi=0)
    obs = _held_observations(dt(d=20, h=19, mi=0), t)
    # Replace the newest observation with a high-RR one.
    obs[-1] = _obs(t, rr=40)
    ctx = _synthetic_ctx(
        observations=obs,
        events=[_sat(dt(d=20, h=19, mi=0)), _check(dt(d=20, h=22, mi=30))],
    )
    r = evaluate_r1(ctx, t)
    assert r.state is EvaluationState.NOT_MET
    assert r.reason is ReasonCode.CONTEXT_REVIEW
    assert "RR" in r.detail


def test_unit_r1f_low_ph_gate_not_met() -> None:
    # pH is not in the dataset, so exercise the gate helper directly.
    from sanad.r1 import _crit_f_gate

    obs = _obs(dt(d=20, h=23, mi=0))
    blocked = _crit_f_gate(obs, ph=Decimal("7.29"))
    assert blocked is not None
    assert blocked.reason is ReasonCode.CONTEXT_REVIEW
    # pH exactly 7.30 is acceptable (>= 7.30 passes the SBT tolerance).
    assert _crit_f_gate(obs, ph=Decimal("7.30")) is None


# --- AC-DEF-12: confirmation expiry on a vasoactive dose change ------------


def test_unit_confirmation_ends_early_on_pressor_start() -> None:
    # Effort confirmed at 21:00 (valid to 23:00). A norepinephrine infusion
    # *starts* at 22:00 -> the confirmation ends early, so at 22:30 effort is no
    # longer valid even though only 90 min have passed.
    t = dt(d=20, h=22, mi=30)
    obs = _held_observations(dt(d=20, h=17, mi=0), t)
    check = _check(dt(d=20, h=21, mi=0))
    pressor = Infusion(
        bed=99, encounter="SYN", drug="norepinephrine", dose=Decimal("5"),
        unit="mcg/min", start=dt(d=20, h=22, mi=0), end=dt(d=21, h=7, mi=0),
    )
    ctx = _synthetic_ctx(
        observations=obs, infusions=[pressor],
        events=[_sat(dt(d=20, h=17, mi=0)), check],
    )
    r = evaluate_r1(ctx, t)
    assert r.state is EvaluationState.UNKNOWN
    assert r.reason is ReasonCode.CONFIRMATION_EXPIRED


def test_unit_confirmation_valid_within_two_hours_no_change() -> None:
    # Control: same confirmation with no vasoactive change is still valid.
    t = dt(d=20, h=22, mi=30)
    obs = _held_observations(dt(d=20, h=17, mi=0), t)
    ctx = _synthetic_ctx(
        observations=obs,
        events=[_sat(dt(d=20, h=17, mi=0))]
        + _checks_every_2h(dt(d=20, h=17, mi=0), t),
    )
    # Criteria + duration hold and the confirmation is valid -> met.
    assert evaluate_r1(ctx, t).state is EvaluationState.MET


# --- unsupported unit on a pressor dose -> unknown (unsupported_unit) -------


def test_unit_unsupported_pressor_unit_is_unknown() -> None:
    t = dt(d=20, h=23, mi=0)
    obs = _held_observations(dt(d=20, h=19, mi=0), t)
    bad = Infusion(
        bed=99, encounter="SYN", drug="norepinephrine", dose=Decimal("5"),
        unit="mg/hr", start=dt(d=20, h=18, mi=0), end=dt(d=21, h=7, mi=0),
    )
    ctx = _synthetic_ctx(
        observations=obs, infusions=[bad],
        events=[_sat(dt(d=20, h=19, mi=0)), _check(dt(d=20, h=22, mi=30))],
    )
    r = evaluate_r1(ctx, t)
    assert r.state is EvaluationState.UNKNOWN
    assert r.reason is ReasonCode.UNSUPPORTED_UNIT


# ==========================================================================
# Review fix 1 (BLOCK): dopamine / dobutamine compare in mcg/kg/min, not the
# absolute mcg/min used for norepinephrine's < 10 mcg/min threshold.
# (docs/EVIDENCE.md R1-e: "dopamine and dobutamine < 5 mcg/kg/min".)
# ==========================================================================


def _met_context_with_infusion(inf: Infusion, *, weight_kg=80, ph=None):
    """A synthetic context that otherwise reaches ``met`` at 23:00, so the only
    thing that can block is the supplied infusion in criterion e."""

    t = dt(d=20, h=23, mi=0)
    obs = _held_observations(dt(d=20, h=17, mi=0), t)
    ctx = _synthetic_ctx(
        observations=obs, infusions=[inf], weight_kg=weight_kg, ph=ph,
        events=[_sat(dt(d=20, h=17, mi=0))]
        + _checks_every_2h(dt(d=20, h=17, mi=0), t),
    )
    return ctx, t


def test_unit_r1e_dopamine_low_mcg_kg_min_is_met() -> None:
    # 3 mcg/kg/min dopamine on an 80 kg patient = 240 mcg/min absolute. The old
    # code compared 240 >= 5 and wrongly returned not_met; the correct weight-
    # indexed comparison is 3 < 5 -> satisfied, so the screen reaches met.
    inf = Infusion(
        bed=99, encounter="SYN", drug="dopamine", dose=Decimal("3"),
        unit="mcg/kg/min", start=dt(d=20, h=16, mi=0), end=dt(d=21, h=7, mi=0),
    )
    ctx, t = _met_context_with_infusion(inf)
    assert evaluate_r1(ctx, t).state is EvaluationState.MET


def test_unit_r1e_dobutamine_low_mcg_kg_min_is_met() -> None:
    inf = Infusion(
        bed=99, encounter="SYN", drug="dobutamine", dose=Decimal("4.9"),
        unit="mcg/kg/min", start=dt(d=20, h=16, mi=0), end=dt(d=21, h=7, mi=0),
    )
    ctx, t = _met_context_with_infusion(inf)
    assert evaluate_r1(ctx, t).state is EvaluationState.MET


def test_unit_r1e_dopamine_at_or_above_5_mcg_kg_min_is_not_met() -> None:
    # 5 mcg/kg/min is not < 5 -> recorded negative, not_met.
    inf = Infusion(
        bed=99, encounter="SYN", drug="dopamine", dose=Decimal("5"),
        unit="mcg/kg/min", start=dt(d=20, h=16, mi=0), end=dt(d=21, h=7, mi=0),
    )
    ctx, t = _met_context_with_infusion(inf)
    r = evaluate_r1(ctx, t)
    assert r.state is EvaluationState.NOT_MET
    assert "mcg/kg/min" in r.detail


def test_unit_r1e_dopamine_charted_mcg_min_indexed_by_weight() -> None:
    # A dose charted in absolute mcg/min must be divided by weight before the
    # weight-based threshold. 320 mcg/min / 80 kg = 4 mcg/kg/min < 5 -> met.
    inf = Infusion(
        bed=99, encounter="SYN", drug="dopamine", dose=Decimal("320"),
        unit="mcg/min", start=dt(d=20, h=16, mi=0), end=dt(d=21, h=7, mi=0),
    )
    ctx, t = _met_context_with_infusion(inf, weight_kg=80)
    assert evaluate_r1(ctx, t).state is EvaluationState.MET
    # 480 mcg/min / 80 kg = 6 mcg/kg/min >= 5 -> not_met.
    inf_high = Infusion(
        bed=99, encounter="SYN", drug="dopamine", dose=Decimal("480"),
        unit="mcg/min", start=dt(d=20, h=16, mi=0), end=dt(d=21, h=7, mi=0),
    )
    ctx_high, t_high = _met_context_with_infusion(inf_high, weight_kg=80)
    assert evaluate_r1(ctx_high, t_high).state is EvaluationState.NOT_MET


def test_unit_r1e_dopamine_missing_weight_is_unknown() -> None:
    # The dopamine/dobutamine threshold is weight-based, so with no weight it is
    # unknown/weight_missing even when the dose is charted in mcg/min (never a
    # guessed weight).
    inf = Infusion(
        bed=99, encounter="SYN", drug="dopamine", dose=Decimal("200"),
        unit="mcg/min", start=dt(d=20, h=16, mi=0), end=dt(d=21, h=7, mi=0),
    )
    ctx, t = _met_context_with_infusion(inf, weight_kg=None)
    r = evaluate_r1(ctx, t)
    assert r.state is EvaluationState.UNKNOWN
    assert r.reason is ReasonCode.WEIGHT_MISSING


def test_unit_r1e_dobutamine_mcg_kg_min_missing_weight_is_unknown() -> None:
    inf = Infusion(
        bed=99, encounter="SYN", drug="dobutamine", dose=Decimal("3"),
        unit="mcg/kg/min", start=dt(d=20, h=16, mi=0), end=dt(d=21, h=7, mi=0),
    )
    ctx, t = _met_context_with_infusion(inf, weight_kg=None)
    r = evaluate_r1(ctx, t)
    assert r.state is EvaluationState.UNKNOWN
    assert r.reason is ReasonCode.WEIGHT_MISSING


def test_unit_r1e_norepinephrine_threshold_still_absolute_mcg_min() -> None:
    # Regression guard: norepinephrine stays an absolute mcg/min comparison.
    # 8 mcg/min < 10 -> met; 10 mcg/min is not < 10 -> not_met.
    ok = Infusion(
        bed=99, encounter="SYN", drug="norepinephrine", dose=Decimal("8"),
        unit="mcg/min", start=dt(d=20, h=16, mi=0), end=dt(d=21, h=7, mi=0),
    )
    ctx_ok, t_ok = _met_context_with_infusion(ok)
    assert evaluate_r1(ctx_ok, t_ok).state is EvaluationState.MET
    high = Infusion(
        bed=99, encounter="SYN", drug="norepinephrine", dose=Decimal("10"),
        unit="mcg/min", start=dt(d=20, h=16, mi=0), end=dt(d=21, h=7, mi=0),
    )
    ctx_high, t_high = _met_context_with_infusion(high)
    r = evaluate_r1(ctx_high, t_high)
    assert r.state is EvaluationState.NOT_MET
    assert "mcg/min" in r.detail


# ==========================================================================
# Review fix 2 (FIX): a sedation *increase* ends a confirmation early, but a
# sedative start at a lower rate, a decrease, or a stop does not.
# (docs/EVIDENCE.md R1 confirmations: "... or sedation increases".)
# ==========================================================================


def _sedative(drug: str, dose: str, start: datetime, end: datetime) -> Infusion:
    return Infusion(
        bed=99, encounter="SYN", drug=drug, dose=Decimal(dose),
        unit="mcg/kg/min", start=start, end=end,
    )


def test_unit_sedation_increase_ends_confirmation_early() -> None:
    # Propofol 20 running since 17:00; effort confirmed at 21:00 (valid to
    # 23:00). Propofol increases to 40 at 22:00 -> confirmation ends early, so
    # at 22:30 effort is no longer valid -> unknown/confirmation_expired.
    t = dt(d=20, h=22, mi=30)
    obs = _held_observations(dt(d=20, h=15, mi=0), t)
    base = _sedative("propofol", "20", dt(d=20, h=17, mi=0), dt(d=20, h=22, mi=0))
    higher = _sedative("propofol", "40", dt(d=20, h=22, mi=0), dt(d=21, h=7, mi=0))
    ctx = _synthetic_ctx(
        observations=obs, infusions=[base, higher],
        events=[_sat(dt(d=20, h=15, mi=0)), _check(dt(d=20, h=21, mi=0))],
    )
    r = evaluate_r1(ctx, t)
    assert r.state is EvaluationState.UNKNOWN
    assert r.reason is ReasonCode.CONFIRMATION_EXPIRED


def test_unit_sedation_decrease_does_not_end_confirmation() -> None:
    # Same shape but propofol *decreases* 40 -> 20 at 22:00. A decrease must not
    # end the confirmation; with a valid confirmation the screen reaches met.
    t = dt(d=20, h=23, mi=0)
    obs = _held_observations(dt(d=20, h=15, mi=0), t)
    base = _sedative("propofol", "40", dt(d=20, h=17, mi=0), dt(d=20, h=22, mi=0))
    lower = _sedative("propofol", "20", dt(d=20, h=22, mi=0), dt(d=21, h=7, mi=0))
    ctx = _synthetic_ctx(
        observations=obs, infusions=[base, lower],
        events=[_sat(dt(d=20, h=15, mi=0))]
        + _checks_every_2h(dt(d=20, h=15, mi=0), t),
    )
    assert evaluate_r1(ctx, t).state is EvaluationState.MET


def test_unit_sedation_new_start_from_zero_is_increase() -> None:
    # No sedative running before 22:00; a propofol *start* at 22:00 is an
    # increase from zero and ends the 21:00 confirmation early.
    t = dt(d=20, h=22, mi=30)
    obs = _held_observations(dt(d=20, h=15, mi=0), t)
    started = _sedative("propofol", "20", dt(d=20, h=22, mi=0), dt(d=21, h=7, mi=0))
    ctx = _synthetic_ctx(
        observations=obs, infusions=[started],
        events=[_sat(dt(d=20, h=15, mi=0)), _check(dt(d=20, h=21, mi=0))],
    )
    r = evaluate_r1(ctx, t)
    assert r.state is EvaluationState.UNKNOWN
    assert r.reason is ReasonCode.CONFIRMATION_EXPIRED


def test_unit_sedation_stop_does_not_end_confirmation() -> None:
    # Propofol 20 running since 17:00 *stops* at 22:00 (no later row). A stop is
    # not an increase, so the 21:00-anchored confirmation remains valid and the
    # screen reaches met at 23:00.
    t = dt(d=20, h=23, mi=0)
    obs = _held_observations(dt(d=20, h=15, mi=0), t)
    base = _sedative("propofol", "20", dt(d=20, h=17, mi=0), dt(d=20, h=22, mi=0))
    ctx = _synthetic_ctx(
        observations=obs, infusions=[base],
        events=[_sat(dt(d=20, h=15, mi=0))]
        + _checks_every_2h(dt(d=20, h=15, mi=0), t),
    )
    assert evaluate_r1(ctx, t).state is EvaluationState.MET


# ==========================================================================
# Review fix 3 (NIT): the pH < 7.30 context gate is reachable end to end
# through the public evaluator via R1Context.ph.
# ==========================================================================


def test_unit_r1f_low_ph_gate_not_met_via_public_evaluator() -> None:
    t = dt(d=20, h=23, mi=0)
    obs = _held_observations(dt(d=20, h=19, mi=0), t)
    ctx = _synthetic_ctx(
        observations=obs, ph=Decimal("7.29"),
        events=[_sat(dt(d=20, h=19, mi=0))]
        + _checks_every_2h(dt(d=20, h=19, mi=0), t),
    )
    r = evaluate_r1(ctx, t)
    assert r.state is EvaluationState.NOT_MET
    assert r.reason is ReasonCode.CONTEXT_REVIEW
    assert "pH" in r.detail


def test_unit_r1f_ph_at_7_30_does_not_block_via_public_evaluator() -> None:
    # pH exactly 7.30 is acceptable (>= 7.30), so the screen still reaches met.
    t = dt(d=20, h=23, mi=0)
    obs = _held_observations(dt(d=20, h=19, mi=0), t)
    ctx = _synthetic_ctx(
        observations=obs, ph=Decimal("7.30"),
        events=[_sat(dt(d=20, h=19, mi=0))]
        + _checks_every_2h(dt(d=20, h=19, mi=0), t),
    )
    assert evaluate_r1(ctx, t).state is EvaluationState.MET
