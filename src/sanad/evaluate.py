"""Orchestration over the shared 5-minute grid: all rules + cross-rule pieces.

This module assembles the per-bed, per-time :class:`~sanad.model.GridCell`
from the individual rule evaluations, and adds the cross-rule pieces that
belong to the orchestrator rather than to any single rule (design.md Section 9):

* **All configured rules** -- R1, R2a, R2b and R3 are each evaluated on the
  data *as known at* ``t`` (each rule module applies its own freshness /
  history / pathway gating), and their :class:`~sanad.model.RuleResult` objects
  are bundled into the cell's ``results`` map keyed by rule id (AC-DEF-1,
  AC-DEF-3).
* **R2 combined message** -- when R2a is ``met`` *and* R2b is ``met`` at the
  same grid time, the cell carries the single approved combined wording
  (:data:`~sanad.states.R2_COMBINED_TEXT`), which lists the alternative causes
  and explicitly does not establish pulmonary oedema or indicate fluid removal
  (AC-R2-comb; oracle bed 6 from 02:00). The combined message is decided *per
  grid point* on the shared grid, so it can only appear at a ``t`` where both
  rules independently resolved to ``met`` on the data as known at that ``t``
  (AC-DEF-3) -- bed 6's R2a is ``met`` from 01:05 and R2b only from 02:00, so
  the combined message first appears at 02:00, not before.
* **Feed alert** -- the staleness decision from
  :func:`~sanad.freshness.freshness_gate` for the encounter is surfaced as
  ``GridCell.feed_alert``. It is ``True`` exactly while the newest observation
  as known at ``t`` is stale (> 15 min old, or none) -- the false-reassurance
  signal the board actually has -- a visible failure state, never silence
  (AC-DEF-5, AC-R3-failure, invariants 1 and 9, PBT-9). Bed 9's feed is reported
  down from 01:00, but its last reading (00:55) stays fresh through 01:10, so
  the alert is raised on the grid from 01:15 to 02:25 -- the staleness window --
  even though every rule is (correctly) ``unknown`` there. The ``feed_status``
  event records the cause of the outage; the alert tracks the moment fresh data
  is actually lost, keeping the window consistent with the oracle.
* **Workflow states** -- the open episodes' workflow states
  (:class:`~sanad.states.WorkflowState`) are carried per rule in
  ``GridCell.workflow_states``. The workflow is *presentation only*: it never
  changes an evaluation state and acknowledging never closes an episode
  (AC-DEF-2). R3 is the rule with an explicit episode lifecycle, so its
  workflow state is always reported; R1 episodes are handled inside R1's own
  result (``suppressed`` when held) and are left out of this map so there is a
  single, unambiguous source for each rule's state.
* **Silence text** -- when no configured rule is ``met`` at ``t``, the cell's
  ``display_text`` is the single silence constant
  (:data:`~sanad.states.SILENCE_TEXT`) and nothing else; a silent bed is never
  rendered as safe, stable, clear or green (AC-DEF-4, PBT-10, baseline
  invariant 10, the top hazard D06). ``unknown`` / ``not_met`` /
  ``not_applicable`` / ``suppressed`` are all "not met" and therefore silent in
  this display sense -- but the reason each rule gives is still carried in its
  :class:`~sanad.model.RuleResult` (and a feed failure is carried in
  ``feed_alert``), so silence is never mistaken for a positive "all clear".

The ward-wide driver :func:`evaluate_ward` runs every encounter in the dataset
over the night window read from the dataset ``meta`` (or an explicit window),
producing a deterministic, ordered structure the scenario-oracle tests index by
``(encounter, t)``. Re-running over the same inputs yields a byte-for-byte
identical structure (determinism; ``.kiro/steering/tech.md``).

Every rule is evaluated through its own pure ``evaluate_*`` on the data **as
known at t**, and this module only *combines* their results. It imports every
rule module (allowed for the orchestrator) but no rule imports it.

Pure and deterministic: ``(dataset, encounter, t) -> GridCell``; no I/O beyond
the already-loaded dataset, no wall-clock, no mutation of the inputs. Stdlib
only, isolated-mode safe.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from typing import Optional

from . import r1, r2a, r2b, r3
from .freshness import freshness_gate
from .model import Dataset, GridCell, RuleResult
from .states import (
    SILENCE_TEXT,
    EvaluationState,
    R2_COMBINED_TEXT,
    WorkflowState,
)
from .timeline import grid

__all__ = [
    "R1_RULE_ID",
    "R2A_RULE_ID",
    "R2B_RULE_ID",
    "R3_RULE_ID",
    "r2_combined_message",
    "r2a_fluid_unknown_detail",
    "silence_display_text",
    "evaluate_cell",
    "evaluate_encounter",
    "evaluate_ward",
    "night_window",
]

R1_RULE_ID = r1.RULE_ID
R2A_RULE_ID = r2a.RULE_ID
R2B_RULE_ID = r2b.RULE_ID
R3_RULE_ID = r3.RULE_ID


@dataclass(frozen=True, slots=True)
class _Contexts:
    """The four per-``(dataset, encounter)`` rule contexts, built once.

    Each rule's context is a pure function of the dataset and the encounter --
    it does not depend on the grid time ``t`` -- so it can be built once per
    encounter and reused across all 145 grid points rather than rebuilt in every
    :func:`evaluate_cell` call. Internal to the orchestrator; the public
    ``evaluate_cell`` signature stays ``(ds, encounter, t)``.
    """

    r1: "r1.R1Context"
    r2a: "r2a.R2aContext"
    r2b: "r2b.R2bContext"
    r3: "r3.R3Context"


def _build_contexts(ds: Dataset, encounter: str) -> _Contexts:
    """Build the four rule contexts for one encounter (time-independent)."""

    return _Contexts(
        r1=r1.context_for(ds, encounter),
        r2a=r2a.context_for(ds, encounter),
        r2b=r2b.context_for(ds, encounter),
        r3=r3.context_for(ds, encounter),
    )


def _is_met(result: Optional[RuleResult]) -> bool:
    """True only when a rule resolved to ``met`` (the one positive state).

    ``unknown`` / ``not_met`` / ``suppressed`` / ``not_applicable`` are all
    *not* ``met``; a ``None`` result (rule not run for this cell) is likewise
    not ``met``. This single predicate drives both the combined-message test
    (both R2a and R2b ``met``) and the silence test (no rule ``met``), so the
    two can never disagree about what "met" means.
    """

    return result is not None and result.state is EvaluationState.MET


def r2_combined_message(
    r2a_result: Optional[RuleResult], r2b_result: Optional[RuleResult]
) -> str:
    """The approved R2 combined wording when **both** R2a and R2b are ``met``.

    Returns :data:`~sanad.states.R2_COMBINED_TEXT` verbatim when R2a and R2b
    are both ``met`` at the same grid time (AC-R2-comb), else an empty string.
    The wording is taken from the baseline and is never paraphrased.
    """

    if _is_met(r2a_result) and _is_met(r2b_result):
        return R2_COMBINED_TEXT
    return ""


def _is_unknown(result: Optional[RuleResult]) -> bool:
    """True only when a rule resolved to ``unknown`` (a missing/stale datum)."""

    return result is not None and result.state is EvaluationState.UNKNOWN


def r2a_fluid_unknown_detail(
    r2a_result: Optional[RuleResult], r2b_result: Optional[RuleResult]
) -> Optional[RuleResult]:
    """R2a's result with the "fluid balance unknown" label appended iff needed.

    The baseline labels an R2a ``met`` "fluid balance unknown" only *"if fluid
    data are missing or incomplete"* (``docs/EVIDENCE.md`` R2a;
    AC-R2a-fluid-independent). Whether the fluid ledger is incomplete for this
    encounter at this grid time is precisely R2b's ``unknown`` result -- the
    ``output_not_charted`` / ``insufficient_history`` / ``stale_data`` cases.
    R2a is fluid-independent by construction and cannot read a fluid record, so
    it cannot decide this itself; the label is a *cross-rule display* concern
    the orchestrator owns, which is why it lives here and not in ``r2a.py``
    (D29, clinical lead 9 Nov; the prior build appended it to every R2a ``met``,
    even beside a complete R2b ledger such as bed 6 at 02:00).

    When R2a is ``met`` **and** R2b is ``unknown`` on the same cell, returns a
    copy of ``r2a_result`` with ``"; fluid balance unknown"`` appended to its
    detail (or the bare label when the detail is empty). Otherwise returns the
    R2a result unchanged. The two rules stay independent: only R2a's *displayed
    detail* is completed -- its ``state`` and ``reason`` are never touched, and
    R2b is never modified. Returns ``None`` iff ``r2a_result`` is ``None``.

    Pure: builds a new frozen :class:`~sanad.model.RuleResult` via
    :func:`dataclasses.replace`; nothing is mutated.
    """

    if r2a_result is None:
        return None
    if not (_is_met(r2a_result) and _is_unknown(r2b_result)):
        return r2a_result
    label = r2a.FLUID_UNKNOWN_LABEL
    detail = f"{r2a_result.detail}; {label}" if r2a_result.detail else label
    return replace(r2a_result, detail=detail)


def silence_display_text(results: dict[str, RuleResult]) -> str:
    """The display text for a cell: the silence constant iff nothing is ``met``.

    Pure function of the per-rule results. When **no** rule is ``met`` the cell
    is silent and its display text is exactly
    :data:`~sanad.states.SILENCE_TEXT` -- never safe, stable, clear or green
    (AC-DEF-4, PBT-10, baseline invariant 10). When at least one rule *is*
    ``met`` the display is driven by that rule's own approved wording, so the
    silence text is not used and this returns an empty string.

    Factored out so the invariant can be property-tested directly over any
    combination of rule states, independent of how a cell was built.
    """

    any_met = any(_is_met(r) for r in results.values())
    return "" if any_met else SILENCE_TEXT


def evaluate_cell(
    ds: Dataset,
    encounter: str,
    t: datetime,
    contexts: Optional["_Contexts"] = None,
) -> GridCell:
    """Evaluate every configured rule for one encounter at grid time ``t``.

    Runs R1, R2a, R2b and R3 on the data as known at ``t`` (each rule applies
    its own freshness / history / pathway gating), bundles their
    :class:`~sanad.model.RuleResult` into a :class:`~sanad.model.GridCell`, then
    adds the orchestrator-level fields:

    * ``combined_message`` -- the R2 combined wording when R2a and R2b are both
      ``met`` (AC-R2-comb);
    * the R2a result's *detail* is completed with the "fluid balance unknown"
      label only when R2a is ``met`` and R2b is ``unknown`` on this cell
      (:func:`r2a_fluid_unknown_detail`; D29). R2a's state and reason are never
      changed, and R2b is untouched -- the rules stay independent;
    * ``feed_alert`` -- the observation-staleness decision for this encounter
      **while it is on the board**: ``True`` when the encounter is active at
      ``t`` *and* the newest reading as known at ``t`` is stale (> 15 min), a
      visible failure state and never silence (AC-DEF-5, AC-R3-failure, PBT-9);
    * ``workflow_states`` -- the R3 episode's workflow state (presentation only,
      never mutating an evaluation state; AC-DEF-2);
    * ``display_text`` -- the single silence constant when *no* rule is ``met``
      (AC-DEF-4, PBT-10); empty when at least one rule is ``met`` (that rule's
      own approved wording is what the UI shows instead of silence).

    ``contexts`` may be passed by :func:`evaluate_encounter` so the four
    per-``(ds, encounter)`` rule contexts are built once per encounter rather
    than rebuilt at every one of the 145 grid points (the contexts are
    time-independent); when omitted they are built here, so the public
    ``evaluate_cell(ds, encounter, t)`` signature still works on its own.

    Deterministic and pure: identical inputs give an identical cell.
    """

    enc = ds.by_encounter[encounter]

    if contexts is None:
        contexts = _build_contexts(ds, encounter)
    r1_ctx = contexts.r1
    r2a_ctx = contexts.r2a
    r2b_ctx = contexts.r2b
    r3_ctx = contexts.r3

    r1_result = r1.evaluate_r1(r1_ctx, t)
    r2a_result = r2a.evaluate_r2a(r2a_ctx, t)
    r2b_result = r2b.evaluate_r2b(r2b_ctx, t)
    r3_result = r3.evaluate_r3(r3_ctx, t)

    # D29: complete R2a's *display detail* with "fluid balance unknown" only
    # when the fluid ledger is itself ``unknown`` for this cell (R2b unknown).
    # This is a cross-rule display step the orchestrator owns -- R2a cannot see
    # a fluid record -- and it never changes R2a's state/reason or R2b
    # (AC-R2a-fluid-independent; the rules stay independent).
    r2a_result = r2a_fluid_unknown_detail(r2a_result, r2b_result)

    results: dict[str, RuleResult] = {
        R1_RULE_ID: r1_result,
        R2A_RULE_ID: r2a_result,
        R2B_RULE_ID: r2b_result,
        R3_RULE_ID: r3_result,
    }

    combined_message = r2_combined_message(r2a_result, r2b_result)

    # The single freshness/feed decision for this encounter. The ward-level
    # ``feed_alert`` is a visible failure state raised independently of whether
    # any rule is ``met`` -- a feed failure is never silence (AC-DEF-5,
    # AC-R3-failure, PBT-9).
    #
    # It tracks observation **staleness** (``gate.stale``) **only while the
    # encounter is on the board** (``r3.is_active``): the alert is shown exactly
    # while the newest observation as-known-at ``t`` is older than the 15-min
    # fresh window (or there is none) *for an admitted, not-yet-discharged
    # encounter*. That is the false-reassurance signal the night-shift board
    # actually has -- the top hazard is a stale reading being mistaken for a
    # live one (``.kiro/steering/safety.md``, D06).
    #
    # Gating on the active window matters because the ward grid evaluates every
    # encounter over the whole night (19:00-07:00), including a reassigned bed's
    # two encounters. An encounter that is not on the board at ``t`` -- bed 13's
    # ``E13A`` after its 23:00 discharge, or ``E13B`` before its 23:15 admission
    # -- has (of course) no fresh observations, but there is no board slot to
    # alert on: raising ``feed_alert`` there would be a false positive, not a
    # real outage (AC-R3-encounter). The active-window test is the same one R3
    # uses before it returns ``not_applicable`` outside the window.
    #
    # A ``feed_status: down`` event records the *cause* of an outage, but its
    # start instant is not when the board loses fresh data: the last good
    # reading is still fresh for up to 15 min after it. Bed 9's feed is reported
    # down from 01:00, yet its last observation (00:55) stays fresh through
    # 01:10, so the oracle fixes the feed alert at **01:15-02:25** -- the
    # staleness window -- not 01:00 (``data/SCENARIOS.md`` bed 9; design
    # Section 7 "unknown 01:15-02:25"). Gating the alert on staleness rather than
    # on the raw event window keeps the two consistent: the outage still surfaces
    # as its own visible failure state (never silence), only from the moment the
    # consumer has actually lost fresh data. The standalone feed-down path is
    # still enforced where the invariant is defined -- ``freshness_gate`` returns
    # ``feed_alert = stale or feed_down`` (PBT-9, tested directly) and R3 carries
    # a feed/scheduler-failure note in its result detail (AC-R3-failure) -- so no
    # feed failure is silently dropped at the engine level.
    gate = freshness_gate(r3_ctx.observations, t, r3_ctx.events)
    feed_alert = r3.is_active(r3_ctx, t) and gate.stale

    # Workflow states (presentation only). R3 carries an explicit episode
    # lifecycle, so its workflow state is always reported; acknowledging keeps
    # an open episode open and never changes the evaluation state (AC-DEF-2).
    workflow_states: dict[str, WorkflowState] = {
        R3_RULE_ID: r3.workflow_state_at(r3_ctx, t),
    }

    # Silence: display the single silence text iff nothing is ``met`` (see
    # :func:`silence_display_text`). A bed that is ``unknown`` / ``not_met`` /
    # ``not_applicable`` / ``suppressed`` everywhere is still silent in the
    # display sense -- but never "safe" (AC-DEF-4, PBT-10). When any rule is
    # ``met`` the display is driven by that rule's own approved wording, so
    # ``display_text`` stays empty.
    display_text = silence_display_text(results)

    return GridCell(
        bed=enc.bed,
        encounter=encounter,
        t=t,
        results=results,
        combined_message=combined_message,
        feed_alert=feed_alert,
        display_text=display_text,
        workflow_states=workflow_states,
    )


def evaluate_encounter(
    ds: Dataset, encounter: str, start: datetime, end: datetime
) -> list[GridCell]:
    """Evaluate one encounter across the shared 5-minute grid ``[start, end]``.

    Produces one :class:`~sanad.model.GridCell` per clock-aligned grid point
    (``…:00, :05, …``) using :func:`~sanad.timeline.grid`, so the combined
    message and silence text are decided on the same grid every rule is
    evaluated on (AC-DEF-3). Returns an ordered list indexable by position;
    re-running over the same window yields an identical list (determinism).

    The four rule contexts are time-independent per ``(ds, encounter)``, so they
    are built once here and reused at every grid point rather than rebuilt in
    each :func:`evaluate_cell` call.
    """

    contexts = _build_contexts(ds, encounter)
    return [evaluate_cell(ds, encounter, t, contexts) for t in grid(start, end)]


def night_window(ds: Dataset) -> tuple[datetime, datetime]:
    """The night-shift board window ``(night_start, night_end)`` for the ward.

    Read from the dataset ``meta`` when present (the frozen dataset records
    ``night_start`` 19:00 and ``night_end`` 07:00 the next day); otherwise a
    fixed ``+01:00`` 19:00->07:00 window matching the baseline. Timezone-aware;
    never derived from the local clock.
    """

    meta = ds.meta or {}
    start_s = meta.get("night_start")
    end_s = meta.get("night_end")
    if start_s is not None and end_s is not None:
        return datetime.fromisoformat(start_s), datetime.fromisoformat(end_s)
    tz = timezone(timedelta(hours=1))
    start = datetime(2026, 11, 20, 19, 0, tzinfo=tz)
    end = datetime(2026, 11, 21, 7, 0, tzinfo=tz)
    return start, end


def evaluate_ward(
    ds: Dataset,
    start: Optional[datetime] = None,
    end: Optional[datetime] = None,
) -> dict[str, list[GridCell]]:
    """Evaluate **every** encounter over the night window on the shared grid.

    Drives :func:`evaluate_encounter` for each encounter in the dataset
    (including both encounters of a reassigned bed, e.g. bed 13's ``E13A`` and
    ``E13B``) over ``[start, end]``. When ``start`` / ``end`` are omitted they
    default to :func:`night_window` -- the board window 19:00->07:00.

    Returns an ordered mapping ``encounter id -> [GridCell, ...]`` in the
    dataset's own encounter order, each list on the same clock-aligned grid.
    The whole structure is a pure, deterministic function of the loaded dataset
    and the window: re-running produces an identical result (``.kiro/steering/
    tech.md``; AC-DEF-3). The scenario-oracle tests index this by
    ``(encounter, t)`` to assert each bed's expected outcomes and timings.
    """

    if start is None or end is None:
        default_start, default_end = night_window(ds)
        start = default_start if start is None else start
        end = default_end if end is None else end

    return {
        enc.encounter: evaluate_encounter(ds, enc.encounter, start, end)
        for enc in ds.encounters
    }
