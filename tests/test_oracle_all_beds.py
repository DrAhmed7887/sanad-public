"""End-to-end scenario oracle over the whole ward (``data/SCENARIOS.md``).

Task 8: drive the orchestrator (:func:`sanad.evaluate.evaluate_ward`) over the
entire night window (19:00 on 20 Nov -> 07:00 on 21 Nov, ``+01:00``) for **all
17 beds / 18 encounters** -- including bed 13's two encounters A and B -- and
assert every bed's expected outcomes and timings against the frozen oracle on
the shared 5-minute grid.

This is the integration counterpart to the per-rule oracle tests: those pin a
single rule's result; this one asserts that the *assembled* per-bed/per-time
cell -- all of R1, R2a, R2b, R3, the R2 combined message, the feed alert and
the silence text -- matches the oracle when the whole ward is evaluated in one
deterministic pass.

It also proves two build-wide properties required by the task:

* ``daily_totals.jsonl`` is **loaded but never used** by any rule
  (AC-R2b-no-dailytotals): the dataset carries daily totals, yet zeroing or
  corrupting them does not change a single cell of the ward evaluation.
* the full 5-minute grid is produced **deterministically**: re-running
  :func:`evaluate_ward` over the same dataset yields a byte-for-byte identical
  structure (``.kiro/steering/tech.md``).

Plus PBT-10 across all beds: at every grid point of every encounter, the
rendered display text is the single silence constant iff nothing is ``met`` and
never contains a banned word (safe / stable / clear / green).

Reads the fixed dataset read-only (safety steering); never writes to ``docs/``
or ``data/``.
"""

from __future__ import annotations

import dataclasses
from datetime import datetime, timedelta, timezone

import pytest

from sanad.evaluate import evaluate_ward, night_window
from sanad.loader import load_dataset
from sanad.model import Dataset
from sanad.states import (
    BANNED_SILENCE_WORDS,
    SILENCE_TEXT,
    EvaluationState,
    R1_MET_TEXT,
    R2_COMBINED_TEXT,
    R3_OVERDUE_TEXT,
)
from sanad.timeline import grid

TZ = timezone(timedelta(hours=1))

MET = EvaluationState.MET
NOT_MET = EvaluationState.NOT_MET
UNKNOWN = EvaluationState.UNKNOWN
SUPPRESSED = EvaluationState.SUPPRESSED
NOT_APPLICABLE = EvaluationState.NOT_APPLICABLE


def dt(d=20, h=19, mi=0) -> datetime:
    return datetime(2026, 11, d, h, mi, tzinfo=TZ)


@pytest.fixture(scope="module")
def ds(dataset) -> Dataset:
    return dataset


@pytest.fixture(scope="module")
def ward(ward_eval: dict) -> dict:
    """One full-ward evaluation over the night window, indexed by encounter
    (shared session evaluation, see tests/conftest.py)."""

    return ward_eval


def _by_time(cells) -> dict[datetime, object]:
    """Index an encounter's cell list by grid time for O(1) oracle lookups."""

    return {c.t: c for c in cells}


# ==========================================================================
# The ward evaluation covers all 18 encounters over the full night grid.
# ==========================================================================


def test_ward_covers_all_18_encounters(ds: Dataset, ward: dict) -> None:
    expected = {e.encounter for e in ds.encounters}
    assert set(ward) == expected
    assert len(ward) == 18  # 17 beds, bed 13 has A and B


def test_ward_each_encounter_on_the_full_night_grid(ds: Dataset, ward: dict) -> None:
    start, end = night_window(ds)
    expected_times = grid(start, end)
    # 19:00..07:00 inclusive on a 5-min grid: 12 h = 144 steps + 1 = 145 points.
    assert len(expected_times) == 145
    for enc, cells in ward.items():
        assert [c.t for c in cells] == expected_times, enc


def test_night_window_is_read_from_meta(ds: Dataset) -> None:
    start, end = night_window(ds)
    assert start == dt(d=20, h=19)
    assert end == dt(d=21, h=7)


# ==========================================================================
# Per-bed scenario oracle. Each case names the encounter and a predicate over
# its time-indexed cells; the predicate asserts the headline oracle facts.
# ==========================================================================


