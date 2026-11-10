"""R2b tests: the fluid-accounting scenario oracle (``data/SCENARIOS.md``).

Asserts the engine's R2b output against the per-bed expectations in the frozen
oracle, on the 5-minute grid:

* bed 4  -- ``not_met`` all night (+0.3 L; well under the +2 L threshold);
* bed 5  -- ``met`` all night (+3.2 L known since 20 Nov 08:00; two duplicate
  transaction IDs must not change the net);
* bed 6  -- ``not_met`` until 01:55, ``met`` from 02:00 (a 1.0 L intake given
  at 20:00 but documented 02:00 is invisible until 02:00, then tips the 72-h
  net over +2 L -- as known at t);
* bed 11 -- ``not_met`` (VV-ECMO; R2b *applies* to ECMO, so it is evaluated,
  not ``not_applicable``);
* bed 13A -- ``met`` 19:00-23:00 (+2.4 L) before the bed is reassigned;
* bed 17 -- ``unknown`` / ``output_not_charted`` all night (no urine charted
  after 20 Nov 10:00); the computed net is still shown, +4.25 L at 19:00
  falling to +2.5 L once the 04:00 ``crrt_net`` entry is known, with the gross
  CRRT effluent/replacement volumes ignored.

Also two synthetic-context unit tests for the >= 6 h history gate
(AC-R2b-hist) and the "missing output is never zero" coverage path
(AC-R2b-coverage), so the exact gate boundaries can be asserted without
depending on a frozen-oracle bed timing.

Reads the fixed dataset read-only (safety steering); never writes.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from sanad.model import Dataset
from sanad.r2b import (
    THRESHOLD_ML,
    context_for,
    evaluate_r2b,
    rolling_net_ml,
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
# Bed 4: not_met all night (+0.3 L).
# ==========================================================================


def test_bed4_not_met_small_positive(ds: Dataset) -> None:
    ctx = context_for(ds, "E04-1120")
    for t in _night_grid():
        r = evaluate_r2b(ctx, t)
        assert r.state is EvaluationState.NOT_MET
    # The 300 ml daily extra is the only unmatched intake -> net +300 ml.
    assert rolling_net_ml(ctx, dt(d=20, h=19)) == 300


# ==========================================================================
# Bed 5: met all night; duplicate transaction IDs do not change the net.
# ==========================================================================


def test_bed5_met_all_night(ds: Dataset) -> None:
    ctx = context_for(ds, "E05-1120")
    for t in _night_grid():
        r = evaluate_r2b(ctx, t)
        assert r.state is EvaluationState.MET


def test_bed5_duplicate_tx_ids_do_not_change_net(ds: Dataset) -> None:
    ctx = context_for(ds, "E05-1120")
    # The +3.2 L daily intake (F05-0059) is the only unmatched intake; the two
    # duplicate rows (F05-0003, F05-0007) are deduplicated by tx_id, so the net
    # is exactly +3200 ml, not inflated by the repeats.
    assert rolling_net_ml(ctx, dt(d=20, h=19)) == 3200
    assert rolling_net_ml(ctx, dt(d=20, h=19)) > THRESHOLD_ML


# ==========================================================================
# Bed 6: not_met until 01:55, met from 02:00 (as known at t).
# ==========================================================================


def test_bed6_not_met_until_0155(ds: Dataset) -> None:
    ctx = context_for(ds, "E06-1120")
    for t in grid(dt(d=20, h=19), dt(d=21, h=1, mi=55)):
        r = evaluate_r2b(ctx, t)
        assert r.state is EvaluationState.NOT_MET
    # Known net before the late 1.0 L becomes visible: +1.6 L (<= +2 L).
    assert rolling_net_ml(ctx, dt(d=21, h=1, mi=55)) == 1600


def test_bed6_met_from_0200(ds: Dataset) -> None:
    ctx = context_for(ds, "E06-1120")
    # At 02:00 the 1.0 L intake given at 20:00 but documented 02:00 becomes
    # visible and is placed at its 20:00 event time -> net +2.6 L (> +2 L).
    assert rolling_net_ml(ctx, dt(d=21, h=2, mi=0)) == 2600
    for t in grid(dt(d=21, h=2, mi=0), dt(d=21, h=7)):
        r = evaluate_r2b(ctx, t)
        assert r.state is EvaluationState.MET


# ==========================================================================
# Bed 11: not_met (VV-ECMO) -- R2b applies to ECMO, never not_applicable.
# ==========================================================================


def test_bed11_not_met_applies_to_ecmo(ds: Dataset) -> None:
    ctx = context_for(ds, "E11-1120")
    for t in _night_grid():
        r = evaluate_r2b(ctx, t)
        assert r.state is EvaluationState.NOT_MET
        assert r.state is not EvaluationState.NOT_APPLICABLE
    # +1.0 L -- evaluated, under threshold.
    assert rolling_net_ml(ctx, dt(d=20, h=19)) == 1000


# ==========================================================================
# Bed 13A: met 19:00-23:00 (+2.4 L) before the bed is reassigned at 23:00.
# ==========================================================================


def test_bed13a_met_through_2300(ds: Dataset) -> None:
    ctx = context_for(ds, "E13A-1120")
    # A is active 19:00-23:00; R2b is met across that window (+2.4 L).
    for t in grid(dt(d=20, h=19), dt(d=20, h=23)):
        r = evaluate_r2b(ctx, t)
        assert r.state is EvaluationState.MET
    assert rolling_net_ml(ctx, dt(d=20, h=19)) == 2400


# ==========================================================================
# Bed 17: output_not_charted all night; computed net shown, +4.25 L -> +2.5 L;
# gross CRRT effluent/replacement ignored.
# ==========================================================================


def test_bed17_output_not_charted_all_night(ds: Dataset) -> None:
    ctx = context_for(ds, "E17-1120")
    for t in _night_grid():
        r = evaluate_r2b(ctx, t)
        assert r.state is EvaluationState.UNKNOWN
        assert r.reason is ReasonCode.OUTPUT_NOT_CHARTED
        # The computed net is still shown in the detail (never silent).
        assert "L" in r.detail and "72 h" in r.detail


def test_bed17_net_425L_at_1900_and_only_crrt_net_counted(ds: Dataset) -> None:
    ctx = context_for(ds, "E17-1120")
    # +6.0 L charted intake (500 + 5500) minus two known crrt_net removals of
    # 875 ml (10:00, 16:00) = +4.25 L. The 18 L gross effluent/replacement
    # volumes are ignored entirely.
    assert rolling_net_ml(ctx, dt(d=20, h=19)) == 4250


def test_bed17_net_falls_to_25L_once_0400_crrt_known(ds: Dataset) -> None:
    ctx = context_for(ds, "E17-1120")
    # By 04:00 (21 Nov) all four crrt_net removals (10:00, 16:00, 22:00, 04:00)
    # are known -> +6.0 L - 4 x 0.875 L = +2.5 L. Gross CRRT still ignored.
    assert rolling_net_ml(ctx, dt(d=21, h=4, mi=0)) == 2500


# ==========================================================================
# Synthetic-context unit tests for the safety gates (AC-R2b-hist,
# AC-R2b-coverage). Hand-built contexts so the exact gate boundaries can be
# asserted directly, without depending on any frozen-oracle bed timing.
# ==========================================================================

from decimal import Decimal

from sanad.model import FluidTx, Observation
from sanad.r2b import HISTORY, R2bContext


def _obs(t: datetime) -> Observation:
    """A minimal synthetic 5-minute observation at ``t`` (values unused by R2b)."""

    return Observation(
        bed=99, encounter="SYN", t=t,
        fio2=Decimal("0.40"), fio2_unit="fraction", fio2_fraction=Decimal("0.40"),
        peep=5, peep_unit="cmH2O", spo2=96, spo2_quality="good",
        rr=16, sbp=120, hr=80, spont_effort_flag=True,
    )


def _fluid(
    tx_id: str, kind: str, ml: int, event: datetime, *, source: str = "iv",
    documented: datetime | None = None,
) -> FluidTx:
    return FluidTx(
        bed=99, encounter="SYN", tx_id=tx_id, kind=kind, ml=ml, source=source,
        event_time=event, documented_time=documented or event,
    )


def _six_h() -> timedelta:
    return HISTORY


def test_insufficient_history_until_first_obs_plus_6h() -> None:
    # First observation at 20:00; steady samples every 5 min thereafter.
    first = dt(d=20, h=20, mi=0)
    obs = tuple(_obs(first + timedelta(minutes=5 * i)) for i in range(0, 120))
    # A large intake and a recent urine output so the only gate that could fire
    # is the history gate.
    fluids = (
        _fluid("A", "in", 5000, first),
        _fluid("U", "out", 100, first + timedelta(hours=5, minutes=55),
               source="urine"),
    )
    ctx = R2bContext(
        encounter="SYN", bed=99, anuric=False, fluids=fluids, observations=obs,
    )

    # Just under 6 h of history -> unknown / insufficient_history.
    t_before = first + _six_h() - timedelta(minutes=5)
    r_before = evaluate_r2b(ctx, t_before)
    assert r_before.state is EvaluationState.UNKNOWN
    assert r_before.reason is ReasonCode.INSUFFICIENT_HISTORY

    # Exactly 6 h after the first observation -> the history gate is satisfied;
    # with a recent urine output and +5 L net, R2b is now met.
    t_at = first + _six_h()
    r_at = evaluate_r2b(ctx, t_at)
    assert r_at.state is EvaluationState.MET


def test_coverage_missing_output_is_unknown_not_zero() -> None:
    # 6 h of history and a large positive intake, but no urine/drain output in
    # the previous 6 h and not anuric -> unknown / output_not_charted; the net
    # is still shown and missing output is never treated as zero.
    first = dt(d=20, h=12, mi=0)
    obs = tuple(_obs(first + timedelta(minutes=5 * i)) for i in range(0, 120))
    fluids = (
        _fluid("A", "in", 5000, first + timedelta(hours=6)),
        # The only output is older than 6 h at the probe time.
        _fluid("U", "out", 300, first, source="urine"),
    )
    ctx = R2bContext(
        encounter="SYN", bed=99, anuric=False, fluids=fluids, observations=obs,
    )

    t = first + timedelta(hours=6, minutes=30)  # > 6 h after the only urine
    r = evaluate_r2b(ctx, t)
    assert r.state is EvaluationState.UNKNOWN
    assert r.reason is ReasonCode.OUTPUT_NOT_CHARTED
    assert "72 h" in r.detail  # computed net still shown


def test_coverage_anuric_patient_is_not_unknown() -> None:
    # Same ledger but the patient is documented anuric: the absence of urine is
    # expected, so the coverage gate does not fire and the balance is used.
    first = dt(d=20, h=12, mi=0)
    obs = tuple(_obs(first + timedelta(minutes=5 * i)) for i in range(0, 120))
    fluids = (_fluid("A", "in", 5000, first + timedelta(hours=6)),)
    ctx = R2bContext(
        encounter="SYN", bed=99, anuric=True, fluids=fluids, observations=obs,
    )

    t = first + timedelta(hours=6, minutes=30)
    r = evaluate_r2b(ctx, t)
    assert r.state is EvaluationState.MET  # +5 L, coverage gate skipped (anuric)


def test_gross_crrt_sources_are_ignored_in_the_net() -> None:
    # A net 72-h balance built from IV intake, charted urine output, a crrt_net
    # removal, and large gross CRRT flows that must be ignored entirely.
    first = dt(d=20, h=12, mi=0)
    obs = tuple(_obs(first + timedelta(minutes=5 * i)) for i in range(0, 120))
    t = first + timedelta(hours=6)
    fluids = (
        _fluid("IV", "in", 3000, first + timedelta(hours=1)),
        _fluid("UR", "out", 200, t - timedelta(minutes=10), source="urine"),
        _fluid("NET", "out", 500, first + timedelta(hours=2), source="crrt_net"),
        _fluid("EFF", "out", 18000, first + timedelta(hours=2),
               source="crrt_effluent_gross"),
        _fluid("REP", "in", 18000, first + timedelta(hours=2),
               source="crrt_replacement_gross"),
    )
    ctx = R2bContext(
        encounter="SYN", bed=99, anuric=False, fluids=fluids, observations=obs,
    )
    # +3000 IV - 200 urine - 500 crrt_net = +2300 ml; the 18 L gross pair is
    # ignored (if it counted, the net would be wildly different).
    assert rolling_net_ml(ctx, t) == 2300
    assert evaluate_r2b(ctx, t).state is EvaluationState.MET
