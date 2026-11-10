"""Tile states equal the engine at the oracle sample times (tasks.md task 6).

This module is the board's **fidelity** check: it proves the states the page
would actually show equal what :func:`sanad.evaluate.evaluate_ward` computed,
at the specific sample points the oracle (``data/SCENARIOS.md``) fixes, read
back out of the **generated HTML** rather than the in-memory model. No engine
code changes for this task (tasks.md: "Create ``tests/test_board_states.py``
(no code change)"); the task only adds this test.

Why parse the HTML and not just the model dict? The viewer reads **only** the
``#board-data`` JSON embedded in the page and shows a cell's state by index
(design.md §4; AC-GEN-6). So the embedded JSON is the single source the UI
renders from. Parsing it out of the generated HTML (unescaping the ``<``/``>``/
``&`` entities first, design.md §3d) and asserting its cells against the oracle
is the end-to-end fidelity guarantee: a tile can never drift from the rule
result the engine produced for that encounter at that grid time
(AC-FID-1, AC-FID-2, AC-FID-3), the state is exactly one verbatim state word
(AC-STATE-1), an ``unknown`` names the missing item in its reason code
(AC-STATE-5), a silent bed carries the single silence text and no ``met`` rule
(AC-S2-silence), and a missing item is never folded into silence
(AC-SILENCE-3).

Expected values below are copied from ``data/SCENARIOS.md`` (the frozen oracle);
the engine is corrected to match the oracle, never the reverse
(``.kiro/steering/safety.md``). The two parts:

* **scenario-oracle tests** over the real fixed dataset, read from the embedded
  ``board-data`` of the generated HTML, at the oracle sample times;
* a **property-based test** (hypothesis) over the whole embedded board that
  every cell's state/reason/display is a verbatim enum word and a silent cell
  never carries a ``met`` rule or a banned word (no synthetic rule logic; the
  invariant must hold for every one of the real cells).

Reads the fixed dataset read-only through the shared ``board_html`` fixture and
never writes to ``docs/`` or ``data/`` (safety steering).
"""

from __future__ import annotations

import html as html_mod
import json
import re
from datetime import datetime, timedelta, timezone

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from sanad.states import (
    SILENCE_TEXT,
    BANNED_SILENCE_WORDS,
    EvaluationState,
    ReasonCode,
    WorkflowState,
)

TZ = timezone(timedelta(hours=1))

# The four rule ids as they key each embedded cell's ``results`` map (design.md
# §3b): the verbatim rule-id strings, the same words the model test and the
# engine use.
R1, R2A, R2B, R3 = "R1", "R2a", "R2b", "R3"

_STATE_WORDS = {s.value for s in EvaluationState}
_REASON_WORDS = {r.value for r in ReasonCode}
_WORKFLOW_WORDS = {w.value for w in WorkflowState}


# ==========================================================================
# Helpers: pull the embedded board-data JSON out of the generated HTML.
# ==========================================================================


def _board_data(html: str) -> dict:
    """Parse the ``#board-data`` JSON embedded in the generated HTML.

    The embedded text has ``<`` / ``>`` / ``&`` written as entities so no data
    can close the ``<script>`` tag (design.md §3d); unescape before parsing, the
    same way the viewer's ``JSON.parse`` sees it.
    """

    m = re.search(
        r'<script type="application/json" id="board-data">(.*?)</script>',
        html,
        re.DOTALL,
    )
    assert m, "board-data script block not found"
    return json.loads(html_mod.unescape(m.group(1)))


def _cells_by_encounter(data: dict) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for bed in data["beds"]:
        for encounter, payload in bed["encounters"].items():
            out[encounter] = payload["cells"]
    return out


def _iso(d: int, h: int, mi: int) -> str:
    return datetime(2026, 11, d, h, mi, tzinfo=TZ).isoformat()


@pytest.fixture(scope="module")
def data(board_html: str) -> dict:
    """The board model as the viewer sees it: parsed from the embedded JSON."""

    return _board_data(board_html)


@pytest.fixture(scope="module")
def cells(data: dict) -> dict[str, list[dict]]:
    return _cells_by_encounter(data)


def _at(cells: dict[str, list[dict]], enc: str, d: int, h: int, mi: int) -> dict:
    iso = _iso(d, h, mi)
    return next(c for c in cells[enc] if c["t"] == iso)