def _states(cell, rule: str) -> EvaluationState:
    return cell.results[rule].state


def _check_bed1(cells) -> None:
    # R1 met from 22:20 (clock from the 20:15 SAT); not_met just before; exactly
    # one prompt (the first grid point where R1 is met, which the per-rule test
    # pins; here we assert the met onset and persistence).
    by = _by_time(cells)
    assert _states(by[dt(d=20, h=22, mi=15)], "R1") is not MET
    assert _states(by[dt(d=20, h=22, mi=20)], "R1") is MET
    assert by[dt(d=20, h=22, mi=20)].results["R1"].message == R1_MET_TEXT
    # Still met at the end of the night (criteria hold; SAT within 12 h of
    # 20:15 until ~08:15, so the whole night is inside the window).
    assert _states(by[dt(d=21, h=7)], "R1") is MET


def _check_bed2(cells) -> None:
    # R1 unknown all night: no SAT recorded (sat_not_recorded).
    for c in cells:
        assert _states(c, "R1") is UNKNOWN


def _check_bed3(cells) -> None:
    # R1 unknown all night (sat_not_recorded before 19:30, haemo_unconfirmed
    # after); never met.
    for c in cells:
        assert _states(c, "R1") is UNKNOWN


def _check_bed4(cells) -> None:
    by = _by_time(cells)
    # R2a met from 02:20 (SpO2 -3 sustained 5 min); not_met at 02:15.
    assert _states(by[dt(d=21, h=2, mi=15)], "R2a") is not MET
    assert _states(by[dt(d=21, h=2, mi=20)], "R2a") is MET
    # R2b not_met all night (+0.3 L). R1 unknown (no SAT).
    for c in cells:
        assert _states(c, "R2b") is NOT_MET
        assert _states(c, "R1") is UNKNOWN


def _check_bed5(cells) -> None:
    # R2b met all night (+3.2 L, duplicate tx_ids do not change the net);
    # R2a not_met throughout.
    for c in cells:
        assert _states(c, "R2b") is MET
        assert _states(c, "R2a") is NOT_MET


def _check_bed6(cells) -> None:
    by = _by_time(cells)
    # R2a met from 01:05 (SpO2 branch).
    assert _states(by[dt(d=21, h=1, mi=0)], "R2a") is not MET
    assert _states(by[dt(d=21, h=1, mi=5)], "R2a") is MET
    # R2b not_met until 01:55, met from 02:00 (late-documented 1.0 L).
    assert _states(by[dt(d=21, h=1, mi=55)], "R2b") is NOT_MET
    assert _states(by[dt(d=21, h=2, mi=0)], "R2b") is MET
    # Combined message exactly from 02:00 (both met at the same grid point).
    assert by[dt(d=21, h=1, mi=55)].combined_message == ""
    assert by[dt(d=21, h=2, mi=0)].combined_message == R2_COMBINED_TEXT
    for t in grid(dt(d=21, h=2, mi=0), dt(d=21, h=7)):
        assert by[t].combined_message == R2_COMBINED_TEXT


def _check_bed7(cells) -> None:
    # Silent all night: R2a not_met (artefact ignored), nothing else met.
    for c in cells:
        assert _states(c, "R2a") is NOT_MET
        assert not _any_met(c)
        assert c.display_text == SILENCE_TEXT
        # A normal bed with fresh observations never raises a feed alert.
        assert c.feed_alert is False


def _check_bed8(cells) -> None:
    # R2a not_met all night (tagged pre-oxygenation excluded).
    for c in cells:
        assert _states(c, "R2a") is NOT_MET


