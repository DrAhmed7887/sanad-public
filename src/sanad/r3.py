"""R3 -- task and response tracker (per-encounter ventilation check).

Pure, deterministic evaluation of the configured *task tracker* on the fixed
synthetic dataset. R3 is **not** continuous monitoring (``docs/EVIDENCE.md`` R3;
requirements Section 6): it tracks whether the 2-hourly ventilation check for an
**encounter** has a valid completion recorded, and surfaces an overdue check so
a missed one is visible -- without inheriting another encounter's history and
without ever rendering silence for a feed/scheduler/routing failure.

The task, verbatim from the baseline:

* A **valid check** records all three required fields -- a breathing-effort
  assessment, a haemodynamics assessment and a cuff pressure in cmH2O. Any
  missing field means it is *not* a valid check (AC-R3-valid).
* **Due time** = the last valid check for this encounter + 2 h. A newly
  admitted encounter's **first** check is due 30 min after admission
  (AC-R3-due).
* R3 is **``met`` (overdue)** when no valid check exists by due time + a 10 min
  grace (inclusive); the message is the single approved
  :data:`~sanad.states.R3_OVERDUE_TEXT` (AC-R3-overdue; oracle bed 10 met
  01:10-01:50).
* The **workflow** continues ``notified -> acknowledged -> assessed ->
  resolved``; acknowledging keeps the episode ``met`` and open, and only a
  valid check or a documented deferral (reason, owner, expiry) ends it
  (AC-R3-workflow, AC-DEF-2; oracle bed 10 ``not_met`` from 01:55 once the
  01:50 check is known).
* Checks are matched **per encounter, never per bed**: another encounter's
  check in the same bed never satisfies or resets this encounter's task, in
  either direction across a reassignment (AC-R3-encounter; oracle bed 13 A and
  B never met via inheritance).
* A **feed, scheduler or routing failure** is shown as its own alert, never as
  silence (AC-R3-failure, invariant 9).

Everything is computed **as known at t**: a check counts only once its
``documented_time <= t`` (AC-DEF-11), so bed 10's 01:50 check (documented 01:52)
does not end the episode until 01:55.

Pure: ``(context, t) -> RuleResult``; no I/O, no wall-clock, no mutation of the
inputs. Imports only shared modules (never another rule). Stdlib only.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

from .freshness import feed_down_at
from .model import Dataset, Event, Observation, RuleResult
from .states import (
    EvaluationState,
    R3_OVERDUE_TEXT,
    ReasonCode,
    WorkflowState,
)
from .timeline import as_known_at

__all__ = [
    "RULE_ID",
    "CHECK_INTERVAL",
    "FIRST_CHECK_DELAY",
    "GRACE",
    "R3Context",
    "context_for",
    "evaluate_r3",
    "workflow_state_at",
    "is_active",
]

RULE_ID = "R3"

# --- configured intervals (DESIGN demo values / local policy, baseline v3) --

# A ventilation check is due every 2 h after the last valid check.
CHECK_INTERVAL = timedelta(hours=2)

# A newly admitted encounter's first check is due 30 min after admission.
FIRST_CHECK_DELAY = timedelta(minutes=30)

# Grace after the due time before an unrecorded check is flagged overdue. The
# boundary is inclusive: overdue is raised at due + 10 min exactly.
GRACE = timedelta(minutes=10)


# --- per-encounter context --------------------------------------------------


@dataclass(frozen=True, slots=True)
class R3Context:
    """Everything R3 needs for one encounter, filtered to that encounter.

    All events belong to a single encounter, so another encounter's checks are
    structurally absent -- the "no inheritance across a reassignment" property
    (AC-R3-encounter, PBT-8) holds by construction, not by a runtime filter.
    ``observations`` are carried only so the feed/scheduler failure alert can be
    raised from the same freshness signal the other rules use; R3's overdue
    logic reads only the task events.
    """

    encounter: str
    bed: int
    events: tuple[Event, ...]
    observations: tuple[Observation, ...]


def context_for(ds: Dataset, encounter: str) -> R3Context:
    """Build an :class:`R3Context` for one encounter from a loaded dataset."""

    enc = ds.by_encounter[encounter]
    return R3Context(
        encounter=encounter,
        bed=enc.bed,
        events=tuple(e for e in ds.events if e.encounter == encounter),
        observations=tuple(o for o in ds.observations if o.encounter == encounter),
    )


# --- helpers ----------------------------------------------------------------


def _is_valid_check(e: Event) -> bool:
    """A ventilation check with all three required fields present (AC-R3-valid).

    A missing breathing-effort assessment, haemodynamics assessment or cuff
    pressure (cmH2O) means the record is *not* a valid check -- it neither
    satisfies nor resets the task.
    """

    if e.type != "vent_check":
        return False
    return (
        e.effort is not None
        and e.haemodynamics is not None
        and e.cuff_pressure_cmH2O is not None
    )


def _visible_valid_checks(ctx: R3Context, t: datetime) -> list[Event]:
    """This encounter's valid checks known at ``t``, ordered by performed time.

    ``as_known_at`` filters to ``documented_time <= t`` and orders
    deterministically (by event time = ``performed_at`` for a check), so a check
    performed at 01:50 but documented 01:52 is invisible until 01:52 and then
    placed at its 01:50 performed time (bed 10).
    """

    visible = as_known_at(list(ctx.events), t)
    return [e for e in visible if _is_valid_check(e)]


def _admission_time(ctx: R3Context, t: datetime) -> Optional[datetime]:
    """The encounter's admission time, if an admission event is known at ``t``."""

    adms = [
        e.t
        for e in ctx.events
        if e.type == "admission" and e.t is not None and e.t <= t
    ]
    return min(adms) if adms else None