# ==========================================================================
# AC-FID-2: the oracle sample points (copied from data/SCENARIOS.md).
# ==========================================================================


def test_bed1_r1_met_at_2220(cells: dict[str, list[dict]]) -> None:
    """Bed 1: R1 met from 22:20 (and not met at the point just before)."""

    assert _at(cells, "E01-1120", 20, 22, 20)["results"][R1]["state"] == "met"
    # Strictly one verbatim state word (AC-STATE-1).
    assert _at(cells, "E01-1120", 20, 22, 15)["results"][R1]["state"] in _STATE_WORDS
    assert _at(cells, "E01-1120", 20, 22, 15)["results"][R1]["state"] != "met"


def test_bed6_combined_message_absent_1155_present_0200(
    cells: dict[str, list[dict]]
) -> None:
    """Bed 6: the combined R2 message is absent at 01:55 and present at 02:00
    (R2a met from 01:05, R2b met only from 02:00 as known at t)."""

    assert _at(cells, "E06-1120", 21, 1, 55)["combined_message"] == ""
    combined = _at(cells, "E06-1120", 21, 2, 0)["combined_message"]
    assert combined != ""
    # The combined message is present exactly when both R2a and R2b are met.
    both = _at(cells, "E06-1120", 21, 2, 0)
    assert both["results"][R2A]["state"] == "met"
    assert both["results"][R2B]["state"] == "met"


def test_bed9_feed_alert_and_stale_unknown_0115_and_0225(
    cells: dict[str, list[dict]]
) -> None:
    """Bed 9: feed_alert true and R1/R2a unknown (stale_data) at 01:15 and
    02:25; feed_alert false once fresh again at 02:30 (AC-FID-3)."""

    for h, mi in ((1, 15), (2, 25)):
        cell = _at(cells, "E09-1120", 21, h, mi)
        # The failure is its own visible state, never silence (AC-FID-3).
        assert cell["feed_alert"] is True
        assert cell["results"][R1]["state"] == "unknown"
        assert cell["results"][R1]["reason"] == "stale_data"
        assert cell["results"][R2A]["state"] == "unknown"
        assert cell["results"][R2A]["reason"] == "stale_data"
    # Fresh again from 02:30: the feed alert has cleared.
    assert _at(cells, "E09-1120", 21, 2, 30)["feed_alert"] is False


def test_bed10_r3_met_0110_through_0150_not_met_0155(
    cells: dict[str, list[dict]]
) -> None:
    """Bed 10: R3 met (overdue) 01:10 through 01:50 inclusive, not_met from
    01:55 once the 01:50/01:52-documented valid check is known."""

    for h, mi in ((1, 10), (1, 15), (1, 30), (1, 50)):
        assert _at(cells, "E10-1120", 21, h, mi)["results"][R3]["state"] == "met"
    assert _at(cells, "E10-1120", 21, 1, 55)["results"][R3]["state"] == "not_met"


def test_bed7_silent_with_silence_text_and_no_met_rule_every_index(
    cells: dict[str, list[dict]]
) -> None:
    """Bed 7: silent all night -- every cell carries the single silence text
    and no rule is met, never a safe/green state (AC-S2-silence, AC-SILENCE-3,
    AC-FID-1)."""

    bed7 = cells["E07-1120"]
    assert bed7, "bed 7 has no cells"
    for cell in bed7:
        assert cell["display_text"] == SILENCE_TEXT
        assert all(r["state"] != "met" for r in cell["results"].values())
        # The failure channel is clear too: silence is only ever shown when
        # there is no feed alert (a stale bed shows the alert, not silence).
        assert cell["feed_alert"] is False


# ==========================================================================
# AC-STATE-5 / AC-SILENCE-3: unknown names its missing item; missing is never
# folded into silence (shown as unknown, never blank, never "met").
# ==========================================================================


def test_unknown_cells_name_their_missing_item(
    cells: dict[str, list[dict]]
) -> None:
    """Every ``unknown`` rule result carries a non-empty reason code naming the
    missing/stale/unresolved item -- never a blank or a silent gap
    (AC-STATE-5, AC-SILENCE-3). Sampled across the whole embedded board, so it
    holds for beds 2/3/14 (unknown all night) and bed 9 (stale)."""

    saw_unknown = False
    for enc_cells in cells.values():
        for cell in enc_cells:
            for result in cell["results"].values():
                if result["state"] == "unknown":
                    saw_unknown = True
                    assert result["reason"] in _REASON_WORDS
                    assert result["reason"] != ""
    assert saw_unknown, "no unknown result found in the embedded board"