def _check_bed9(cells) -> None:
    by = _by_time(cells)
    # Feed outage: every *observation-based* rule (R1, R2a) is unknown with a
    # feed alert on the grid from 01:15 to 02:25 inclusive (AC-DEF-5). R2b is a
    # fluid-ledger rule, not observation-based, so it is deliberately *not*
    # gated by observation staleness -- the alert is still raised ward-wide via
    # ``feed_alert`` (a visible failure state, never silence; AC-R3-failure).
    for t in grid(dt(d=21, h=1, mi=15), dt(d=21, h=2, mi=25)):
        assert _states(by[t], "R1") is UNKNOWN, t.isoformat()
        assert _states(by[t], "R2a") is UNKNOWN, t.isoformat()
        assert by[t].feed_alert is True, t.isoformat()
    # Fresh on either side of the outage: no feed alert.
    assert by[dt(d=21, h=1, mi=10)].feed_alert is False
    assert by[dt(d=21, h=2, mi=30)].feed_alert is False


def _check_bed10(cells) -> None:
    by = _by_time(cells)
    # R3 met (overdue) 01:10-01:50, then not_met from 01:55.
    for t in grid(dt(d=21, h=1, mi=10), dt(d=21, h=1, mi=50)):
        assert _states(by[t], "R3") is MET, t.isoformat()
        assert by[t].results["R3"].message == R3_OVERDUE_TEXT
    for t in grid(dt(d=21, h=1, mi=55), dt(d=21, h=7)):
        assert _states(by[t], "R3") is NOT_MET, t.isoformat()
    # Not overdue before 01:10.
    assert _states(by[dt(d=21, h=1, mi=5)], "R3") is NOT_MET


def _check_bed11(cells) -> None:
    # VV-ECMO: R1 and R2a not_applicable; R2b applies and is not_met (+1.0 L).
    for c in cells:
        assert _states(c, "R1") is NOT_APPLICABLE
        assert _states(c, "R2a") is NOT_APPLICABLE
        assert _states(c, "R2b") is NOT_MET


def _check_bed12(cells) -> None:
    by = _by_time(cells)
    # DNR is not an exclusion: R1 met from 23:05.
    assert _states(by[dt(d=20, h=23, mi=0)], "R1") is not MET
    assert _states(by[dt(d=20, h=23, mi=5)], "R1") is MET


def _check_bed13a(cells) -> None:
    by = _by_time(cells)
    # Encounter A: R2b met 19:00-23:00 (+2.4 L); R3 never met (no inheritance).
    for t in grid(dt(d=20, h=19), dt(d=20, h=23)):
        assert _states(by[t], "R2b") is MET, t.isoformat()
    for c in cells:
        assert _states(c, "R3") is not MET
        # No false feed alert: while A is on the board its observations are
        # fresh, and once it is discharged (23:00) it is off the board, so the
        # absence of any later observation must not raise a feed alert
        # (AC-R3-encounter; the active-window gate in evaluate_cell).
        assert c.feed_alert is False, c.t.isoformat()


def _check_bed13b(cells) -> None:
    by = _by_time(cells)
    # Encounter B: R1 unknown (no SAT); R2a/R2b unknown until 05:10,
    # not_met from 05:15 (insufficient_history on B's own history); R3 never met.
    for c in cells:
        assert _states(c, "R1") is UNKNOWN
        assert _states(c, "R3") is not MET
        # No false feed alert: before B is admitted (23:15) it is not on the
        # board, so the absence of observations must not raise a feed alert;
        # once admitted its observations are fresh (AC-R3-encounter).
        assert c.feed_alert is False, c.t.isoformat()
    # After admission but before first-obs + 6 h: unknown.
    assert _states(by[dt(d=21, h=5, mi=10)], "R2a") is UNKNOWN
    assert _states(by[dt(d=21, h=5, mi=10)], "R2b") is UNKNOWN
    # From 05:15: not_met (enough history, nothing triggered).
    for t in grid(dt(d=21, h=5, mi=15), dt(d=21, h=7)):
        assert _states(by[t], "R2a") is NOT_MET, t.isoformat()
        assert _states(by[t], "R2b") is NOT_MET, t.isoformat()


def _check_bed14(cells) -> None:
    # R1 unknown all night (weight_missing; never a guessed weight).
    for c in cells:
        assert _states(c, "R1") is UNKNOWN


