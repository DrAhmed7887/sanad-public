"""R2a tests: the oxygenation-trend scenario oracle (``data/SCENARIOS.md``).

Asserts the engine's R2a output against the per-bed expectations in the frozen
oracle, on the 5-minute grid:

* bed 4  -- ``met`` from 02:20 (SpO2 branch; SpO2 -3 from 02:15, sustained
  5 min); the settings branch alone would fire at 02:50; ``not_met`` before;
* bed 6  -- ``met`` from 01:05 (SpO2 branch);
* bed 7  -- ``not_met`` all night (poor-quality 74% artefact ignored);
* bed 8  -- ``not_met`` all night (FiO2 1.0 spike is inside a tagged
  pre-oxygenation window);
* bed 11 -- ``not_applicable`` (VV-ECMO);
* bed 16 -- ``met`` at 03:05 during tagged suctioning (the SpO2 branch is never
  suppressed by a tag), ``not_met`` from 03:10 when SpO2 recovers.

Reads the fixed dataset read-only (safety steering); never writes.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from sanad.model import Dataset
from sanad.r2a import (
    FLUID_UNKNOWN_LABEL,
    SETTINGS_BRANCH,
    SPO2_BRANCH,
    context_for,
    evaluate_r2a,
)
from sanad.states import EvaluationState, ReasonCode
from sanad.timeline import grid

TZ = timezone(timedelta(hours=1))


def dt(d=20, h=19, mi=0) -> datetime:
    return datetime(2026, 11, d, h, mi, tzinfo=TZ)


@pytest.fixture(scope="module")
def ds() -> Dataset:
    from sanad.loader import load_dataset

    return load_dataset()


def _night_grid() -> list[datetime]:
    # The board window 19:00 (20 Nov) .. 07:00 (21 Nov), inclusive.
    return grid(dt(d=20, h=19), dt(d=21, h=7))


# ==========================================================================
# Bed 4: met from 02:20 (SpO2 branch); settings branch alone fires 02:50.
# ==========================================================================


def test_bed4_spo2_branch_met_from_0220(ds: Dataset) -> None:
    ctx = context_for(ds, "E04-1120")
    # Not yet met one step before (the 02:15 drop has only just started).
    assert evaluate_r2a(ctx, dt(d=21, h=2, mi=15)).state is EvaluationState.NOT_MET
    # Met at 02:20: SpO2 is >= 3 below the 6-h median, sustained 5 min.
    r = evaluate_r2a(ctx, dt(d=21, h=2, mi=20))
    assert r.state is EvaluationState.MET
    assert SPO2_BRANCH in r.detail
    # Fires regardless of fluid balance (fluid-independent, PBT-5). R2a's own
    # detail no longer carries the "fluid balance unknown" label -- that label
    # is a cross-rule display step added by the orchestrator only when R2b is
    # unknown (D29); R2a alone never adds it.
    assert FLUID_UNKNOWN_LABEL not in r.detail
    # Stays met for the rest of the night (FiO2/PEEP keep climbing).
    for t in grid(dt(d=21, h=2, mi=20), dt(d=21, h=7)):
        assert evaluate_r2a(ctx, t).state is EvaluationState.MET


def test_bed4_settings_branch_alone_fires_0250(ds: Dataset) -> None:
    # The settings branch (FiO2/PEEP sustained >= their 6-h minimum + rise for
    # 30 min) would first hold at 02:50: the elevation begins at 02:20.
    ctx = context_for(ds, "E04-1120")
    from sanad.r2a import _settings_branch_met

    assert _settings_branch_met(ctx, dt(d=21, h=2, mi=45)) is False
    assert _settings_branch_met(ctx, dt(d=21, h=2, mi=50)) is True
    # At 02:50 the met detail names both branches (SpO2 still low too).
    r = evaluate_r2a(ctx, dt(d=21, h=2, mi=50))
    assert r.state is EvaluationState.MET
    assert SETTINGS_BRANCH in r.detail


def test_bed4_not_met_before_the_drop(ds: Dataset) -> None:
    ctx = context_for(ds, "E04-1120")
    for t in grid(dt(d=20, h=19), dt(d=21, h=2, mi=15)):
        assert evaluate_r2a(ctx, t).state is EvaluationState.NOT_MET


# ==========================================================================
# Bed 6: met from 01:05 (SpO2 branch).
# ==========================================================================


def test_bed6_spo2_branch_met_from_0105(ds: Dataset) -> None:
    ctx = context_for(ds, "E06-1120")
    # SpO2 drops 96 -> 93 at 01:00; not yet sustained 5 min.
    assert evaluate_r2a(ctx, dt(d=21, h=1, mi=0)).state is EvaluationState.NOT_MET
    r = evaluate_r2a(ctx, dt(d=21, h=1, mi=5))
    assert r.state is EvaluationState.MET
    assert SPO2_BRANCH in r.detail


def test_bed6_not_met_before_the_drop(ds: Dataset) -> None:
    ctx = context_for(ds, "E06-1120")
    for t in grid(dt(d=20, h=19), dt(d=21, h=0, mi=55)):
        assert evaluate_r2a(ctx, t).state is EvaluationState.NOT_MET


# ==========================================================================
# Bed 7: not_met all night (poor-quality artefact ignored).
# ==========================================================================


def test_bed7_not_met_artefact_ignored(ds: Dataset) -> None:
    ctx = context_for(ds, "E07-1120")
    for t in _night_grid():
        r = evaluate_r2a(ctx, t)
        assert r.state is EvaluationState.NOT_MET


# ==========================================================================
# Bed 8: not_met all night (FiO2 1.0 inside a tagged pre-oxygenation window).
# ==========================================================================


def test_bed8_not_met_tagged_preoxygenation(ds: Dataset) -> None:
    ctx = context_for(ds, "E08-1120")
    for t in _night_grid():
        r = evaluate_r2a(ctx, t)
        assert r.state is EvaluationState.NOT_MET
    # And specifically around the tagged spike at 04:00-04:05.
    for t in grid(dt(d=21, h=3, mi=55), dt(d=21, h=4, mi=30)):
        assert evaluate_r2a(ctx, t).state is EvaluationState.NOT_MET


# ==========================================================================
# Bed 11: not_applicable (VV-ECMO).
# ==========================================================================


def test_bed11_not_applicable_ecmo(ds: Dataset) -> None:
    ctx = context_for(ds, "E11-1120")
    for t in _night_grid():
        r = evaluate_r2a(ctx, t)
        assert r.state is EvaluationState.NOT_APPLICABLE
        assert r.reason is ReasonCode.ECMO


# ==========================================================================
# Bed 16: met at 03:05 during tagged suctioning; not_met from 03:10.
# ==========================================================================


def test_bed16_spo2_branch_met_during_tag_at_0305(ds: Dataset) -> None:
    ctx = context_for(ds, "E16-1120")
    # SpO2 96 -> 82 at 03:00 and 03:05 (good quality), inside tag 03:00-03:10.
    # The drop has not yet lasted 5 min at 03:00.
    assert evaluate_r2a(ctx, dt(d=21, h=3, mi=0)).state is EvaluationState.NOT_MET
    # Met at 03:05 -- a tag never suppresses the SpO2 branch.
    r = evaluate_r2a(ctx, dt(d=21, h=3, mi=5))
    assert r.state is EvaluationState.MET
    assert SPO2_BRANCH in r.detail
    # Not_met from 03:10 when SpO2 recovers to 96.
    assert evaluate_r2a(ctx, dt(d=21, h=3, mi=10)).state is EvaluationState.NOT_MET


def test_bed16_not_met_outside_the_desaturation(ds: Dataset) -> None:
    ctx = context_for(ds, "E16-1120")
    for t in grid(dt(d=20, h=19), dt(d=21, h=2, mi=55)):
        assert evaluate_r2a(ctx, t).state is EvaluationState.NOT_MET
    for t in grid(dt(d=21, h=3, mi=10), dt(d=21, h=7)):
        assert evaluate_r2a(ctx, t).state is EvaluationState.NOT_MET


# ==========================================================================
# Synthetic-context unit tests for the safety gates (AC-R2a-hist, AC-DEF-5),
# the spo2_target display (AC-R2a-spo2), and the "no usable data -> unknown"
# guard against silent false reassurance (safety steering; PBT-1).
#
# These use hand-built R2aContext objects so the exact gate boundaries can be
# asserted directly, without depending on any frozen-oracle bed timing.
# ==========================================================================

from decimal import Decimal

from sanad.model import Observation
from sanad.r2a import R2aContext


def _obs(
    t: datetime,
    *,
    fio2: str = "0.40",
    peep: int = 5,
    spo2: int = 96,
    quality: str = "good",
) -> Observation:
    """A minimal good-quality synthetic 5-minute sample at ``t``."""

    f = Decimal(fio2)
    return Observation(
        bed=99,
        encounter="SYN",
        t=t,
        fio2=f,
        fio2_unit="fraction",
        fio2_fraction=f,
        peep=peep,
        peep_unit="cmH2O",
        spo2=spo2,
        spo2_quality=quality,
        rr=16,
        sbp=120,
        hr=80,
        spont_effort_flag=True,
    )


def _syn_ctx(
    observations: tuple[Observation, ...],
    *,
    pathways: tuple[str, ...] = (),
    spo2_target=None,
) -> R2aContext:
    return R2aContext(
        encounter="SYN",
        bed=99,
        pathways=pathways,
        observations=observations,
        events=(),
        spo2_target=spo2_target,
    )


def test_insufficient_history_until_first_obs_plus_6h() -> None:
    # First observation at 20:00; steady, fresh 5-minute samples thereafter.
    first = dt(d=20, h=20, mi=0)
    obs = tuple(
        _obs(first + timedelta(minutes=5 * i)) for i in range(0, 90)  # 20:00..~27:25
    )
    ctx = _syn_ctx(obs)

    # Just under 6 h of history -> unknown / insufficient_history.
    t_before = first + _six_h() - timedelta(minutes=5)
    r_before = evaluate_r2a(ctx, t_before)
    assert r_before.state is EvaluationState.UNKNOWN
    assert r_before.reason is ReasonCode.INSUFFICIENT_HISTORY

    # Exactly 6 h after the first observation -> the history gate is satisfied
    # (steady settings/SpO2 -> not_met, not unknown).
    t_at = first + _six_h()
    r_at = evaluate_r2a(ctx, t_at)
    assert r_at.state is EvaluationState.NOT_MET


def test_stale_data_when_newest_observation_over_15_min_old() -> None:
    # 6 h of fresh history, then the feed goes quiet: newest sample is 20 min
    # old at t -> unknown / stale_data (AC-DEF-5).
    first = dt(d=20, h=20, mi=0)
    obs = tuple(_obs(first + timedelta(minutes=5 * i)) for i in range(0, 73))
    last = obs[-1].event_time  # first + 6 h
    ctx = _syn_ctx(obs)

    t = last + timedelta(minutes=20)
    r = evaluate_r2a(ctx, t)
    assert r.state is EvaluationState.UNKNOWN
    assert r.reason is ReasonCode.STALE_DATA


def test_spo2_target_shown_in_met_detail() -> None:
    # Build a context that fires the SpO2 branch, with a documented target.
    first = dt(d=20, h=20, mi=0)
    # 6 h of steady good SpO2 at 96 (median 96), then a sustained drop to 92
    # (>= 3 below median) for >= 5 min.
    steady = [
        _obs(first + timedelta(minutes=5 * i), spo2=96) for i in range(0, 73)
    ]
    low = [
        _obs(first + _six_h() + timedelta(minutes=5 * i), spo2=92)
        for i in range(1, 3)  # +5 and +10 min
    ]
    ctx = _syn_ctx(tuple(steady + low), spo2_target=92)

    t = first + _six_h() + timedelta(minutes=10)
    r = evaluate_r2a(ctx, t)
    assert r.state is EvaluationState.MET
    assert SPO2_BRANCH in r.detail
    assert "SpO2 target 92%" in r.detail


def test_unknown_when_no_usable_oxygenation_data() -> None:
    # 6 h of history, all fresh, but every in-window SpO2 sample is poor
    # quality AND every settings sample sits inside a tagged planned-change
    # window -> no usable datum for either branch -> unknown (never a silent
    # not_met). This is the false-reassurance path the reviewer flagged.
    from sanad.model import Event

    first = dt(d=20, h=20, mi=0)
    obs = tuple(
        _obs(first + timedelta(minutes=5 * i), quality="poor")
        for i in range(0, 73)
    )
    last = obs[-1].event_time
    # A tag covering the whole span so no untagged settings sample exists.
    tag = Event(
        bed=99,
        encounter="SYN",
        type="planned_change",
        start=first - timedelta(minutes=5),
        end=last + timedelta(minutes=5),
        documented_at=first - timedelta(minutes=5),
        reason="proning",
    )
    ctx = R2aContext(
        encounter="SYN",
        bed=99,
        pathways=(),
        observations=obs,
        events=(tag,),
        spo2_target=None,
    )

    t = last  # fresh (newest sample is exactly at t)
    r = evaluate_r2a(ctx, t)
    assert r.state is EvaluationState.UNKNOWN
    assert r.reason is ReasonCode.MISSING_ITEM


def test_not_met_when_one_branch_still_evaluable() -> None:
    # Same as above but SpO2 is good quality (just steady, no drop): the SpO2
    # branch is evaluable and shows no desaturation -> not_met, not unknown.
    from sanad.model import Event

    first = dt(d=20, h=20, mi=0)
    obs = tuple(
        _obs(first + timedelta(minutes=5 * i), quality="good", spo2=96)
        for i in range(0, 73)
    )
    last = obs[-1].event_time
    tag = Event(
        bed=99,
        encounter="SYN",
        type="planned_change",
        start=first - timedelta(minutes=5),
        end=last + timedelta(minutes=5),
        documented_at=first - timedelta(minutes=5),
        reason="proning",
    )
    ctx = R2aContext(
        encounter="SYN",
        bed=99,
        pathways=(),
        observations=obs,
        events=(tag,),
        spo2_target=None,
    )

    r = evaluate_r2a(ctx, last)
    assert r.state is EvaluationState.NOT_MET


def _six_h() -> timedelta:
    return timedelta(hours=6)