def test_beds_unknown_all_night_are_never_blank_and_never_met(
    cells: dict[str, list[dict]]
) -> None:
    """Beds 2, 3 and 14 are R1 unknown all night. The missing item must be
    named (a non-blank reason code) at every grid point, never blank and never
    collapsed into a silent "met" (AC-STATE-5, AC-SILENCE-3; data/SCENARIOS.md
    beds 2/3/14).

    The oracle fixes the *state* (unknown all night) and the dominant reason;
    the exact reason can still vary within the night by the shared
    missing-item precedence (e.g. before a bed's own SAT the missing SAT
    dominates), so this asserts the state and that a reason is always named,
    and that each bed's documented dominant reason does occur.
    """

    dominant = {
        "E02-1120": "sat_not_recorded",
        "E03-1120": "haemo_unconfirmed",
        "E14-1120": "weight_missing",
    }
    for enc, dom in dominant.items():
        seen: set[str] = set()
        for cell in cells[enc]:
            r1 = cell["results"][R1]
            assert r1["state"] == "unknown", (enc, cell["t"])
            assert r1["reason"] in _REASON_WORDS, (enc, cell["t"], r1["reason"])
            assert r1["reason"] != "", (enc, cell["t"])
            seen.add(r1["reason"])
        assert dom in seen, (enc, dom, sorted(seen))


# ==========================================================================
# AC-STATE-1 / AC-FID-1: every embedded state is exactly one verbatim word,
# and a silent cell never carries a met rule or a banned word.
# ==========================================================================


def test_every_embedded_state_is_a_verbatim_word(
    cells: dict[str, list[dict]]
) -> None:
    for enc_cells in cells.values():
        for cell in enc_cells:
            for result in cell["results"].values():
                assert result["state"] in _STATE_WORDS
                assert result["reason"] in _REASON_WORDS
            for ws in cell["workflow_states"].values():
                assert ws in _WORKFLOW_WORDS


def test_silent_cells_carry_no_met_rule_and_no_banned_word(
    cells: dict[str, list[dict]]
) -> None:
    """Wherever the silence text is shown, no rule is met and the text is the
    single silence constant -- never safe/stable/clear/green (AC-S2-silence,
    AC-SILENCE-3; PBT-10)."""

    for enc_cells in cells.values():
        for cell in enc_cells:
            if cell["display_text"]:
                assert cell["display_text"] == SILENCE_TEXT
                assert all(r["state"] != "met" for r in cell["results"].values())
    lowered = SILENCE_TEXT.lower()
    for word in BANNED_SILENCE_WORDS:
        assert not re.search(rf"\b{re.escape(word)}\b", lowered), word


# ==========================================================================
# Property-based: the whole embedded board upholds the fidelity invariants.
# ==========================================================================


@given(data=st.data())
@settings(max_examples=25)
def test_pbt_every_cell_invariants_hold(cells, data) -> None:
    """For any encounter and any grid index drawn, the embedded cell obeys the
    display invariants: exactly one state word per rule; ``met`` only when the
    cell is not silent; a silent cell carries the single silence text and no
    met rule (AC-STATE-1, AC-S2-silence, AC-SILENCE-3). The fixed dataset is
    the only data; nothing is recomputed (no network, no rule logic)."""

    by_enc = cells
    enc = data.draw(st.sampled_from(sorted(by_enc)))
    enc_cells = by_enc[enc]
    i = data.draw(st.integers(min_value=0, max_value=len(enc_cells) - 1))
    cell = enc_cells[i]
    for result in cell["results"].values():
        assert result["state"] in _STATE_WORDS
        assert result["reason"] in _REASON_WORDS
    any_met = any(r["state"] == "met" for r in cell["results"].values())
    if cell["display_text"]:
        assert cell["display_text"] == SILENCE_TEXT
        assert not any_met
    else:
        # No silence text means a rule is met, a feed alert is up, or every
        # rule is a non-met state whose reason is still named (never blank).
        for result in cell["results"].values():
            assert result["reason"] != ""