def _check_bed15(cells) -> None:
    by = _by_time(cells)
    # Deferral across midnight: met 20:35-20:40 (prompt 1), suppressed
    # 20:45-01:25 (no midnight reset), met again 01:30 (prompt 2), unknown from
    # 06:35 (SAT older than 12 h).
    assert _states(by[dt(d=20, h=20, mi=35)], "R1") is MET
    assert _states(by[dt(d=20, h=20, mi=40)], "R1") is MET
    for t in grid(dt(d=20, h=20, mi=45), dt(d=21, h=1, mi=25)):
        assert _states(by[t], "R1") is SUPPRESSED, t.isoformat()
    assert _states(by[dt(d=21, h=1, mi=30)], "R1") is MET
    assert _states(by[dt(d=21, h=6, mi=35)], "R1") is UNKNOWN


def _check_bed16(cells) -> None:
    by = _by_time(cells)
    # Desaturation during tagged suctioning: R2a met at 03:05 (SpO2 branch is
    # never suppressed by a tag), not_met from 03:10.
    assert _states(by[dt(d=21, h=3, mi=5)], "R2a") is MET
    assert _states(by[dt(d=21, h=3, mi=10)], "R2a") is NOT_MET


def _check_bed17(cells) -> None:
    # CRRT: R2b unknown all night (output_not_charted); never met, never
    # silently treated as not_met.
    for c in cells:
        assert _states(c, "R2b") is UNKNOWN


_ORACLE = {
    "E01-1120": _check_bed1,
    "E02-1120": _check_bed2,
    "E03-1120": _check_bed3,
    "E04-1120": _check_bed4,
    "E05-1120": _check_bed5,
    "E06-1120": _check_bed6,
    "E07-1120": _check_bed7,
    "E08-1120": _check_bed8,
    "E09-1120": _check_bed9,
    "E10-1120": _check_bed10,
    "E11-1120": _check_bed11,
    "E12-1120": _check_bed12,
    "E13A-1120": _check_bed13a,
    "E13B-1120": _check_bed13b,
    "E14-1120": _check_bed14,
    "E15-1120": _check_bed15,
    "E16-1120": _check_bed16,
    "E17-1120": _check_bed17,
}


@pytest.mark.parametrize("encounter", sorted(_ORACLE))
def test_bed_oracle(ward: dict, encounter: str) -> None:
    """Each encounter's assembled cells match the frozen oracle timings."""

    _ORACLE[encounter](ward[encounter])


# ==========================================================================
# daily_totals.jsonl is loaded but never used by any rule (AC-R2b-no-dailytotals)
# ==========================================================================


def test_daily_totals_are_loaded(ds: Dataset) -> None:
    # The distractor is present in the dataset (so the "ignored" claim is real).
    assert len(ds.daily_totals) > 0


def test_daily_totals_never_change_the_ward_evaluation(ds: Dataset, ward: dict) -> None:
    """Corrupting every daily total must not change a single ward cell.

    If any rule reached past the ``daily_totals`` boundary, replacing those
    numbers with absurd values would move a fluid balance (or some other
    result). It does not: the full ward evaluation is byte-for-byte identical
    with the daily totals zeroed, inflated, or removed entirely.
    """

    baseline = ward  # the shared evaluation of the unmodified dataset

    # 1. Every daily total net inflated by +1,000,000 ml.
    inflated = dataclasses.replace(
        ds,
        daily_totals=tuple(
            dataclasses.replace(d, net_ml=d.net_ml + 1_000_000)
            for d in ds.daily_totals
        ),
    )
    assert evaluate_ward(inflated) == baseline

    # 2. Daily totals removed entirely.
    empty = dataclasses.replace(ds, daily_totals=())
    assert evaluate_ward(empty) == baseline


# ==========================================================================
# Determinism: re-running produces an identical structure.
# ==========================================================================


def test_ward_evaluation_is_deterministic(ds: Dataset, ward: dict) -> None:
    first = ward  # evaluated earlier in the session
    second = evaluate_ward(ds)
    assert first == second
    # A freshly loaded dataset yields the same result too (no hidden state).
    third = evaluate_ward(load_dataset())
    assert third == first


# ==========================================================================
# PBT-10 across all beds: silence text is the single constant iff nothing met,
# and never a banned word (AC-DEF-4, PBT-10).
# ==========================================================================


