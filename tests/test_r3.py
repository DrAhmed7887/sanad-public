"""R3 tests: the task-and-response-tracker scenario oracle (``data/SCENARIOS.md``).

Asserts the engine's R3 output against the per-bed expectations in the frozen
oracle, on the 5-minute grid:

* bed 10 -- the missed-check scenario. Checks on cadence to 23:00; the 01:00
  check is missing; an acknowledgement at 01:12; a valid check performed 01:50
  (documented 01:52). Expected: ``met`` (overdue) 01:10-01:50, the
  acknowledgement leaves it ``met`` and the episode open, then ``not_met`` from
  01:55 once the 01:50 check becomes known (workflow ``resolved``).
* bed 13 -- the reassignment. Encounter A leaves at 23:00 after a check at
  22:50; encounter B arrives 23:15 with checks at 23:40, 01:35, ... Expected:
  R3 is **never** ``met`` for A or B -- neither inherits the other's history in
  either direction (AC-R3-encounter, PBT-8).

Plus synthetic-context unit tests for the pieces the frozen beds do not pin
down directly: an invalid check (a missing field) neither satisfies nor resets
the task (AC-R3-valid); the first check is due admission + 30 min (AC-R3-due);
and a feed/scheduler/routing failure is shown as its own visible alert, never
as silence (AC-R3-failure, invariant 9).

Reads the fixed dataset read-only (safety steering); never writes.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from sanad.model import Dataset, Event, Observation
from sanad.r3 import (
    FIRST_CHECK_DELAY,
    GRACE,
    R3Context,
    context_for,
    evaluate_r3,
    workflow_state_at,
)
from sanad.states import (
    EvaluationState,
    R3_OVERDUE_TEXT,
    ReasonCode,
    WorkflowState,
)
from sanad.timeline import grid

TZ = timezone(timedelta(hours=1))


def dt(d=20, h=19, mi=0) -> datetime:
    return datetime(2026, 11, d, h, mi, tzinfo=TZ)


@pytest.fixture(scope="module")
def ds() -> Dataset:
    from sanad.loader import load_dataset

    return load_dataset()


def _night_grid() -> list[datetime]:
    return grid(dt(d=20, h=19), dt(d=21, h=7))


# ==========================================================================
# Bed 10: met (overdue) 01:10-01:50; acknowledge keeps it met; not_met from
# 01:55 (workflow resolved).
# ==========================================================================


def test_bed10_not_met_before_overdue(ds: Dataset) -> None:
    ctx = context_for(ds, "E10-1120")
    # Regular 2-hourly cadence through the evening: never overdue before 01:10.
    for t in grid(dt(d=20, h=19), dt(d=21, h=1, mi=5)):
        r = evaluate_r3(ctx, t)
        assert r.state is EvaluationState.NOT_MET, t.isoformat()


def test_bed10_met_overdue_0110_to_0150(ds: Dataset) -> None:
    ctx = context_for(ds, "E10-1120")
    # Due = last valid check (23:00) + 2 h = 01:00; overdue at due + 10 min
    # grace = 01:10 (inclusive). The 01:50 check is documented 01:52, so it is
    # invisible on the 01:50 grid point: the episode is still met at 01:50.
    for t in grid(dt(d=21, h=1, mi=10), dt(d=21, h=1, mi=50)):
        r = evaluate_r3(ctx, t)
        assert r.state is EvaluationState.MET, t.isoformat()
        assert r.message == R3_OVERDUE_TEXT


def test_bed10_overdue_boundary_is_inclusive_at_0110(ds: Dataset) -> None:
    ctx = context_for(ds, "E10-1120")
    # 01:05 not yet overdue (due + grace = 01:10); 01:10 overdue (inclusive).
    assert evaluate_r3(ctx, dt(d=21, h=1, mi=5)).state is EvaluationState.NOT_MET
    assert evaluate_r3(ctx, dt(d=21, h=1, mi=10)).state is EvaluationState.MET


def test_bed10_acknowledge_leaves_it_met_and_open(ds: Dataset) -> None:
    ctx = context_for(ds, "E10-1120")
    # Acknowledgement at 01:12: at 01:15 the episode is still met and now shows
    # the acknowledged-open workflow state (AC-DEF-2: acknowledging never closes
    # the episode nor changes the evaluation state).
    t = dt(d=21, h=1, mi=15)
    r = evaluate_r3(ctx, t)
    assert r.state is EvaluationState.MET
    assert workflow_state_at(ctx, t) is WorkflowState.ACKNOWLEDGED


def test_bed10_not_met_from_0155_resolved(ds: Dataset) -> None:
    ctx = context_for(ds, "E10-1120")
    # From 01:55 the 01:50 check (documented 01:52) is known: it moves the due
    # time forward, so the episode is no longer overdue -> not_met, workflow
    # resolved.
    for t in grid(dt(d=21, h=1, mi=55), dt(d=21, h=7)):
        r = evaluate_r3(ctx, t)
        assert r.state is EvaluationState.NOT_MET, t.isoformat()
    assert workflow_state_at(ctx, dt(d=21, h=1, mi=55)) is WorkflowState.RESOLVED


def test_bed10_never_met_outside_the_overdue_window(ds: Dataset) -> None:
    ctx = context_for(ds, "E10-1120")
    overdue = {
        t
        for t in grid(dt(d=21, h=1, mi=10), dt(d=21, h=1, mi=50))
    }
    for t in _night_grid():
        r = evaluate_r3(ctx, t)
        if t in overdue:
            assert r.state is EvaluationState.MET, t.isoformat()
        else:
            assert r.state is EvaluationState.NOT_MET, t.isoformat()


# ==========================================================================
# Bed 13: R3 never met for A or B (no inheritance across the reassignment).
# ==========================================================================


def test_bed13a_never_met(ds: Dataset) -> None:
    ctx = context_for(ds, "E13A-1120")
    # A is active 19:00-23:00 (discharged 23:00). On cadence throughout; it is
    # never overdue, and from 23:00 it is not_applicable (discharged). B's later
    # checks in the same bed must never make A's task appear met.
    for t in _night_grid():
        r = evaluate_r3(ctx, t)
        assert r.state is not EvaluationState.MET, t.isoformat()


def test_bed13a_not_applicable_after_discharge(ds: Dataset) -> None:
    ctx = context_for(ds, "E13A-1120")
    for t in grid(dt(d=20, h=23), dt(d=21, h=7)):
        r = evaluate_r3(ctx, t)
        assert r.state is EvaluationState.NOT_APPLICABLE, t.isoformat()


def test_bed13b_never_met(ds: Dataset) -> None:
    ctx = context_for(ds, "E13B-1120")
    # B admitted 23:15; first check due 23:45 (admission + 30 min), grace to
    # 23:55. The 23:40 check (documented 23:44) is known before 23:55, so B is
    # never overdue; and before admission B is not_applicable (A's history is
    # never inherited).
    for t in _night_grid():
        r = evaluate_r3(ctx, t)
        assert r.state is not EvaluationState.MET, t.isoformat()


def test_bed13b_not_applicable_before_admission(ds: Dataset) -> None:
    ctx = context_for(ds, "E13B-1120")
    # Before the 23:15 admission B has no task (A's checks are not inherited).
    for t in grid(dt(d=20, h=19), dt(d=20, h=23, mi=10)):
        r = evaluate_r3(ctx, t)
        assert r.state is EvaluationState.NOT_APPLICABLE, t.isoformat()


def test_bed13b_first_due_is_admission_plus_30_min(ds: Dataset) -> None:
    ctx = context_for(ds, "E13B-1120")
    # Immediately after admission (23:20), before the 23:40 check is known, the
    # due reference is admission (23:15) + 30 min = 23:45 -> not yet overdue.
    r = evaluate_r3(ctx, dt(d=20, h=23, mi=20))
    assert r.state is EvaluationState.NOT_MET
    assert "23:45" in r.detail  # next check due admission + 30 min


# ==========================================================================
# Synthetic-context unit tests for AC-R3-valid, AC-R3-due, AC-R3-failure.
# ==========================================================================


def _check(
    performed: datetime,
    *,
    effort: str | None = "adequate",
    haemodynamics: str | None = "acceptable",
    cuff: int | None = 25,
    documented: datetime | None = None,
) -> Event:
    return Event(
        bed=99, encounter="SYN", type="vent_check",
        performed_at=performed,
        documented_at=documented or (performed + timedelta(minutes=4)),
        effort=effort, haemodynamics=haemodynamics, cuff_pressure_cmH2O=cuff,
    )


def _ctx(events: list[Event], obs: tuple[Observation, ...] = ()) -> R3Context:
    return R3Context(encounter="SYN", bed=99, events=tuple(events), observations=obs)


def test_valid_check_requires_all_three_fields() -> None:
    # Admission at 10:00 -> first check due 10:30, overdue at 10:40.
    adm = Event(bed=99, encounter="SYN", type="admission", t=dt(d=20, h=10))

    # An "invalid" check at 10:15 missing the cuff pressure does NOT reset the
    # task: by 10:45 the encounter is still overdue (first-check due basis).
    invalid = _check(dt(d=20, h=10, mi=15), cuff=None)
    ctx_invalid = _ctx([adm, invalid])
    assert evaluate_r3(ctx_invalid, dt(d=20, h=10, mi=45)).state is EvaluationState.MET

    # A valid check at the same time DOES reset it: not overdue at 10:45.
    valid = _check(dt(d=20, h=10, mi=15))
    ctx_valid = _ctx([adm, valid])
    # Known from 10:19 (documented +4 min); due becomes 12:15 -> not overdue.
    assert evaluate_r3(ctx_valid, dt(d=20, h=10, mi=45)).state is EvaluationState.NOT_MET


def test_first_check_due_30_min_after_admission() -> None:
    adm = Event(bed=99, encounter="SYN", type="admission", t=dt(d=20, h=10))
    ctx = _ctx([adm])

    # Due = admission + 30 min = 10:30; overdue at 10:30 + 10 min grace = 10:40.
    assert evaluate_r3(ctx, dt(d=20, h=10, mi=35)).state is EvaluationState.NOT_MET
    assert evaluate_r3(ctx, dt(d=20, h=10, mi=40)).state is EvaluationState.MET
    # The overdue instant is exactly admission + FIRST_CHECK_DELAY + GRACE.
    assert dt(d=20, h=10) + FIRST_CHECK_DELAY + GRACE == dt(d=20, h=10, mi=40)


def test_feed_failure_is_shown_as_its_own_alert_never_silent() -> None:
    # A feed_status "down" window over t: R3 must surface it as a visible alert
    # in its detail, whatever the task state (never silence) -- AC-R3-failure.
    adm = Event(bed=99, encounter="SYN", type="admission", t=dt(d=20, h=10))
    feed = Event(
        bed=99, encounter="SYN", type="feed_status", status="down",
        start=dt(d=20, h=10, mi=20), end=dt(d=20, h=10, mi=50),
    )
    ctx = _ctx([adm, feed])
    # At 10:25 the check is not yet overdue, but the feed failure must be shown.
    r = evaluate_r3(ctx, dt(d=20, h=10, mi=25))
    assert "feed" in r.detail.lower()
    # And while overdue the alert is still shown alongside the met state.
    r2 = evaluate_r3(ctx, dt(d=20, h=10, mi=45))
    assert r2.state is EvaluationState.MET
    assert "feed" in r2.detail.lower()


def test_documented_deferral_suppresses_and_ends_episode() -> None:
    # An overdue episode ended by a documented deferral (reason, owner, expiry)
    # -> suppressed, with the hold and its review time shown (AC-R3-workflow).
    adm = Event(bed=99, encounter="SYN", type="admission", t=dt(d=20, h=10))
    deferral = Event(
        bed=99, encounter="SYN", type="deferral", rule="R3",
        t=dt(d=20, h=10, mi=42), until=dt(d=20, h=12), owner="RN-charge",
        reason="staffing",
    )
    ctx = _ctx([adm, deferral])
    # Before the deferral is documented: overdue (met) at 10:40.
    assert evaluate_r3(ctx, dt(d=20, h=10, mi=40)).state is EvaluationState.MET
    # After it is documented: suppressed, showing the until time.
    r = evaluate_r3(ctx, dt(d=20, h=10, mi=45))
    assert r.state is EvaluationState.SUPPRESSED
    assert r.reason is ReasonCode.HELD_DEFERRED
    assert "12:00" in r.detail
    assert workflow_state_at(ctx, dt(d=20, h=10, mi=45)) is WorkflowState.DEFERRED


def test_no_reference_before_admission_is_not_met_not_a_crash() -> None:
    # An encounter with an admission event but evaluated before it: not yet
    # admitted -> not_applicable (A's history never inherited).
    adm = Event(bed=99, encounter="SYN", type="admission", t=dt(d=20, h=10))
    ctx = _ctx([adm])
    assert evaluate_r3(ctx, dt(d=20, h=9)).state is EvaluationState.NOT_APPLICABLE