def _discharge_time(ctx: R3Context, t: datetime) -> Optional[datetime]:
    """The encounter's discharge time, if a discharge event is known at ``t``."""

    dis = [
        e.t
        for e in ctx.events
        if e.type == "discharge" and e.t is not None and e.t <= t
    ]
    return min(dis) if dis else None


def is_active(ctx: R3Context, t: datetime) -> bool:
    """True when the encounter is on the board at ``t`` (admitted, not discharged).

    The encounter's active admission window is ``admission <= t < discharge``
    (discharge exclusive), exactly the window :func:`evaluate_r3` uses before it
    returns ``not_applicable`` outside it. An encounter with **no** admission
    event is treated as already on the board from the start of the window (the
    dataset only records an admission for a *newly* admitted encounter, e.g.
    bed 13's ``E13B``); an encounter with **no** discharge event stays active to
    the end of the window.

    This is what lets the orchestrator avoid false feed alerts on an encounter
    that is not even on the board at ``t`` -- e.g. bed 13's ``E13A`` after its
    23:00 discharge or ``E13B`` before its 23:15 admission, where there are (of
    course) no fresh observations but no board slot to alert on either
    (AC-R3-encounter). Pure and deterministic; ``as-known-at`` via the same
    admission / discharge helpers the rule uses.
    """

    discharge = _discharge_time(ctx, t)
    if discharge is not None and t >= discharge:
        return False
    has_admission = any(
        e.type == "admission" and e.t is not None for e in ctx.events
    )
    if has_admission and _admission_time(ctx, t) is None:
        return False
    return True


def _active_deferral(ctx: R3Context, t: datetime) -> Optional[Event]:
    """An R3 deferral in force at ``t`` (documented, not yet past its ``until``).

    A documented deferral (reason, owner, expiry) ends the current episode and
    suppresses the task until its ``until`` time (AC-R3-workflow). Only
    deferrals for R3 (or with no rule tag) are considered.
    """

    best: Optional[Event] = None
    for e in ctx.events:
        if e.type != "deferral":
            continue
        if e.rule is not None and e.rule != RULE_ID:
            continue
        if e.documented_time is None or e.documented_time > t:
            continue
        if e.until is not None and e.until <= t:
            continue  # the deferral has expired
        if best is None or (e.t or e.documented_time) > (best.t or best.documented_time):
            best = e
    return best


def _due_time(ctx: R3Context, t: datetime) -> Optional[datetime]:
    """The time the *current* check is due, as known at ``t`` (AC-R3-due).

    Due = the last valid check's performed time + 2 h. When no valid check is
    yet known, due is the admission time + 30 min (a newly admitted encounter's
    first check). Returns ``None`` when neither is available (no basis to time a
    task -- R3 cannot be overdue without a reference point).
    """

    checks = _visible_valid_checks(ctx, t)
    if checks:
        last = max(c.performed_at for c in checks if c.performed_at is not None)
        return last + CHECK_INTERVAL
    admission = _admission_time(ctx, t)
    if admission is not None:
        return admission + FIRST_CHECK_DELAY
    return None


def _episode_start(ctx: R3Context, t: datetime) -> Optional[datetime]:
    """When the current overdue episode became overdue (due + grace), or None.

    The episode starts at due + grace and stays open until a valid check or a
    documented deferral ends it. Because due is recomputed as-known-at ``t``,
    a newly documented valid check moves ``due`` forward and the episode is no
    longer open (its basis has changed) -- this is how bed 10 resolves at 01:55.
    """

    due = _due_time(ctx, t)
    if due is None:
        return None
    overdue_at = due + GRACE
    return overdue_at if t >= overdue_at else None