def _any_met(cell) -> bool:
    return any(r.state is MET for r in cell.results.values())


def test_pbt10_silence_text_across_every_cell(ward: dict) -> None:
    for enc, cells in ward.items():
        for c in cells:
            if _any_met(c):
                # A met rule drives the display via its own wording; the
                # orchestrator does not emit the silence constant.
                assert c.display_text == "", f"{enc} @ {c.t}"
            else:
                # Nothing met -> exactly the single silence constant.
                assert c.display_text == SILENCE_TEXT, f"{enc} @ {c.t}"


def test_pbt10_no_banned_word_anywhere(ward: dict) -> None:
    # The display text and the silence constant itself must never describe a
    # silent state as safe / stable / clear / green.
    for word in BANNED_SILENCE_WORDS:
        assert word not in SILENCE_TEXT.lower()
    for enc, cells in ward.items():
        for c in cells:
            text = c.display_text.lower()
            for word in BANNED_SILENCE_WORDS:
                assert word not in text, f"{enc} @ {c.t}: banned word {word!r}"


# ==========================================================================
# D29: R2a's "fluid balance unknown" label appears only when fluid data are
# missing or incomplete -- i.e. only when R2a is ``met`` AND R2b is ``unknown``
# on the same cell. The baseline applies the label "if fluid data are missing
# or incomplete" (AC-R2a-fluid-independent); whether the fluid ledger is
# incomplete is R2b's ``unknown`` result, which R2a (fluid-independent by
# construction) cannot see. The orchestrator completes R2a's *display detail*
# for the cell; R2a's own state/reason and R2b are never changed (D29, clinical
# lead 9 Nov -- fixes the prior build that appended the label to every R2a
# ``met``, even beside a complete R2b ledger).
# ==========================================================================

import dataclasses as _dc  # noqa: E402,F401  (dataclasses already imported above; kept explicit for the D29 block)

from hypothesis import given  # noqa: E402
from hypothesis import strategies as st  # noqa: E402

from sanad.evaluate import r2a_fluid_unknown_detail  # noqa: E402
from sanad.model import RuleResult  # noqa: E402
from sanad.r2a import FLUID_UNKNOWN_LABEL  # noqa: E402
from sanad.states import ReasonCode  # noqa: E402


def test_bed6_at_0200_r2a_detail_has_no_fluid_unknown_label(ward: dict) -> None:
    """Bed 6 at 02:00: R2a ``met`` *and* R2b ``met`` (+2.60 L, combined message
    shown) -- the fluid ledger is complete, so R2a's detail must NOT carry the
    "fluid balance unknown" label (the exact defect D29 corrects)."""

    by = _by_time(ward["E06-1120"])
    cell = by[dt(d=21, h=2, mi=0)]
    assert _states(cell, "R2a") is MET
    assert _states(cell, "R2b") is MET
    assert FLUID_UNKNOWN_LABEL not in cell.results["R2a"].detail
    # Sanity: the combined message is what is shown for a complete ledger.
    assert cell.combined_message == R2_COMBINED_TEXT


def test_bed4_at_0220_r2a_detail_has_no_fluid_unknown_label(ward: dict) -> None:
    """Bed 4 at 02:20: R2a ``met`` while R2b is ``not_met`` (+0.3 L, a recorded,
    complete ledger -- not ``unknown``). The ledger is present, so no label."""

    by = _by_time(ward["E04-1120"])
    cell = by[dt(d=21, h=2, mi=20)]
    assert _states(cell, "R2a") is MET
    assert _states(cell, "R2b") is NOT_MET
    assert FLUID_UNKNOWN_LABEL not in cell.results["R2a"].detail


# --- Synthetic unit test of the cross-rule label helper --------------------


def _syn_r2a(state: EvaluationState, detail: str = "SpO2 branch") -> RuleResult:
    return RuleResult(
        rule_id="R2a", state=state, reason=ReasonCode.OK_NOT_MET, detail=detail,
    )


