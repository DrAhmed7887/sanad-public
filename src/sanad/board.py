"""Ward board generator: serialise the engine's results into a board model.

The board is an **offline generator** (design.md): it calls
:func:`sanad.evaluate.evaluate_ward` over the night window, serialises the
precomputed per-grid-point :class:`~sanad.model.GridCell` results (plus the
fixed UI copy) into one plain, JSON-safe ``dict`` -- the *board model* -- and
(in later tasks) renders that model into a single self-contained offline HTML
file.

This module (task 1) provides :func:`build_board_model`, the first of the three
layers in design.md Section 1::

    build_board_model(ds, [results]) -> JSON-safe board model dict
    render_html(board_model)         -> one HTML string            (later task)
    main(argv)                       -> write the HTML file         (later task)

``build_board_model`` **never recomputes a rule**. Every cell's
``state`` / ``reason`` / ``message`` is copied verbatim from the ``GridCell``
that :func:`evaluate.evaluate_ward` already produced (AC-GEN-6, AC-FID-1); the
only transformation is serialisation:

* enums are written as their verbatim ``.value`` word -- ``met``, ``unknown``,
  ``sat_not_recorded``, ``notified`` … (AC-STATE-2);
* ``datetime`` values are ISO ``+01:00`` strings;
* everything else is a plain ``str`` / ``int`` / ``bool`` / ``list`` / ``dict``.

Ordering is fixed and severity-free (AC-ORDER-1, AC-ORDER-2): beds by integer
bed number, episodes and inbox items by time raised. Bed 13 (a reassignment)
carries **both** its encounters so the viewer can show whichever is in the bed
at the selected time (AC-S2-grid).

Static UI copy (the persistent label, the intended-use and
verification-vs-validation sentences, the ward line and the approved rule
wording) is lifted verbatim from :mod:`sanad.states` and the baseline, never
re-typed with changes (AC-LABEL-*, AC-STATE-3, AC-SILENCE-1).

Pure and deterministic: ``(dataset) -> board model``; no I/O beyond the
already-loaded dataset, no wall-clock, no RNG, no dict/set/filesystem-order
dependence. Stdlib only, isolated-mode safe.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Optional, Sequence

from . import evaluate, loader, r3
from .model import Dataset, GridCell, RuleResult
from .states import (
    EvaluationState,
    R1_MET_TEXT,
    R2_COMBINED_TEXT,
    R3_OVERDUE_TEXT,
    SILENCE_TEXT,
)

__all__ = [
    "PERSISTENT_LABEL",
    "INTENDED_USE",
    "VERIFICATION",
    "WARD_LINE",
    "THRESHOLD_LABEL",
    "FLUID_UNKNOWN_LABEL",
    "FEED_ALERT_LABEL",
    "CRITERIA_SOURCES",
    "PALETTE",
    "RULE_IDS",
    "NURSE_RULES",
    "DOCTOR_RULES",
    "SCREENS",
    "build_static_copy",
    "build_board_model",
    "render_html",
    "main",
]

# --- Static UI copy (verbatim; never paraphrased) -------------------------
#
# The persistent label and the two regulatory sentences are the exact strings
# from the signed baseline (``docs/EVIDENCE.md`` / ``.kiro/steering/*``); the
# ward line is the Screen-1 string from ``docs/UI_FLOW.md`` (Gate G2). The rule
# messages come from :mod:`sanad.states` so there is a single source of truth
# and no drift is possible.

PERSISTENT_LABEL = "FICTIONAL DATA · SIMULATION · NOT FOR CLINICAL USE"

INTENDED_USE = (
    "Offline software demonstration using fictional adult ICU scenarios. "
    "Illustrates configurable rules and notification workflows. Not intended "
    "to monitor people, assess SBT readiness, detect deterioration, prioritise "
    "clinical care, or support diagnosis or treatment. Do not enter patient "
    "data. No clinical performance has been established."
)

VERIFICATION = (
    "Synthetic scenarios and automated checks exercise the demonstration's "
    "configured logic. They do not establish clinical performance, safety or "
    "benefit."
)

WARD_LINE = "Night of 20–21 Nov 2026 · 17 beds · fictional ward"

THRESHOLD_LABEL = "DESIGN demo values, not emergency alarm thresholds"

FLUID_UNKNOWN_LABEL = "fluid balance unknown"

# The baseline has no approved sentence for the feed alert (D27 answer 1: where
# the baseline has no approved sentence, the screen shows only the rule name,
# the state word and the reason code). The feed alert is a *failure* indicator,
# not a rule message, so the chip/banner carries this neutral, non-clinical
# label only -- it makes no claim and uses none of the banned silence words
# (safe / stable / clear / green). It is kept here so the viewer never
# synthesises wording of its own.
FEED_ALERT_LABEL = "feed alert"

# The R1 criteria list (0, a-f, the 120-min duration) with each criterion's
# source line copied **verbatim** from the R1 table in ``docs/EVIDENCE.md``
# (Screen 5 shows "each criterion's source line from docs/EVIDENCE.md";
# AC-S5-r1 as amended by D28: labels and sources only, no per-criterion state
# or data in this build). Each ``source`` string is a verbatim substring of the
# signed baseline, so the drift test (``tests/test_board_wording.py``) reading
# ``docs/EVIDENCE.md`` at test time anchors it to the source and the hand-typed
# copy here cannot drift. ``label`` is the criterion wording (also verbatim from
# the baseline's "Criterion" column, except the duration label which is the
# baseline's "All criteria hold for more than 120 min").
CRITERIA_SOURCES = (
    {
        "id": "0",
        "label": (
            'Passed spontaneous awakening trial (SAT) in the previous 12 h, '
            'or "SAT not indicated" documented in the previous 12 h'
        ),
        "source": (
            'MODE protocol (NCT05563779, App. 3, Part I): "If the patient '
            'passes the SAT, then the patient should be promptly evaluated in '
            'a Spontaneous Breathing Trial (SBT) Readiness Assessment"; 12-h '
            "window: DESIGN"
        ),
    },
    {
        "id": "a",
        "label": "FiO2 ≤ 0.5 and PEEP ≤ 8 cmH2O",
        "source": "MODE, verbatim",
    },
    {
        "id": "b",
        "label": (
            "FiO2 and PEEP each ≤ their value 12 h earlier (the observation "
            "nearest t−12 h, within 15 min; none → `unknown`)"
        ),
        "source": (
            'MODE: "Values of both PEEP and FiO2 ≤ values from previous 12 '
            'hours" (literal point reading: DESIGN interpretation)'
        ),
    },
    {
        "id": "c",
        "label": "No neuromuscular blocking agent infusing",
        "source": "MODE, verbatim",
    },
    {
        "id": "d",
        "label": "Valid clinician confirmation of adequate inspiratory effort",
        "source": (
            'MODE ("Patient is exhibiting adequate inspiratory efforts"); '
            "confirmation: DESIGN"
        ),
    },
    {
        "id": "e",
        "label": (
            "SBP > 90 mmHg on every fresh observation in the window; "
            "norepinephrine < 10 mcg/min; dopamine and dobutamine < 5 "
            "mcg/kg/min; **any other vasoactive agent** (vasopressin, "
            "epinephrine, phenylephrine, milrinone) → valid clinician "
            "haemodynamics confirmation required"
        ),
        "source": (
            "MODE, verbatim thresholds; the extra-agent rule: DESIGN (one "
            "drug can hide another)"
        ),
    },
    {
        "id": "f",
        "label": (
            "Context gate: respiratory rate > 35/min or pH < 7.30 (when "
            "measured) → `not_met`, reason `context_review`"
        ),
        "source": (
            'MODE SBT tolerance limits ("Total Respiratory Rate ≤ 35 / min", '
            '"pH ≥ 7.30"); use as a pre-screen gate: DESIGN'
        ),
    },
    {
        "id": "⏱",
        "label": "All criteria hold for **more than 120 min**",
        "source": 'MODE: "present for more than 2 hours"',
    },
)

# --- Palette (design.md §4 "Palette") -------------------------------------
#
# Neutral greys plus ONE non-green accent for ``met``; no green anywhere
# (AC-SILENCE-2: a silent / non-triggering bed is never rendered green, and
# green is never in the state palette). Every colour used in the inline
# ``<style>`` block is listed here and checked by
# ``tests/test_board_wording.py`` -- the test proves (a) every hex colour in
# the stylesheet is in this tuple, and (b) none of these colours is green.
# "Green" is defined as a hue in 75°-165° with saturation > 20% (the test
# converts each hex to HSL and asserts it falls outside that band), matching
# the requirement wording so a stray greenish grey cannot slip in. The accent
# is a warm orange, deliberately far from green.
PALETTE = (
    "#1b1d21",  # --bg      near-black panel background
    "#26292e",  # --panel   raised panel grey
    "#f2f3f5",  # --ink     near-white text
    "#b7bcc4",  # --muted   muted grey text
    "#3a3e45",  # --line    hairline grey
    "#c7622d",  # --accent  warm orange accent for `met` (non-green)
)

# The rule ids, in a fixed display order (R1, R2a, R2b, R3).
RULE_IDS = (
    evaluate.R1_RULE_ID,
    evaluate.R2A_RULE_ID,
    evaluate.R2B_RULE_ID,
    evaluate.R3_RULE_ID,
)

# Routing per UI_FLOW Screen 4: R3 overdue and feed alerts go to the nurse's
# inbox; R1 prompts and R2 (combined) messages go to the doctor's episode list.
NURSE_RULES = (evaluate.R3_RULE_ID,)
DOCTOR_RULES = (evaluate.R1_RULE_ID, evaluate.R2A_RULE_ID, evaluate.R2B_RULE_ID)

# The five screens of ``docs/UI_FLOW.md`` (Gate G2, D27): each is one
# ``data-screen`` container in the rendered HTML, with a stable id the viewer
# shows/hides by (design.md Section 4). The order is the flow order; the id is
# the stable attribute, the title is Screen-1-style display copy filled by a
# later task's viewer -- task 3 only guarantees the container exists.
SCREENS = (
    ("start", "Start"),
    ("ward", "Ward board"),
    ("bed", "Bed detail"),
    ("inbox", "Inbox"),
    ("review", "Review prompt"),
)

# Episode groups (design.md §3c, D28): R2a and R2b form ONE doctor item "R2",
# a run of grid points where either is ``met``; the item shows the combined
# message while the cell carries it. R1 and R3 are their own groups.
R2_GROUP = "R2"
EPISODE_GROUPS = (
    (evaluate.R1_RULE_ID, (evaluate.R1_RULE_ID,)),
    (R2_GROUP, (evaluate.R2A_RULE_ID, evaluate.R2B_RULE_ID)),
    (evaluate.R3_RULE_ID, (evaluate.R3_RULE_ID,)),
)


def build_static_copy() -> dict:
    """The verbatim UI copy block embedded in the board model.

    Every value is a fixed string lifted from the baseline / :mod:`sanad.states`
    / ``docs/UI_FLOW.md`` (Gate G2); none is synthesised or paraphrased
    (AC-LABEL-*, AC-STATE-3, AC-SILENCE-1, AC-S3-threshold-label). The block
    also carries ``criteria_sources`` -- the R1 criteria labels (0, a-f, the
    120-min duration) and each criterion's source line copied verbatim from the
    R1 table in ``docs/EVIDENCE.md`` -- shown on Screen 5 (AC-S5-r1, D28). A
    drift test (``tests/test_board_wording.py``) reads the source documents at
    test time and asserts every string here appears in them verbatim, so the
    hand-typed copy cannot drift from the signed baseline.
    """

    return {
        "persistent_label": PERSISTENT_LABEL,
        "intended_use": INTENDED_USE,
        "verification": VERIFICATION,
        "ward_line": WARD_LINE,
        "silence_text": SILENCE_TEXT,
        "r1_met_text": R1_MET_TEXT,
        "r2_combined_text": R2_COMBINED_TEXT,
        "r3_overdue_text": R3_OVERDUE_TEXT,
        "threshold_label": THRESHOLD_LABEL,
        "fluid_unknown_label": FLUID_UNKNOWN_LABEL,
        "feed_alert_label": FEED_ALERT_LABEL,
        # The R1 criteria labels and their docs/EVIDENCE.md source lines, shown
        # on Screen 5 when an R1 episode is opened (AC-S5-r1 as amended by D28).
        # ``dict(c)`` copies each entry so the embedded model owns plain dicts.
        "criteria_sources": [dict(c) for c in CRITERIA_SOURCES],
    }


def _iso(dt) -> str:
    """Serialise a timezone-aware ``datetime`` to its ISO ``+01:00`` string."""

    return dt.isoformat()


def _rule_result_to_dict(result: RuleResult) -> dict:
    """Serialise one :class:`~sanad.model.RuleResult` to a JSON-safe dict.

    State and reason are written as their verbatim enum ``.value`` words
    (AC-STATE-2); ``detail`` and ``message`` are copied exactly as the rule
    produced them -- the board never synthesises or changes wording
    (AC-GEN-6, AC-FID-1). ``message`` is the approved sentence only when the
    rule is ``met``; the orchestrator leaves it empty otherwise.

    ``show_reason`` is a **display-only** flag decided here, in Python, where
    comparing the state word is allowed (the viewer must never carry a
    state-word literal; AC-GEN-6). A ``met`` chip shows no reason code -- the
    engine's default ``met`` reason (``ok_not_met``) is an internal placeholder,
    not a clinical message, and would read as a false "not met" cue on an
    otherwise met chip (F6). Every other state keeps its reason code shown
    verbatim (D27 answer 2). The engine's ``state`` / ``reason`` are untouched;
    only whether the reason is *displayed* is set here.
    """

    return {
        "rule_id": result.rule_id,
        "state": result.state.value,
        "reason": result.reason.value,
        "detail": result.detail,
        "message": result.message,
        "episode_id": result.episode_id,
        "show_reason": result.state is not EvaluationState.MET,
    }


def _cell_to_dict(cell: GridCell, active: bool) -> dict:
    """Serialise one :class:`~sanad.model.GridCell` to a JSON-safe dict.

    The per-rule results, combined message, feed alert, display/silence text and
    workflow-state words are copied straight from the cell (AC-GEN-8,
    AC-FID-1). Nothing is recomputed into a different state.

    ``active`` is the occupant flag for this encounter at the cell's time --
    :func:`sanad.r3.is_active`, i.e. admitted and not yet discharged as known at
    ``t`` -- so the viewer can show whichever encounter is *currently in the
    bed* at the selected clock time without inspecting rule reasons (AC-S2-grid).
    For bed 13's reassignment, ``E13A`` is ``active`` until its 23:00 discharge
    and ``E13B`` from its 23:15 admission; every single-occupant bed is active
    across its whole evaluated window. The flag is derived once in
    :func:`build_board_model` from the same admission/discharge bounds R3 uses
    and passed in here -- it is not recomputed from raw data by the viewer
    (AC-GEN-6).
    """

    return {
        "bed": cell.bed,
        "encounter": cell.encounter,
        "t": _iso(cell.t),
        "active": active,
        "results": {
            rule_id: _rule_result_to_dict(cell.results[rule_id])
            for rule_id in RULE_IDS
            if rule_id in cell.results
        },
        "combined_message": cell.combined_message,
        "feed_alert": cell.feed_alert,
        "display_text": cell.display_text,
        "workflow_states": {
            rule_id: state.value
            for rule_id, state in cell.workflow_states.items()
        },
    }


def _runs_of(flags: list[bool]) -> list[tuple[int, int]]:
    """Index runs ``(start_idx, end_idx)`` of consecutive ``True`` in ``flags``.

    ``end_idx`` is the index of the **last** ``True`` cell of the run (inclusive)
    -- so a run that is a single cell has ``start_idx == end_idx``. A ``False``
    cell (any other state, or no cell) breaks the run, which is exactly the
    contiguous-episode rule R1 uses over the grid (``r1.r1_prompt_times``):
    a run is broken by any non-triggering point, so a rule that is ``met``,
    then held/not_met, then ``met`` again yields **two** runs = two episodes
    (bed 15's two R1 prompts), not one (R1-episodes, PBT-4).
    """

    runs: list[tuple[int, int]] = []
    start: Optional[int] = None
    for i, flag in enumerate(flags):
        if flag and start is None:
            start = i
        elif not flag and start is not None:
            runs.append((start, i - 1))
            start = None
    if start is not None:
        runs.append((start, len(flags) - 1))
    return runs


def _episodes_from_ward(
    ds: Dataset, results: dict[str, list[GridCell]]
) -> tuple[list[dict], list[dict]]:
    """Derive the doctor's episode list and the nurse's inbox from the grid.

    An *episode* is one open notification for a ``(encounter, rule)``: it spans a
    **contiguous run of grid points where that rule is ``met``** (R1 prompt,
    R2a/R2b for the combined R2 message, R3 overdue) or, for the nurse's inbox,
    a contiguous run where a feed alert is active. Because a run is broken by any
    non-triggering point, a rule that is ``met``, then held (``suppressed`` by a
    deferral) or ``not_met``, then ``met`` again yields **two** episodes -- this
    is exactly the R1 deferral/re-evaluation rule: *"At the deferral time, the
    rule re-evaluates and may start a new episode."* Bed 15's R1 is ``met``
    20:35-20:40, suppressed 20:45-01:25, then ``met`` again from 01:30, so it
    produces **two** R1 episodes (prompts at 20:35 and 01:30), not one
    (R1-episodes; ``r1.r1_prompt_times``; ``data/SCENARIOS.md`` bed 15).

    Each episode carries, as known over its run:

    * ``time_raised`` -- the first grid time of the run (when the prompt is
      raised);
    * ``time_ended`` -- the first grid time *after* the run (when the rule
      stopped being ``met`` / the alert cleared), or ``None`` if the run reaches
      the end of the night window (still open);
    * ``start_idx`` / ``end_idx`` -- the inclusive grid-index bounds of the run,
      so the viewer can filter episodes active/known at a selected clock index
      ``t`` (future episodes with ``start_idx`` beyond ``t`` are not yet raised;
      resolved episodes with ``end_idx`` before ``t`` are closed);
    * ``workflow_state`` -- the workflow state **read from the cell at
      ``end_idx``** (the latest known state *within* the run), never a single
      state frozen at the first ``met`` cell. Bed 10's R3 episode is
      ``notified`` at 01:10 and ``acknowledged`` after the 01:12 acknowledgement,
      so by the last ``met`` cell of the run (01:50) its episode
      ``workflow_state`` is ``acknowledged`` -- not stuck at ``notified``. The
      episode's run ends at 01:50; the ``resolved`` workflow state (and the
      ``not_met`` evaluation state) first appears at 01:55, the cell at
      ``time_ended``, which the viewer reads to show the episode has been closed
      by the valid check known at 01:52/visible 01:55 (AC-WORKFLOW-1,
      AC-WORKFLOW-2; ``data/SCENARIOS.md`` bed 10). The workflow is presentation
      only -- it never changes the evaluation state and acknowledging never
      closes an episode (AC-DEF-2).

    Both lists are returned pre-sorted by **time raised**, never by severity or
    urgency (AC-ORDER-2). The sort key also includes the bed, encounter, rule
    and start index so two episodes raised at the same instant have a single
    deterministic order (determinism; AC-GEN-7).

    A feed alert is its own inbox item (``rule`` ``"feed_alert"``), never folded
    into silence (AC-FAIL-1, AC-FID-3). The dataset has no routing failure, so
    none is emitted here; a routing-failure item is exercised separately via a
    synthetic model in a later task (tasks.md task 5).
    """

    doctor: list[dict] = []
    nurse: list[dict] = []

    # Stable, deterministic encounter order (the dataset's own order), so the
    # pre-sort by time raised is reproducible.
    for enc in ds.encounters:
        cells = results[enc.encounter]
        bed = enc.bed
        n = len(cells)

        def _episode(
            rule: str, start_idx: int, end_idx: int, workflow: str
        ) -> dict:
            # ``time_ended`` is the first grid time *after* the run, or None when
            # the run is still open at the end of the window.
            ended = _iso(cells[end_idx + 1].t) if end_idx + 1 < n else None
            return {
                "bed": bed,
                "encounter": enc.encounter,
                "rule": rule,
                "time_raised": _iso(cells[start_idx].t),
                "time_ended": ended,
                "start_idx": start_idx,
                "end_idx": end_idx,
                "workflow_state": workflow,
            }

        # --- per-rule "met" episodes (one per contiguous met-run) ----------
        for group, rule_ids in EPISODE_GROUPS:
            # Read the state word only; no rule logic (AC-GEN-6).
            met_flags = [
                any(
                    cell.results.get(r) is not None
                    and cell.results[r].state.value == "met"
                    for r in rule_ids
                )
                for cell in cells
            ]
            for start_idx, end_idx in _runs_of(met_flags):
                # Workflow state as known at the *end* of the run (the latest
                # state), read from the cell -- not frozen at the first cell.
                ws = next(
                    (cells[end_idx].workflow_states[r] for r in rule_ids
                     if r in cells[end_idx].workflow_states),
                    None,
                )
                workflow = ws.value if ws is not None else ""
                item = _episode(group, start_idx, end_idx, workflow)
                if group in NURSE_RULES:
                    nurse.append(item)
                else:
                    doctor.append(item)

        # --- feed alert inbox items (nurse), one per contiguous alert run --
        feed_flags = [cell.feed_alert for cell in cells]
        for start_idx, end_idx in _runs_of(feed_flags):
            nurse.append(_episode("feed_alert", start_idx, end_idx, ""))

    def _sort_key(item: dict) -> tuple:
        # Time raised first (ISO strings sort chronologically), then stable
        # tie-breakers so equal times still order deterministically.
        return (
            item["time_raised"],
            item["bed"],
            item["encounter"],
            item["rule"],
            item["start_idx"],
        )

    doctor.sort(key=_sort_key)
    nurse.sort(key=_sort_key)
    return doctor, nurse


def build_board_model(
    ds: Dataset,
    results: Optional[dict[str, list[GridCell]]] = None,
) -> dict:
    """Serialise the engine's ward evaluation into a JSON-safe board model.

    Calls :func:`sanad.evaluate.evaluate_ward` over the night window (or uses a
    caller-supplied ``results`` map, e.g. a synthetic one in a test) and turns
    the precomputed per-grid-point :class:`~sanad.model.GridCell` results into
    one plain ``dict`` with two parts (design.md Section 3):

    * **static copy** -- the verbatim UI strings (:func:`build_static_copy`);
    * **dynamic results** --

      - ``grid_times``: the ordered list of 5-minute grid ISO times (the shared
        grid every encounter is evaluated on), so the viewer steps a fixed index
        (AC-GEN-8);
      - ``beds``: a list of ``{bed, encounters: {encounter: {cells: [...]}}}``,
        ordered by integer **bed number** (AC-ORDER-1); bed 13 carries both of
        its encounters (AC-S2-grid);
      - ``episodes``: the doctor's open-episode list; and ``inbox``: the nurse's
        inbox items -- both pre-sorted by **time raised** (AC-ORDER-2).

    The board **never recomputes a rule**: each cell's state / reason / message
    is copied verbatim from the ``GridCell`` (AC-GEN-6, AC-FID-1). Enums are
    serialised to their verbatim ``.value`` words (AC-STATE-2); times to ISO
    ``+01:00`` strings; everything else is a plain JSON scalar/list/dict.

    Pure and deterministic: identical inputs give an identical model (no
    wall-clock, no RNG, no dict/set/filesystem-order dependence; AC-GEN-7).
    """

    if results is None:
        results = evaluate.evaluate_ward(ds)

    # grid_times: the shared 5-minute grid. Every encounter is evaluated on the
    # same grid, so take it from any encounter's cell list (or [] if empty).
    grid_times: list[str] = []
    for cells in results.values():
        grid_times = [_iso(cell.t) for cell in cells]
        break

    # beds ordered by integer bed number; bed 13 carries both encounters.
    # Group encounters by bed from the dataset (the single source of which
    # encounter belongs to which bed), then order beds numerically and
    # encounters by their id so the structure is deterministic.
    by_bed: dict[int, list[str]] = {}
    for enc in ds.encounters:
        by_bed.setdefault(enc.bed, []).append(enc.encounter)

    beds: list[dict] = []
    for bed in sorted(by_bed):
        encounters_for_bed: dict[str, dict] = {}
        for encounter in sorted(by_bed[bed]):
            cells = results.get(encounter, [])
            # The occupant flag is derived once per encounter from the same
            # admission/discharge bounds R3 uses (``r3.is_active``), as known at
            # each cell's time -- so bed 13's two encounters each know when they
            # are the one in the bed (AC-S2-grid). Single-occupant beds are
            # active across their whole evaluated window.
            r3_ctx = r3.context_for(ds, encounter)
            encounters_for_bed[encounter] = {
                "cells": [
                    _cell_to_dict(cell, r3.is_active(r3_ctx, cell.t))
                    for cell in cells
                ],
            }
        beds.append({"bed": bed, "encounters": encounters_for_bed})

    episodes, inbox = _episodes_from_ward(ds, results)

    model: dict = {
        "static": build_static_copy(),
        "grid_times": grid_times,
        "beds": beds,
        "episodes": episodes,
        "inbox": inbox,
    }
    return model


# ==========================================================================
# Layer 2: render_html -- the board model -> one self-contained HTML string.
# ==========================================================================
#
# design.md Section 4: the *skeleton* (the persistent-label banner, the five
# ``data-screen`` containers, one ``data-bed`` tile per bed, the clock buttons
# and the fixed action picklists) is rendered by Python, so structure, controls
# and ordering are testable from the HTML string without executing any JS.
#
# Task 3 fixes the offline and no-input guarantees:
#
# * self-contained -- inline CSS and inline vanilla JS only; no ``<link>``, no
#   ``<script src>``, no external URL, CDN, font or image (AC-GEN-3);
# * no network -- no ``fetch(``, ``XMLHttpRequest``, ``WebSocket`` and no
#   ``http://`` / ``https://`` anywhere in the file (AC-GEN-4);
# * no persistence -- no ``localStorage``, ``sessionStorage``, ``document.cookie``
#   or ``indexedDB`` (AC-GEN-5);
# * no data entry -- no ``<textarea>``, no file picker; every ``<input>`` is a
#   ``type="button"`` control and every ``<select>`` offers only fixed
#   ``<option>``s (AC-NOINPUT-1, AC-NOINPUT-2);
# * the board data is embedded as canonical JSON in a
#   ``<script type="application/json" id="board-data">`` block with ``<``, ``>``
#   and ``&`` escaped so no data value can close the tag or inject markup
#   (design.md §3d, AC-GEN-8).
#
# The viewer JS (the index step, show/hide, ``textContent`` fill and simulated
# workflow overlay) and the final palette/wording are filled by tasks 4 and 5;
# task 3 ships a minimal, offline-safe inline script so the single file is
# self-contained and the structural tests have something to assert against.


def _escape_text(value: str) -> str:
    """Escape ``&``, ``<`` and ``>`` for HTML text / attribute content.

    ``&`` first so an already-escaped entity is not double-escaped out of order.
    Used for every value the Python skeleton writes into the markup, so no
    static-copy or bed-label string can inject markup (design.md §3d).
    """

    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _embed_board_data(model: dict) -> str:
    """Serialise the model to canonical JSON and escape it for embedding.

    The JSON is canonical -- ``sort_keys=True``, compact separators,
    ``ensure_ascii=False`` so the ``·`` / ``–`` characters stay as UTF-8, which
    the document declares (``<meta charset="utf-8">``) and :func:`main` writes
    (AC-GEN-7 determinism). ``<``, ``>`` and ``&`` are then escaped to
    ``&lt;`` / ``&gt;`` / ``&amp;`` so the embedded text contains no raw ``<``,
    ``>`` or ``&`` and nothing in the data can close the ``<script>`` tag or
    inject markup (design.md §3d). The viewer reverses the escaping before
    ``JSON.parse`` (task 5).
    """

    canonical = json.dumps(
        model, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    )
    return _escape_text(canonical)


def _render_screen(screen_id: str, title: str, body: str) -> str:
    """One ``data-screen`` container with a stable id (design.md Section 4)."""

    return (
        f'<section class="screen" data-screen="{screen_id}" hidden>'
        f'<h2 class="screen-title">{_escape_text(title)}</h2>'
        f"{body}"
        f"</section>"
    )


def _render_bed_tile(bed: int, encounters: Sequence[str]) -> str:
    """One ``data-bed`` tile placeholder per physical bed (design.md §4).

    The tile carries its bed number and the ids of the encounter(s) that may
    occupy it (bed 13 carries two); the viewer fills the per-rule chips, the
    silence text and the feed chip from the embedded cell at the selected clock
    index (task 5). Task 3 only guarantees the tile element exists, once per
    bed, in bed-number order (AC-S2-grid, AC-ORDER-1).
    """

    enc_attr = _escape_text(",".join(encounters))
    return (
        f'<li class="bed-tile" data-bed="{bed}" data-encounters="{enc_attr}">'
        f'<span class="bed-number">{bed}</span>'
        f'<span class="bed-body" data-bed-body></span>'
        f'<span class="bed-feed-chip" data-feed-chip hidden></span>'
        f"</li>"
    )


def _render_clock_controls() -> str:
    """The simulated-clock controls -- fixed buttons only (AC-NOINPUT-1/2).

    Stepping the clock is the only "input"; it is two ``<input type="button">``
    controls (never a text/number/range field), plus a read-only display the
    viewer writes with ``textContent`` (task 5).

    The same control block is rendered on every working screen (Screens 2-5),
    so the clock is visible and usable wherever the user is, not only on the
    ward board (task 10; UI_FLOW rule 2 "Every screen shows data as known at the
    selected time"). The viewer wires **all** ``data-clock-prev`` /
    ``data-clock-next`` controls to the single integer clock index and writes
    **every** ``data-clock-display`` with ``textContent``, so stepping the clock
    on any screen moves the whole board together.
    """

    return (
        '<div class="clock" data-clock>'
        '<input type="button" data-clock-prev value="&larr; 5 min">'
        '<span class="clock-display" data-clock-display></span>'
        '<input type="button" data-clock-next value="5 min &rarr;">'
        "</div>"
    )


def _render_start_nav() -> str:
    """A fixed "Start" button that returns to Screen 1 (task 10).

    Rendered on Screens 2-5 so the persistent label and the intended-use /
    verification wording of Screen 1 are always one click away (UI_FLOW Screen 1
    "the user must read what Sanad is not"). A fixed ``<input type="button">``
    only -- no free text, no navigation that enters data (AC-NOINPUT-1).
    """

    return (
        '<div class="nav" data-nav>'
        '<input type="button" data-nav-start value="Start">'
        "</div>"
    )


def _render_action_controls() -> str:
    """The simulated workflow actions -- fixed buttons and fixed picklists.

    Acknowledge / Assessed / Deferred are ``<input type="button">`` controls;
    reason, owner and deferral time are ``<select>`` picklists whose only
    ``<option>``s are fixed here (no free text anywhere; AC-NOINPUT-2,
    AC-S5-assess). The viewer (task 5) reads the chosen option and sets a
    workflow chip in memory only -- it never changes an evaluation state.
    """

    reasons = ("awaiting review", "clinical hold", "handover")
    owners = ("on-call doctor", "night nurse", "charge nurse")
    times = ("00:30", "01:00", "01:30", "02:00")

    def _select(name: str, options: Sequence[str]) -> str:
        opts = "".join(
            f'<option value="{_escape_text(o)}">{_escape_text(o)}</option>'
            for o in options
        )
        return (
            f'<label class="picklist">{_escape_text(name)}'
            f'<select data-action-{name}>{opts}</select>'
            f"</label>"
        )

    return (
        '<div class="actions" data-actions>'
        '<input type="button" data-action-acknowledge value="Acknowledge (simulated)">'
        '<input type="button" data-action-assessed value="Assessed (simulated)">'
        '<input type="button" data-action-deferred value="Deferred (simulated)">'
        f'{_select("reason", reasons)}'
        f'{_select("owner", owners)}'
        f'{_select("until", times)}'
        "</div>"
    )


def _render_threshold_label(static: dict) -> str:
    """The R2a/R2b threshold label (AC-S3-threshold-label, AC-S5-r2).

    Rendered verbatim on the bed-detail and review screens so the viewer never
    has to synthesise it: "DESIGN demo values, not emergency alarm thresholds".
    """

    return (
        '<p class="threshold-label" data-threshold-label>'
        f'{_escape_text(static["threshold_label"])}</p>'
    )


def _render_criteria_sources(static: dict) -> str:
    """The R1 criteria list (0, a-f, the 120-min duration) with source lines.

    Each criterion's label and its ``docs/EVIDENCE.md`` source line are rendered
    verbatim on Screen 5 (AC-S5-r1 as amended by D28: labels and sources only,
    no per-criterion state or data). The strings come from the static copy, so
    the drift test anchors them to the signed baseline.
    """

    items = "".join(
        (
            f'<li class="criterion" data-criterion="{_escape_text(c["id"])}">'
            f'<span class="criterion-id">{_escape_text(c["id"])}</span>'
            f'<span class="criterion-label">{_escape_text(c["label"])}</span>'
            f'<span class="criterion-source">{_escape_text(c["source"])}</span>'
            f"</li>"
        )
        for c in static["criteria_sources"]
    )
    return f'<ul class="criteria-sources" data-criteria-sources>{items}</ul>'


# The inline viewer (design.md Section 4; tasks.md task 5). It is deliberately
# small and does only four things:
#
#   * holds the clock index (an integer) and the current screen;
#   * shows / hides the ``data-screen`` containers;
#   * fills text with ``textContent`` (never ``innerHTML``) from the embedded
#     values at the selected index -- it reads the precomputed ``GridCell``
#     fields by key, it never computes, re-implements or compares an evaluation
#     state (AC-GEN-6); and
#   * keeps simulated actions (Acknowledge / Assessed / Deferred) in an in-memory
#     object keyed by episode id, held in memory only (reset on reload) and only
#     ever setting a displayed workflow chip -- never the evaluation state
#     (AC-GEN-5, AC-S5-assess, AC-WORKFLOW-2, D28).
#
# Safety constraints the task-5 tests assert against the *source* (the JS is not
# executed by the stdlib-only suite, design.md §6):
#
#   * no ``innerHTML`` anywhere -- text is written with ``textContent`` and nodes
#     are built with ``createElement`` / ``appendChild`` / ``createTextNode``;
#   * no state-word literal (``"met"``, ``"unknown"`` …) is ever compared against
#     -- the viewer only renders the embedded word verbatim and *builds* a CSS
#     class from it (``"state-" + result.state``), so a typo could never make the
#     page disagree with the engine and no safe/green branch can exist (AC-GEN-6,
#     AC-STATE-1, AC-SILENCE-2). List filtering uses ``start_idx``/``end_idx``,
#     occupancy uses ``active``, and failures use ``feed_alert`` -- never a state
#     word.
#
# The rule ids are read from the embedded data's cells, so no rule name is
# hard-coded as a comparison either.
_VIEWER_JS = """\
(function () {
  "use strict";

  var raw = document.getElementById("board-data");
  if (!raw) { return; }
  // textContent already holds the unescaped JSON (the &lt;/&gt;/&amp; the
  // Python side wrote are decoded by the parser into real characters when the
  // element's text is read). Parse it; never eval, never fetch.
  var model = JSON.parse(raw.textContent);

  var grid = model.grid_times || [];
  var beds = model.beds || [];
  var episodes = model.episodes || [];
  var inbox = model.inbox || [];
  var staticCopy = model.static || {};

  // The simulated-clock index. An integer step over the embedded grid only.
  var clockIndex = 0;
  if (grid.length === 0) { clockIndex = -1; }

  // Simulated workflow overlay: episode id -> chip text. In memory only; a
  // reload drops it (no storage API is touched anywhere). It only ever holds a
  // displayed chip string; it never influences an evaluation state.
  var simulated = {};
  // The role the user picked (for the inbox routing display); the embedded
  // lists are already split into the doctor's episodes and the nurse's inbox.
  var currentBed = null;
  var currentEpisodeId = null;

  // --- tiny DOM helpers (textContent + createElement only) ---------------

  function setText(el, value) {
    if (el) { el.textContent = value == null ? "" : String(value); }
  }

  function clear(el) {
    if (!el) { return; }
    while (el.firstChild) { el.removeChild(el.firstChild); }
  }

  function make(tag, className) {
    var el = document.createElement(tag);
    if (className) { el.className = className; }
    return el;
  }

  function withText(tag, className, value) {
    var el = make(tag, className);
    el.appendChild(document.createTextNode(value == null ? "" : String(value)));
    return el;
  }

  function q(sel) { return document.querySelector(sel); }
  function qa(sel) { return document.querySelectorAll(sel); }

  // --- readable times (F7): HH:MM, with the date only on the clock -------

  // Every embedded time is a full ISO string with the dataset offset (a
  // date, then "T", then HH:MM:SS, then "+01:00"). No raw ISO string may
  // reach the screen (F7). These helpers read the fixed ISO layout by
  // position -- no Date parsing, so no local-timezone shift can move a minute
  // -- and return the wall-clock the dataset recorded.
  var MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

  // HH:MM only -- used in lists, bed detail and R3 detail, where the night is
  // understood and only the time of day is needed.
  function fmtTime(iso) {
    if (!iso) { return ""; }
    return String(iso).slice(11, 16);
  }

  // "D Mon" (e.g. "21 Nov") from an ISO string, for the clock and wherever the
  // day changes. Leading zero on the day is dropped so it reads "20 Nov".
  function fmtDate(iso) {
    if (!iso) { return ""; }
    var s = String(iso);
    var month = parseInt(s.slice(5, 7), 10);
    var day = parseInt(s.slice(8, 10), 10);
    var name = MONTHS[month - 1] || s.slice(5, 7);
    return day + " " + name;
  }

  // The clock display carries the date and the time ("21 Nov 01:10"), so the
  // user always knows which night-hour is selected (F7).
  function fmtClock(iso) {
    if (!iso) { return ""; }
    return fmtDate(iso) + " " + fmtTime(iso);
  }

  // The day part (YYYY-MM-DD) of an ISO string, to detect a day change.
  function dayOf(iso) { return iso ? String(iso).slice(0, 10) : ""; }

  // --- screen show / hide -------------------------------------------------

  var screens = qa("[data-screen]");
  function show(id) {
    for (var i = 0; i < screens.length; i += 1) {
      screens[i].hidden = screens[i].getAttribute("data-screen") !== id;
    }
  }

  // --- embedded-data lookups (read by key only; no rule logic) -----------

  // The cell shown for a bed at the current index is the active occupant's
  // cell. Occupancy is the embedded boolean ``active`` -- not a state word.
  function activeCellForBed(bed, i) {
    var encs = bed.encounters || {};
    var ids = Object.keys(encs);
    for (var k = 0; k < ids.length; k += 1) {
      var cells = encs[ids[k]].cells || [];
      var cell = cells[i];
      if (cell && cell.active) { return { encounter: ids[k], cell: cell }; }
    }
    return null;
  }

  function cellFor(bedNumber, encounter, i) {
    for (var b = 0; b < beds.length; b += 1) {
      if (beds[b].bed === bedNumber) {
        var enc = (beds[b].encounters || {})[encounter];
        if (enc && enc.cells) { return enc.cells[i] || null; }
      }
    }
    return null;
  }

  // The rule ids a cell carries, in the embedded order.
  function ruleIdsOf(cell) {
    return cell && cell.results ? Object.keys(cell.results) : [];
  }

  function readableDetail(detail) {
    return String(detail).replace(
      /[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}[+-][0-9]{2}:[0-9]{2}/g,
      function (iso) { return fmtTime(iso); }
    );
  }

  // --- state chip (renders the embedded word verbatim) --------------------

  // Build a chip for one rule result. The CSS class is *built from* the state
  // value (``state-`` + the word); the word is never compared to a literal, so
  // the chip always shows exactly what the engine produced (AC-GEN-6,
  // AC-STATE-1..7). The reason code is shown verbatim **unless** the embedded
  // ``show_reason`` flag is false -- the Python side clears it for ``met``
  // chips only, so a met chip carries no engine-default reason while every
  // other chip keeps its reason code (F6, D27 answer 2). The approved message
  // (if any) is shown unless the surrounding static detail already carries it;
  // engine detail is preserved except that embedded ISO times read as HH:MM.
  function ruleChip(ruleId, result, showMessage) {
    var chip = make("div", "chip state-" + result.state);
    chip.setAttribute("data-rule", ruleId);
    chip.setAttribute("data-state", result.state);
    chip.appendChild(withText("span", "rule-id", ruleId));
    chip.appendChild(withText("span", "state-word", result.state));
    if (result.show_reason) {
      chip.appendChild(withText("span", "reason-code", result.reason));
    }
    if (result.detail) {
      chip.appendChild(withText("span", "detail", readableDetail(result.detail)));
    }
    if (result.message && showMessage !== false) {
      chip.appendChild(withText("span", "approved-message", result.message));
    }
    return chip;
  }

  // --- tiles (Screen 2) ---------------------------------------------------

  function renderTiles() {
    var i = clockIndex;
    var anyFeed = false;
    var feedBeds = [];
    var tiles = qa("[data-bed]");
    for (var t = 0; t < tiles.length; t += 1) {
      var tile = tiles[t];
      var bedNumber = parseInt(tile.getAttribute("data-bed"), 10);
      var bed = null;
      for (var b = 0; b < beds.length; b += 1) {
        if (beds[b].bed === bedNumber) { bed = beds[b]; break; }
      }
      var body = tile.querySelector("[data-bed-body]");
      var feedChip = tile.querySelector("[data-feed-chip]");
      clear(body);
      if (feedChip) { feedChip.hidden = true; }
      if (!bed || i < 0) { continue; }
      var found = activeCellForBed(bed, i);
      if (!found) {
        // No encounter is in the bed at this time: show it empty, never a
        // silence or safe state.
        body.appendChild(withText("span", "bed-empty", "\\u2014"));
        continue;
      }
      var cell = found.cell;
      var ruleIds = ruleIdsOf(cell);
      for (var r = 0; r < ruleIds.length; r += 1) {
        body.appendChild(ruleChip(ruleIds[r], cell.results[ruleIds[r]]));
      }
      // Silence text, verbatim from the embedded cell, when nothing is met.
      if (cell.display_text) {
        body.appendChild(withText("p", "silence-text", cell.display_text));
      }
      // Per-tile feed chip when the cell's feed_alert is true, so a stale bed
      // never reads as silence alone (AC-FAIL-1, D06).
      if (cell.feed_alert) {
        anyFeed = true;
        feedBeds.push(bedNumber);
        if (feedChip) {
          feedChip.hidden = false;
          setText(feedChip, staticCopy.feed_alert_label || "feed alert");
        }
      }
    }
    // The banner above the grid shows the static feed-alert label plus the
    // affected bed numbers while any active cell has a feed alert, and is empty
    // and hidden otherwise (F2, AC-S2-feedbanner, AC-FAIL-1). The [hidden]
    // CSS rule is the single switch that removes its layout box (F1).
    var banner = q("[data-feed-banner]");
    if (banner) {
      if (anyFeed) {
        var label = staticCopy.feed_alert_label || "feed alert";
        setText(banner, label + " \\u00b7 beds " + feedBeds.join(", "));
        banner.hidden = false;
      } else {
        setText(banner, "");
        banner.hidden = true;
      }
    }
  }

  // --- episode / inbox lists (filtered by the clock) ----------------------

  // An item is "raised" once the clock reaches its start_idx; it is still open
  // while the clock has not passed its end_idx (for every group). The viewer
  // reads the workflow state from the cell at the current index, not frozen.
  function itemIsRaised(item, i) { return item.start_idx <= i; }

  function itemIsOpen(item, i) {
    return item.start_idx <= i && i <= item.end_idx;
  }

  // The workflow chip text shown for an item: the simulated overlay (if the
  // user acted on it) wins for display; otherwise the embedded workflow state
  // read from the item's cell at the current index.
  function workflowChipText(item, i) {
    var id = item.encounter + ":" + item.rule + ":" + item.start_idx;
    if (Object.prototype.hasOwnProperty.call(simulated, id)) {
      return simulated[id];
    }
    var cell = cellFor(item.bed, item.encounter, i);
    if (cell && cell.workflow_states) {
      // Read the rule's workflow word by key; render it verbatim.
      var ids = Object.keys(cell.workflow_states);
      for (var k = 0; k < ids.length; k += 1) {
        if (item.rule.indexOf(ids[k]) === 0 || ids[k] === item.rule) {
          return cell.workflow_states[ids[k]];
        }
      }
    }
    return item.workflow_state || "";
  }

  function episodeId(item) {
    return item.encounter + ":" + item.rule + ":" + item.start_idx;
  }

  function renderList(container, items, onOpen, openOnly) {
    if (!container) { return; }
    clear(container);
    var i = clockIndex;
    var lastDay = "";
    for (var n = 0; n < items.length; n += 1) {
      var item = items[n];
      var shouldShow = openOnly ? itemIsOpen(item, i) : itemIsRaised(item, i);
      if (!shouldShow) { continue; }  // respect the clock and, for doctors, open runs
      var li = make("li", "list-item");
      li.setAttribute("data-episode-id", episodeId(item));
      li.appendChild(withText("span", "item-bed", "Bed " + item.bed));
      li.appendChild(withText("span", "item-encounter", item.encounter));
      li.appendChild(withText("span", "item-rule", item.rule));
      // Time raised as HH:MM; the date is prefixed only when the day changes
      // from the previous listed item (or on the first item), so a list that
      // straddles midnight stays readable without repeating the date (F7).
      var day = dayOf(item.time_raised);
      var shown = day !== lastDay
        ? fmtDate(item.time_raised) + " " + fmtTime(item.time_raised)
        : fmtTime(item.time_raised);
      lastDay = day;
      li.appendChild(withText("span", "item-time", shown));
      li.appendChild(
        withText("span", "item-workflow", workflowChipText(item, i))
      );
      if (onOpen) {
        (function (captured) {
          li.addEventListener("click", function () { onOpen(captured); });
        })(item);
      }
      container.appendChild(li);
    }
  }

  // Count of open nurse items at the clock (AC-S2-inbox-counter).
  function inboxOpenCount() {
    var i = clockIndex;
    var c = 0;
    for (var n = 0; n < inbox.length; n += 1) {
      if (itemIsOpen(inbox[n], i)) { c += 1; }
    }
    return c;
  }

  // --- bed detail (Screen 3) ---------------------------------------------

  function selectedInboxItem() {
    if (!currentEpisodeId) { return null; }
    for (var n = 0; n < inbox.length; n += 1) {
      if (episodeId(inbox[n]) === currentEpisodeId) { return inbox[n]; }
    }
    return null;
  }

  // Opening Screen 3 selects the active encounter's open R3 item. Both the
  // inbox and tile routes therefore act on the same episode, rather than
  // leaving applySimulated with no current episode (AC-S3-ack).
  function selectBed(bedNumber) {
    currentBed = bedNumber;
    currentEpisodeId = null;
    for (var b = 0; b < beds.length; b += 1) {
      if (beds[b].bed !== bedNumber) { continue; }
      var found = activeCellForBed(beds[b], clockIndex);
      if (!found) { break; }
      for (var n = 0; n < inbox.length; n += 1) {
        var item = inbox[n];
        if (item.bed === bedNumber && item.encounter === found.encounter &&
            item.rule === "R3" && itemIsOpen(item, clockIndex)) {
          currentEpisodeId = episodeId(item);
          break;
        }
      }
      break;
    }
    show("bed");
    renderBedDetail();
  }

  function renderBedDetail() {
    var holder = q("[data-bed-detail]");
    if (!holder || currentBed == null) { return; }
    clear(holder);
    var i = clockIndex;
    var bed = null;
    for (var b = 0; b < beds.length; b += 1) {
      if (beds[b].bed === currentBed) { bed = beds[b]; break; }
    }
    if (!bed) { return; }
    holder.appendChild(withText("h3", "bed-detail-title", "Bed " + currentBed));
    var found = activeCellForBed(bed, i);
    if (!found) {
      holder.appendChild(withText("p", "bed-empty", "\\u2014"));
      return;
    }
    var cell = found.cell;
    var ruleIds = ruleIdsOf(cell);
    for (var r = 0; r < ruleIds.length; r += 1) {
      var row = make("div", "rule-row");
      row.appendChild(ruleChip(ruleIds[r], cell.results[ruleIds[r]]));
      // Workflow beside, never instead of, the evaluation state (AC-WORKFLOW-1).
      var workflow = cell.workflow_states && cell.workflow_states[ruleIds[r]];
      var selected = selectedInboxItem();
      if (selected && selected.bed === currentBed &&
          selected.encounter === found.encounter && selected.rule === ruleIds[r]) {
        workflow = workflowChipText(selected, i);
      }
      if (workflow) {
        row.appendChild(withText("span", "workflow-beside", workflow));
      }
      holder.appendChild(row);
    }
    if (cell.display_text) {
      holder.appendChild(withText("p", "silence-text", cell.display_text));
    }
    if (cell.feed_alert) {
      holder.appendChild(
        withText("p", "feed-alert", staticCopy.feed_alert_label || "feed alert")
      );
    }
  }

  // --- review detail (Screen 5): the selected episode at the clock -------

  // Find the doctor's episode whose id matches the current selection.
  function selectedEpisode() {
    if (!currentEpisodeId) { return null; }
    for (var n = 0; n < episodes.length; n += 1) {
      if (episodeId(episodes[n]) === currentEpisodeId) { return episodes[n]; }
    }
    return null;
  }

  // Render the detail for the *selected* episode (task 10). With no episode
  // selected both sub-panels stay hidden, so Screen 5 shows the list only.
  // An R1 episode shows the approved R1 wording and the criteria list (the
  // ``data-r1-detail`` panel, already in the markup verbatim). An R2 episode
  // shows the R2a/R2b state chips, and -- only when the selected cell carries
  // the combined message (R2a and R2b both met) -- the combined message and
  // threshold label; any other R2 item shows just the chips (rule name, state
  // word, reason code), never the R1 text or criteria (D27 answer 1, AC-S5-r1,
  // AC-S5-r2, D28). The viewer only toggles [hidden] and fills the chips; all
  // wording stays the verbatim markup (AC-GEN-6).
  function renderReviewDetail() {
    var r1Panel = q("[data-r1-detail]");
    var r1Chips = q("[data-r1-chips]");
    var r2Panel = q("[data-r2-detail]");
    var r2Chips = q("[data-r2-chips]");
    var r2Combined = q("[data-r2-combined]");
    if (r1Panel) { r1Panel.hidden = true; }
    if (r2Panel) { r2Panel.hidden = true; }
    if (r1Chips) { clear(r1Chips); }
    if (r2Chips) { clear(r2Chips); }
    var item = selectedEpisode();
    if (!item) { return; }  // no episode selected -> list only
    var cell = cellFor(item.bed, item.encounter, clockIndex);
    // The group name is the episode's ``rule`` ("R1" or "R2"); it is matched by
    // equality against the embedded value only, never a state-word comparison.
    if (item.rule === "R1") {
      if (r1Panel) { r1Panel.hidden = false; }
      if (r1Chips && cell && cell.results && cell.results[item.rule]) {
        // The approved R1 sentence already follows in the static panel; the
        // current state/reason/detail chip must not repeat that sentence.
        r1Chips.appendChild(ruleChip(item.rule, cell.results[item.rule], false));
      }
      return;
    }
    // R2 (or any other non-R1 group): show the chips for this episode's cell at
    // the clock. The combined message is shown only when the cell carries it.
    if (r2Panel) { r2Panel.hidden = false; }
    if (r2Chips && cell && cell.results) {
      var ruleIds = ruleIdsOf(cell);
      for (var r = 0; r < ruleIds.length; r += 1) {
        // Only the R2 rules belong on this doctor item; a rule id is on the R2
        // item when the episode's ``rule`` is its prefix ("R2" matches "R2a"
        // and "R2b"). Built from the embedded ids; no state-word logic.
        if (ruleIds[r].indexOf(item.rule) === 0) {
          r2Chips.appendChild(ruleChip(ruleIds[r], cell.results[ruleIds[r]]));
        }
      }
    }
    // The combined message (and its threshold label) only when both are met,
    // which the engine signals by setting the cell's combined_message.
    if (r2Combined) {
      r2Combined.hidden = !(cell && cell.combined_message);
    }
  }

  // --- the clock ----------------------------------------------------------

  // The clock controls are repeated on Screens 2-5 (task 10), so write EVERY
  // ``data-clock-display`` with textContent -- the whole board shares one
  // integer index, so stepping on any screen moves them all together.
  function renderClock() {
    var disps = qa("[data-clock-display]");
    for (var k = 0; k < disps.length; k += 1) {
      setText(disps[k], clockIndex >= 0 ? fmtClock(grid[clockIndex]) : "");
    }
  }

  // The inbox counter is a button reading "Inbox: N open (simulated)" that the
  // user clicks to open Screen 4 (task 10, AC-S2-inbox-counter, AC-S2-nav).
  // N is the count of open nurse items at the clock; the full label text is
  // written on the button's value with no free text anywhere.
  function renderInboxCounter() {
    var el = q("[data-inbox-counter]");
    if (el) {
      el.value = "Inbox: " + inboxOpenCount() + " open (simulated)";
    }
  }

  function renderAll() {
    renderClock();
    renderTiles();
    renderInboxCounter();
    renderList(q("[data-inbox-list]"), inbox, function (item) {
      selectBed(item.bed);
    });
    renderList(q("[data-episode-list]"), episodes, function (item) {
      currentEpisodeId = episodeId(item);
      show("review");
      renderReviewDetail();
    }, true);
    renderBedDetail();
    renderReviewDetail();
  }

  function step(delta) {
    if (clockIndex < 0) { return; }
    clockIndex += delta;
    if (clockIndex < 0) { clockIndex = 0; }
    if (clockIndex > grid.length - 1) { clockIndex = grid.length - 1; }
    renderAll();
  }

  // --- simulated actions (workflow chip only) -----------------------------

  // Set the displayed workflow chip for the current episode to one of the fixed
  // overlay words. This writes to the in-memory overlay only; it never changes
  // an evaluation state, never re-evaluates and never picks a different cell
  // (AC-S5-assess, AC-WORKFLOW-2, D28).
  function selectValue(sel) {
    return sel && sel.options[sel.selectedIndex]
      ? sel.options[sel.selectedIndex].value : "";
  }

  function applySimulated(kind) {
    if (!currentEpisodeId) { return; }
    var text = kind;
    if (kind === "deferred") {
      var owner = selectValue(q("[data-screen]:not([hidden]) [data-action-owner]"));
      var until = selectValue(q("[data-screen]:not([hidden]) [data-action-until]"));
      text = "deferred \\u00b7 " + owner + " \\u00b7 until " + until;
    }
    simulated[currentEpisodeId] = text;
    renderAll();
  }

  // --- wiring -------------------------------------------------------------

  function on(sel, handler) {
    // Wire EVERY match, not just the first: the clock controls, the Start
    // button and the simulated-action controls are repeated across screens
    // (task 10), so a handler must attach to all of them.
    var els = qa(sel);
    for (var k = 0; k < els.length; k += 1) {
      els[k].addEventListener("click", handler);
    }
  }

  // Each bed tile opens Screen 3 (Bed detail) for that bed (task 10,
  // AC-S2-nav). Wired once at setup so no duplicate listeners accumulate.
  function wireTiles() {
    var tiles = qa("[data-bed]");
    for (var t = 0; t < tiles.length; t += 1) {
      (function (tile) {
        var bedNumber = parseInt(tile.getAttribute("data-bed"), 10);
        tile.addEventListener("click", function () {
          selectBed(bedNumber);
        });
      })(tiles[t]);
    }
  }

  on("[data-role-nurse]", function () { show("ward"); renderAll(); });
  on("[data-role-doctor]", function () { show("review"); renderAll(); });
  // Start returns to Screen 1 from any working screen (task 10).
  on("[data-nav-start]", function () { show("start"); });
  // The inbox counter button opens Screen 4 (task 10, AC-S2-nav).
  on("[data-inbox-counter]", function () { show("inbox"); renderAll(); });
  on("[data-clock-prev]", function () { step(-1); });
  on("[data-clock-next]", function () { step(1); });
  on("[data-action-acknowledge]", function () { applySimulated("acknowledged"); });
  on("[data-action-assessed]", function () { applySimulated("assessed"); });
  on("[data-action-deferred]", function () { applySimulated("deferred"); });
  wireTiles();

  // Start on the first screen (Start); the user picks a role from there.
  if (screens.length) { show(screens[0].getAttribute("data-screen")); }
  renderAll();
})();
"""

_STYLE_CSS = """\
:root {
  --bg: #1b1d21;
  --panel: #26292e;
  --ink: #f2f3f5;
  --muted: #b7bcc4;
  --line: #3a3e45;
  --accent: #c7622d;
}
* { box-sizing: border-box; }
/* Hidden means hidden (F1): a single, highest-specificity rule so no later
   class rule (e.g. ``.bed-feed-chip { display: inline-block }``) can give a
   ``[hidden]`` element a layout box. The viewer toggles only the ``hidden``
   attribute, so this is the one switch that shows/hides every optional
   element -- the per-tile feed chip, the feed banner, the review detail
   panels and the screen containers (AC-FAIL-1, AC-S2-feedbanner). */
[hidden] { display: none !important; }
body {
  margin: 0;
  font-family: system-ui, sans-serif;
  background: var(--bg);
  color: var(--ink);
}
.persistent-label {
  position: sticky;
  top: 0;
  z-index: 10;
  padding: 8px 12px;
  background: var(--panel);
  border-bottom: 1px solid var(--line);
  font-weight: 700;
  letter-spacing: 0.04em;
}
.feed-banner {
  padding: 6px 12px;
  background: var(--accent);
  color: var(--ink);
  font-weight: 700;
}
.screen { padding: 12px; }
.screen-title { margin: 0 0 8px; }
.bed-grid {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
  gap: 8px;
}
.bed-tile {
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 6px;
  padding: 8px;
}
.bed-number { font-weight: 700; }
.bed-feed-chip {
  display: inline-block;
  background: var(--accent);
  padding: 2px 6px;
  border-radius: 4px;
}
.clock, .actions { margin: 8px 0; }
.nav { margin: 8px 0; }
.review-detail { margin: 8px 0; }
.picklist { margin-left: 8px; color: var(--muted); }
input[type="button"] {
  background: var(--panel);
  color: var(--ink);
  border: 1px solid var(--line);
  border-radius: 4px;
  padding: 4px 10px;
  cursor: pointer;
}
/* State chips. The chip class is built by the viewer from the embedded state
   word (``state-`` + the value), so colour and treatment follow the engine's
   state verbatim; colour is never the only cue -- every chip also shows the
   state word and the reason code as text (AC-STATE-1, UI_FLOW rule 3). No
   green anywhere (AC-SILENCE-2); treatments use the neutral greys plus the one
   non-green accent only. */
.chip {
  display: block;
  margin: 4px 0;
  padding: 4px 6px;
  border: 1px solid var(--line);
  border-radius: 4px;
  background: var(--panel);
  color: var(--ink);
  /* Long reason codes (``sat_not_recorded``, ``output_not_charted`` …) wrap
     at the tile width instead of being clipped (F9). */
  overflow-wrap: anywhere;
}
.chip .rule-id { font-weight: 700; margin-right: 6px; }
.chip .state-word { font-weight: 700; margin-right: 6px; }
.chip .reason-code { color: var(--muted); overflow-wrap: anywhere; }
.chip .detail, .chip .approved-message { display: block; color: var(--muted); }
/* met: bordered, high-contrast chip (the one non-green accent). */
.chip.state-met {
  border: 2px solid var(--accent);
  color: var(--ink);
  background: var(--panel);
}
.chip.state-met .approved-message { color: var(--ink); }
/* unknown: hatched chip, using the neutral greys only. */
.chip.state-unknown {
  background: repeating-linear-gradient(
    45deg, var(--panel), var(--panel) 6px, var(--line) 6px, var(--line) 12px
  );
}
/* suppressed: paused-icon chip (a textual pause glyph, no colour cue). */
.chip.state-suppressed .state-word::before { content: "\\23f8 "; }
/* not_applicable: the rule name struck through with the excluded pathway. */
.chip.state-not_applicable .rule-id { text-decoration: line-through; }
.silence-text { color: var(--muted); }
.feed-alert, .bed-feed-chip { color: var(--ink); }
.list-item { cursor: pointer; padding: 4px 0; }
.list-item span { margin-right: 8px; }
.workflow-beside, .item-workflow { color: var(--muted); }
.threshold-label { color: var(--muted); font-style: italic; }
.criteria-sources { color: var(--muted); }
"""


def render_html(model: dict) -> str:
    """Render one self-contained offline HTML string from the board model.

    Pure: ``model -> str``; no I/O, no wall-clock, no RNG. The same model
    always renders byte-identical HTML (AC-GEN-7); :func:`main` is the only
    layer that touches the filesystem.

    The document starts with ``<!doctype html>`` and declares
    ``<meta charset="utf-8">``; it inlines all CSS and JS and references no
    external resource (AC-GEN-3). It contains the persistent-label banner, a
    feed-alert banner region, the five ``data-screen`` containers in flow order,
    one ``data-bed`` tile per bed in bed-number order, the fixed clock buttons
    and the fixed action picklists (design.md Section 4). The board model is
    embedded as escaped canonical JSON in ``#board-data`` (AC-GEN-8).
    """

    static = model["static"]
    label = _escape_text(static["persistent_label"])

    # One tile per physical bed, in bed-number order (AC-ORDER-1, AC-S2-grid).
    tiles = "".join(
        _render_bed_tile(bed["bed"], list(bed["encounters"].keys()))
        for bed in model["beds"]
    )
    bed_grid = f'<ul class="bed-grid" data-bed-grid>{tiles}</ul>'

    # The five screens. Bodies are minimal placeholders the viewer fills in
    # later tasks; task 3 guarantees only the container, the controls and the
    # bed grid structure. Screens 2-5 each carry the simulated-clock controls
    # (so the clock is usable wherever the user is; task 10, UI_FLOW rule 2) and
    # a "Start" button back to Screen 1 (task 10, UI_FLOW Screen 1).
    screen_bodies = {
        "start": (
            f'<p class="intended-use" data-intended-use>'
            f'{_escape_text(static["intended_use"])}</p>'
            f'<p class="verification" data-verification>'
            f'{_escape_text(static["verification"])}</p>'
            f'<p class="ward-line" data-ward-line>'
            f'{_escape_text(static["ward_line"])}</p>'
            '<input type="button" data-role-nurse value="Night nurse view">'
            '<input type="button" data-role-doctor value="On-call doctor view">'
        ),
        "ward": (
            _render_start_nav()
            + _render_clock_controls()
            # The inbox counter is a fixed button reading
            # "Inbox: N open (simulated)" that opens the simulated inbox
            # (Screen 4); the viewer writes the N and the full label with
            # textContent and wires the click (task 10, AC-S2-inbox-counter,
            # AC-S2-nav). A button, never a text field (AC-NOINPUT-1).
            + '<input type="button" class="inbox-counter" '
            'data-inbox-counter value="Inbox: 0 open (simulated)">'
            + bed_grid
        ),
        "bed": (
            _render_start_nav()
            + _render_clock_controls()
            + '<div class="bed-detail" data-bed-detail></div>'
            + _render_threshold_label(static)
            + _render_action_controls()
        ),
        "inbox": (
            _render_start_nav()
            + _render_clock_controls()
            + '<ul class="inbox-list" data-inbox-list></ul>'
        ),
        "review": (
            _render_start_nav()
            + _render_clock_controls()
            + '<ul class="episode-list" data-episode-list></ul>'
            # The per-episode detail: the viewer shows exactly one of these
            # sub-containers from the *selected* episode at the clock (task 10),
            # and hides both when no episode is selected, so Screen 5 shows the
            # list only. The verbatim strings are rendered here in the markup
            # (so the wording drift test anchors them to the signed baseline);
            # the viewer only toggles their [hidden] attribute and fills the
            # R2 state chips -- it never synthesises wording (AC-GEN-6).
            + '<div class="review-detail" data-review-detail>'
            # R1 episode: the approved R1 wording plus the criteria list with
            # each criterion's source line (AC-S5-r1, D28). Hidden until an R1
            # episode is selected.
            + '<div class="r1-detail" data-r1-detail hidden>'
            + '<div class="r1-chips" data-r1-chips></div>'
            + '<p class="r1-wording" data-r1-wording>'
            + _escape_text(static["r1_met_text"])
            + "</p>"
            + _render_criteria_sources(static)
            + "</div>"
            # R2 episode: the combined message and the threshold label when R2a
            # and R2b are both met; otherwise the viewer shows only the rule
            # name, state word and reason code chips here (D27 answer 1). Hidden
            # until an R2 episode is selected (AC-S5-r2, D28).
            + '<div class="r2-detail" data-r2-detail hidden>'
            + '<div class="r2-chips" data-r2-chips></div>'
            + '<p class="r2-combined" data-r2-combined>'
            + _escape_text(static["r2_combined_text"])
            + "</p>"
            + _render_threshold_label(static)
            + "</div>"
            + "</div>"
            + _render_action_controls()
        ),
    }
    screens = "".join(
        _render_screen(screen_id, title, screen_bodies[screen_id])
        for screen_id, title in SCREENS
    )

    board_data = _embed_board_data(model)

    # Assemble. Start EXACTLY with ``<!doctype html>`` (AC-GEN test). No
    # external resource is referenced anywhere; the only ``<script>`` tags are
    # the inline JSON data block and the inline viewer.
    return (
        "<!doctype html>\n"
        '<html lang="en">\n'
        "<head>\n"
        '<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        "<title>Sanad ward board (fictional data)</title>\n"
        f"<style>{_STYLE_CSS}</style>\n"
        "</head>\n"
        "<body>\n"
        f'<header class="persistent-label" data-persistent-label>{label}</header>\n'
        '<div class="feed-banner" data-feed-banner hidden></div>\n'
        f'<main class="board">{screens}</main>\n'
        f'<script type="application/json" id="board-data">{board_data}</script>\n'
        f"<script>{_VIEWER_JS}</script>\n"
        "</body>\n"
        "</html>\n"
    )


# ==========================================================================
# Layer 3: main -- the only impure layer (load dataset, write --out).
# ==========================================================================


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Build the board model and write exactly one HTML file to ``--out``.

    The only impure layer (design.md Section 1): it loads the fixed dataset
    (:func:`sanad.loader.load_dataset`), builds the model, renders the HTML and
    writes it as UTF-8 with ``\\n`` newlines to the ``--out`` path, creating the
    parent directory if needed. It makes no network call and reads only the
    local dataset under ``data/ward_seed42/`` (AC-GEN-1..4).

    Run as ``PYTHONPATH=src python3 -m sanad.board --out dist/board.html``
    (``-I`` drops ``PYTHONPATH`` so the package cannot be imported; amended by
    D28). Returns ``0`` on success.
    """

    parser = argparse.ArgumentParser(
        prog="sanad.board",
        description=(
            "Generate the offline Sanad ward board HTML from the fixed "
            "synthetic dataset. Fictional data, simulation, not for clinical "
            "use."
        ),
    )
    parser.add_argument(
        "--out",
        required=True,
        help="path to write the single self-contained HTML file to",
    )
    args = parser.parse_args(argv)

    ds = loader.load_dataset()
    model = build_board_model(ds)
    html = render_html(model)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    # Explicit UTF-8 and ``\n`` newlines so the output is byte-identical on any
    # platform (AC-GEN-7); ``newline=""`` stops the platform translating ``\n``.
    out_path.write_text(html, encoding="utf-8", newline="")
    return 0


if __name__ == "__main__":  # pragma: no cover - module entry point
    raise SystemExit(main())