def workflow_state_at(ctx: R3Context, t: datetime) -> WorkflowState:
    """The workflow state of the R3 episode at ``t`` (separate from evaluation).

    ``idle`` with no open episode; ``notified`` once overdue; ``acknowledged``
    after an ``acknowledge`` staff action while still open; ``deferred`` /
    ``resolved`` once a documented deferral / valid check has ended it. This is
    presentation only -- it never changes the evaluation state (AC-DEF-2); the
    evaluation state is derived independently in :func:`evaluate_r3`.
    """

    # A documented deferral ends the episode as ``deferred``.
    if _active_deferral(ctx, t) is not None:
        return WorkflowState.DEFERRED

    overdue_at = _episode_start(ctx, t)
    if overdue_at is None:
        # Either never overdue, or a later valid check moved ``due`` past ``t``
        # so the episode has been resolved by a completion.
        if _visible_valid_checks(ctx, t):
            return WorkflowState.RESOLVED
        return WorkflowState.IDLE

    # Episode is open (overdue). Was it acknowledged while open?
    acked = any(
        e.type == "staff_action"
        and (e.action or "").strip().lower() == "acknowledge"
        and (e.rule is None or e.rule == RULE_ID)
        and e.t is not None
        and overdue_at <= e.t <= t
        for e in ctx.events
    )
    return WorkflowState.ACKNOWLEDGED if acked else WorkflowState.NOTIFIED


# --- the public evaluation --------------------------------------------------


def evaluate_r3(ctx: R3Context, t: datetime) -> RuleResult:
    """Evaluate R3 for one encounter at grid time ``t`` -> one state + reason.

    Ordering:

    1. Outside the encounter's active window (before admission / at or after
       discharge) -> ``not_applicable``: there is no task to track, and another
       encounter's checks in the same bed must never be inherited (AC-R3-
       encounter; bed 13 A after 23:00, B before 23:15).
    2. A documented deferral in force -> ``suppressed`` (the episode is ended /
       held; the hold and its review time are shown, AC-R3-workflow).
    3. Overdue (no valid check by due + grace, as known at ``t``) -> ``met``
       with the approved overdue wording; acknowledging keeps it ``met`` and the
       episode open (AC-R3-overdue, AC-R3-workflow, PBT-7).
    4. Otherwise -> ``not_met``: a valid check is recorded on time, or the task
       is not yet due.

    A feed/scheduler/routing failure never silences R3: a ``feed_status`` down
    event known at ``t`` is surfaced in the detail as its own visible failure
    state (AC-R3-failure, invariant 9). It does not change the overdue decision
    (which is about a missing *check*, not stale observations), so the alert is
    reported alongside whatever state the task logic resolves to.
    """

    failure = feed_down_at(list(ctx.events), t)
    failure_note = " [feed/scheduler failure: visible alert raised]" if failure else ""

    # 1. Active window: before admission or at/after discharge -> not_applicable.
    discharge = _discharge_time(ctx, t)
    if discharge is not None and t >= discharge:
        return RuleResult(
            rule_id=RULE_ID,
            state=EvaluationState.NOT_APPLICABLE,
            reason=ReasonCode.PATHWAY_EXCLUDED,
            detail=f"encounter discharged at {discharge.isoformat()}" + failure_note,
        )
    # An admission event, when present, bounds the start of the active window.
    has_admission = any(
        e.type == "admission" and e.t is not None for e in ctx.events
    )
    if has_admission and _admission_time(ctx, t) is None:
        return RuleResult(
            rule_id=RULE_ID,
            state=EvaluationState.NOT_APPLICABLE,
            reason=ReasonCode.PATHWAY_EXCLUDED,
            detail="encounter not yet admitted" + failure_note,
        )

    # 2. A documented deferral in force -> suppressed (episode ended / held).
    deferral = _active_deferral(ctx, t)
    if deferral is not None:
        until = deferral.until.isoformat() if deferral.until is not None else "unset"
        owner = deferral.owner or "unknown"
        return RuleResult(
            rule_id=RULE_ID,
            state=EvaluationState.SUPPRESSED,
            reason=ReasonCode.HELD_DEFERRED,
            detail=f"deferred until {until} (owner {owner})" + failure_note,
        )

    # 3. Overdue -> met (overdue). Acknowledging keeps it met and open; only a
    #    valid check (which moves ``due`` forward) ends it.
    overdue_at = _episode_start(ctx, t)
    if overdue_at is not None:
        wf = workflow_state_at(ctx, t)
        ack_note = (
            " (acknowledged; episode open)"
            if wf is WorkflowState.ACKNOWLEDGED
            else ""
        )
        return RuleResult(
            rule_id=RULE_ID,
            state=EvaluationState.MET,
            reason=ReasonCode.OK_NOT_MET,
            detail=(
                f"overdue since {overdue_at.isoformat()}" + ack_note + failure_note
            ),
            message=R3_OVERDUE_TEXT,
        )

    # 4. Not overdue: either not yet due, or a valid check is recorded on time.
    due = _due_time(ctx, t)
    if due is None:
        detail = "no check reference yet (awaiting first check / admission)"
    else:
        detail = f"next check due {due.isoformat()}"
    return RuleResult(
        rule_id=RULE_ID,
        state=EvaluationState.NOT_MET,
        reason=ReasonCode.OK_NOT_MET,
        detail=detail + failure_note,
    )
