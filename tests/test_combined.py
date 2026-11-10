"""R2 combined-message + silence scenario-oracle tests (``data/SCENARIOS.md``).

Asserts the orchestrator's cross-rule output against the frozen oracle, on the
shared 5-minute grid:

* **R2 combined message (AC-R2-comb)** -- bed 6: R2a is ``met`` from 01:05
  (SpO2 branch) and R2b only becomes ``met`` from 02:00 (a 1.0 L intake given
  20:00 but documented 02:00 becomes visible at 02:00 and tips the 72-h net
  past +2,000 ml). The combined message therefore first appears at **02:00**,
  not at 01:05, and the wording is exactly
  :data:`~sanad.states.R2_COMBINED_TEXT` (lists alternative causes; does not
  establish pulmonary oedema or indicate fluid removal).

* **Silence (AC-DEF-4, PBT-10)** -- a bed with no ``met`` rule renders exactly
  "No configured rule triggered on the available data" and never any of the
  banned words *safe / stable / clear / green*. Bed 7 is silent all night
  (R2a ``not_met`` artefact ignored, R2b ``not_met`` +0.8 L, R1 ``unknown``
  no SAT); bed 6 is silent before R2a fires (before 01:05); and wherever a rule
  *is* ``met`` the display text is empty (the rule's own approved wording shows
  instead of silence).

Reads the fixed dataset read-only (safety steering); never writes.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from sanad.evaluate import evaluate_cell, r2_combined_message
from sanad.model import Dataset
from sanad.states import (
    BANNED_SILENCE_WORDS,
    SILENCE_TEXT,
    EvaluationState,
    R2_COMBINED_TEXT,
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
# Bed 6: R2 combined message from 02:00 (R2a met 01:05, R2b met 02:00).
# ==========================================================================


def test_bed6_combined_message_from_0200(ds: Dataset) -> None:
    enc = "E06-1120"

    # Before 02:00 there is no combined message: R2a is met from 01:05 but R2b
    # is still not_met (its late-documented 1.0 L intake is invisible), so the
    # two are never both met at the same grid point.
    for t in grid(dt(d=20, h=19), dt(d=21, h=1, mi=55)):
        cell = evaluate_cell(ds, enc, t)
        assert cell.combined_message == "", f"unexpected combined message at {t}"

    # From 02:00 onwards both R2a and R2b are met at the same grid point, so the
    # combined message is present and exactly the approved wording.
    for t in grid(dt(d=21, h=2, mi=0), dt(d=21, h=7)):
        cell = evaluate_cell(ds, enc, t)
        assert cell.results["R2a"].state is EvaluationState.MET
        assert cell.results["R2b"].state is EvaluationState.MET
        assert cell.combined_message == R2_COMBINED_TEXT


def test_bed6_combined_message_absent_at_0155_present_at_0200(ds: Dataset) -> None:
    enc = "E06-1120"
    # Exactly one step before: R2b not_met -> no combined message.
    before = evaluate_cell(ds, enc, dt(d=21, h=1, mi=55))
    assert before.results["R2a"].state is EvaluationState.MET
    assert before.results["R2b"].state is EvaluationState.NOT_MET
    assert before.combined_message == ""
    # At 02:00: both met -> combined message appears.
    at = evaluate_cell(ds, enc, dt(d=21, h=2, mi=0))
    assert at.combined_message == R2_COMBINED_TEXT


def test_bed6_silent_before_r2a_fires(ds: Dataset) -> None:
    # Before R2a fires at 01:05, nothing is met on bed 6 -> the cell is silent
    # (display_text is the single silence constant), never "safe/green".
    enc = "E06-1120"
    for t in grid(dt(d=20, h=19), dt(d=21, h=1, mi=0)):
        cell = evaluate_cell(ds, enc, t)
        assert not _any_met(cell)
        assert cell.display_text == SILENCE_TEXT


def test_bed6_display_text_empty_once_a_rule_is_met(ds: Dataset) -> None:
    # From 01:05 R2a is met, so the display is driven by the rule's own wording:
    # display_text is empty (never the silence text when something is met).
    enc = "E06-1120"
    for t in grid(dt(d=21, h=1, mi=5), dt(d=21, h=7)):
        cell = evaluate_cell(ds, enc, t)
        assert _any_met(cell)
        assert cell.display_text == ""


# ==========================================================================
# Silence: bed 7 is silent all night, rendered with the single silence text
# and never any banned word (AC-DEF-4, PBT-10).
# ==========================================================================


def test_bed7_silent_all_night(ds: Dataset) -> None:
    enc = "E07-1120"
    for t in _night_grid():
        cell = evaluate_cell(ds, enc, t)
        # Nothing is ever met on bed 7.
        assert not _any_met(cell)
        # The silence render is exactly the one constant, nothing else.
        assert cell.display_text == SILENCE_TEXT
        assert cell.combined_message == ""


def test_silence_text_never_uses_a_banned_word(ds: Dataset) -> None:
    # The silence string itself must never contain safe/stable/clear/green.
    lowered = SILENCE_TEXT.lower()
    for word in BANNED_SILENCE_WORDS:
        assert word not in lowered
    # And every silent cell across bed 7 renders only that vetted string.
    enc = "E07-1120"
    for t in _night_grid():
        cell = evaluate_cell(ds, enc, t)
        text = cell.display_text.lower()
        for word in BANNED_SILENCE_WORDS:
            assert word not in text


# ==========================================================================
# r2_combined_message is a pure function of the two results.
# ==========================================================================


def test_r2_combined_message_requires_both_met(ds: Dataset) -> None:
    enc = "E06-1120"
    # Both met -> message.
    both = evaluate_cell(ds, enc, dt(d=21, h=2, mi=0))
    assert (
        r2_combined_message(both.results["R2a"], both.results["R2b"])
        == R2_COMBINED_TEXT
    )
    # R2a met, R2b not_met -> no message.
    one = evaluate_cell(ds, enc, dt(d=21, h=1, mi=55))
    assert r2_combined_message(one.results["R2a"], one.results["R2b"]) == ""
    # Either argument None -> no message (defensive: a rule not run).
    assert r2_combined_message(None, both.results["R2b"]) == ""
    assert r2_combined_message(both.results["R2a"], None) == ""


def _any_met(cell) -> bool:
    return any(r.state is EvaluationState.MET for r in cell.results.values())