def _syn_r2b(state: EvaluationState) -> RuleResult:
    reason = (
        ReasonCode.OUTPUT_NOT_CHARTED
        if state is UNKNOWN
        else ReasonCode.OK_NOT_MET
    )
    return RuleResult(rule_id="R2b", state=state, reason=reason)


def test_label_added_exactly_once_when_r2a_met_and_r2b_unknown() -> None:
    r2a_in = _syn_r2a(MET, detail="SpO2 branch")
    out = r2a_fluid_unknown_detail(r2a_in, _syn_r2b(UNKNOWN))
    # The label is appended to the detail, exactly once.
    assert out.detail == f"SpO2 branch; {FLUID_UNKNOWN_LABEL}"
    assert out.detail.count(FLUID_UNKNOWN_LABEL) == 1
    # R2a's own state and reason are untouched (rules stay independent).
    assert out.state is MET
    assert out.reason is r2a_in.reason
    assert out.rule_id == "R2a"


def test_label_bare_when_r2a_met_detail_empty_and_r2b_unknown() -> None:
    out = r2a_fluid_unknown_detail(_syn_r2a(MET, detail=""), _syn_r2b(UNKNOWN))
    assert out.detail == FLUID_UNKNOWN_LABEL


def test_label_not_added_when_r2b_not_unknown() -> None:
    r2a_in = _syn_r2a(MET, detail="SpO2 branch")
    for r2b_state in (MET, NOT_MET, NOT_APPLICABLE, SUPPRESSED):
        out = r2a_fluid_unknown_detail(r2a_in, _syn_r2b(r2b_state))
        assert FLUID_UNKNOWN_LABEL not in out.detail, r2b_state
        # Unchanged result when the label does not apply.
        assert out is r2a_in, r2b_state


def test_label_never_added_to_non_met_r2a() -> None:
    # Even with R2b unknown, a not_met / unknown R2a never carries the label
    # (only a ``met`` R2a can be fluid-labelled).
    for r2a_state in (NOT_MET, UNKNOWN, NOT_APPLICABLE, SUPPRESSED):
        r2a_in = _syn_r2a(r2a_state, detail="x")
        out = r2a_fluid_unknown_detail(r2a_in, _syn_r2b(UNKNOWN))
        assert FLUID_UNKNOWN_LABEL not in out.detail, r2a_state
        assert out is r2a_in, r2a_state


def test_helper_returns_none_for_none_r2a() -> None:
    assert r2a_fluid_unknown_detail(None, _syn_r2b(UNKNOWN)) is None


_ALL_STATES = st.sampled_from(list(EvaluationState))


@given(r2a_state=_ALL_STATES, r2b_state=_ALL_STATES)
def test_pbt_label_iff_r2a_met_and_r2b_unknown(
    r2a_state: EvaluationState, r2b_state: EvaluationState
) -> None:
    """Over every combination of R2a/R2b states, the label is in R2a's detail
    iff R2a is ``met`` and R2b is ``unknown``; R2a's state/reason never change
    and R2b is untouched (D29; AC-R2a-fluid-independent)."""

    r2a_in = _syn_r2a(r2a_state, detail="branch")
    r2b_in = _syn_r2b(r2b_state)
    out = r2a_fluid_unknown_detail(r2a_in, r2b_in)

    should_label = r2a_state is MET and r2b_state is UNKNOWN
    assert (FLUID_UNKNOWN_LABEL in out.detail) is should_label
    # State and reason are never altered by the display step.
    assert out.state is r2a_state
    assert out.reason is r2a_in.reason


def test_pbt_ward_label_iff_r2a_met_and_r2b_unknown(ward: dict) -> None:
    """Across every cell of all 18 encounters, the "fluid balance unknown"
    label is present in R2a's detail iff R2a is ``met`` and R2b is ``unknown``
    at that cell, and no R2a state ever changed because of the label."""

    for enc, cells in ward.items():
        for c in cells:
            r2a_res = c.results["R2a"]
            r2b_res = c.results["R2b"]
            should_label = (
                r2a_res.state is MET and r2b_res.state is UNKNOWN
            )
            has_label = FLUID_UNKNOWN_LABEL in r2a_res.detail
            assert has_label is should_label, f"{enc} @ {c.t}"
