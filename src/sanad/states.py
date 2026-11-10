"""Shared evaluation/workflow states, reason codes and approved wording.

These are the single source of truth for the five evaluation states, the
workflow state machine and the fixed wording the engine is allowed to emit.
Keeping them here (rather than in each rule module) is what lets the
invariants be enforced centrally:

* ``MET`` is only ever returned when no mandatory input is missing, stale or
  in an unresolved unit (PBT-1 / baseline invariant 1).
* The silence text is the *only* text rendered when nothing is ``met``; a
  silent bed is never shown as safe, stable, clear or green
  (PBT-10, AC-DEF-4, baseline invariant 10).
* Workflow transitions never mutate an :class:`EvaluationState` and never close
  an open episode (AC-DEF-2).

Stdlib only; no I/O; importable in isolated mode.
"""

from __future__ import annotations

from enum import Enum

__all__ = [
    "EvaluationState",
    "WorkflowState",
    "ReasonCode",
    "SILENCE_TEXT",
    "BANNED_SILENCE_WORDS",
    "R1_MET_TEXT",
    "R2_COMBINED_TEXT",
    "R3_OVERDUE_TEXT",
    "WORKFLOW_TRANSITIONS",
    "next_workflow_state",
]


class EvaluationState(Enum):
    """Exactly one of these is returned by any rule evaluation (AC-DEF-1)."""

    MET = "met"
    NOT_MET = "not_met"
    UNKNOWN = "unknown"
    SUPPRESSED = "suppressed"
    NOT_APPLICABLE = "not_applicable"


class WorkflowState(Enum):
    """The workflow state of an episode; separate from the evaluation state.

    ``idle -> notified -> acknowledged -> assessed -> deferred | resolved``.
    Transitions never change the evaluation state (AC-DEF-2).
    """

    IDLE = "idle"
    NOTIFIED = "notified"
    ACKNOWLEDGED = "acknowledged"
    ASSESSED = "assessed"
    DEFERRED = "deferred"
    RESOLVED = "resolved"


class ReasonCode(str, Enum):
    """Why a rule returned the state it did.

    A :class:`str` enum so the value can be compared to, and serialised as, a
    plain string while still being an explicit, typo-proof constant.
    """

    # --- unknown: a required datum is missing / stale / unresolved ----------
    SAT_NOT_RECORDED = "sat_not_recorded"
    HAEMO_UNCONFIRMED = "haemo_unconfirmed"
    WEIGHT_MISSING = "weight_missing"
    TWELVE_H_REF_MISSING = "twelve_h_ref_missing"
    STALE_DATA = "stale_data"
    INSUFFICIENT_HISTORY = "insufficient_history"
    OUTPUT_NOT_CHARTED = "output_not_charted"
    UNSUPPORTED_UNIT = "unsupported_unit"
    MISSING_ITEM = "missing_item"
    CONFIRMATION_EXPIRED = "confirmation_expired"

    # --- not_met: a recorded negative or a failed gate ----------------------
    CONTEXT_REVIEW = "context_review"
    NMBA_INFUSING = "nmba_infusing"
    OK_NOT_MET = "ok_not_met"

    # --- suppressed: an active hold / deferral / acknowledged episode -------
    HELD_DEFERRED = "held_deferred"
    ACKNOWLEDGED_OPEN = "acknowledged_open"

    # --- not_applicable: an excluded pathway --------------------------------
    PATHWAY_EXCLUDED = "pathway_excluded"
    ECMO = "ecmo"
    COMFORT_ONLY = "comfort_only"

    # --- silence -------------------------------------------------------------
    NO_RULE_TRIGGERED = "no_rule_triggered"


# The single silence constant (AC-DEF-4, PBT-10). This exact string is the only
# text rendered when no rule is ``met``.
SILENCE_TEXT = "No configured rule triggered on the available data"

# Words that must never describe a silent or non-triggering state. Tests use
# this set to prove the silence text (and any other emitted text) avoids them.
BANNED_SILENCE_WORDS = frozenset({"safe", "stable", "clear", "green"})

# Approved rule wording (verbatim from the baseline; never paraphrased).
R1_MET_TEXT = (
    "Available data match the configured SBT screen. Clinician review "
    "required; this does not establish SBT or extubation readiness."
)
R2_COMBINED_TEXT = (
    "Worsening oxygenation with positive recorded fluid balance. Review the "
    "patient, oxygenation, fluid accounting and alternative causes (including "
    "hypovolaemia and third-spacing). This does not establish pulmonary "
    "oedema or indicate fluid removal."
)
R3_OVERDUE_TEXT = "No completion recorded in this feed; verify whether performed."


# The allowed workflow transitions as a pure state machine. ``acknowledge``
# keeps an episode open (it maps to ACKNOWLEDGED, a non-terminal state); only a
# valid check / documented deferral reaches a terminal (RESOLVED / DEFERRED)
# state. This never touches an EvaluationState (AC-DEF-2).
WORKFLOW_TRANSITIONS: dict[WorkflowState, frozenset[WorkflowState]] = {
    WorkflowState.IDLE: frozenset({WorkflowState.NOTIFIED}),
    WorkflowState.NOTIFIED: frozenset(
        {WorkflowState.ACKNOWLEDGED, WorkflowState.ASSESSED,
         WorkflowState.DEFERRED, WorkflowState.RESOLVED}
    ),
    WorkflowState.ACKNOWLEDGED: frozenset(
        {WorkflowState.ASSESSED, WorkflowState.DEFERRED, WorkflowState.RESOLVED}
    ),
    WorkflowState.ASSESSED: frozenset(
        {WorkflowState.DEFERRED, WorkflowState.RESOLVED}
    ),
    WorkflowState.DEFERRED: frozenset({WorkflowState.RESOLVED}),
    WorkflowState.RESOLVED: frozenset(),
}

# States from which an episode is still open (i.e. not terminal).
_OPEN_WORKFLOW_STATES = frozenset(
    {WorkflowState.IDLE, WorkflowState.NOTIFIED,
     WorkflowState.ACKNOWLEDGED, WorkflowState.ASSESSED}
)


def next_workflow_state(
    current: WorkflowState, target: WorkflowState
) -> WorkflowState:
    """Return ``target`` if the transition is legal, else raise ``ValueError``.

    Pure: no state is stored, nothing is mutated. Callers use the returned
    value; the evaluation state is never derived from it (AC-DEF-2).
    """

    if target in WORKFLOW_TRANSITIONS.get(current, frozenset()):
        return target
    raise ValueError(f"illegal workflow transition {current.value} -> {target.value}")


def is_open(state: WorkflowState) -> bool:
    """True while an episode is still open (acknowledging keeps it open)."""

    return state in _OPEN_WORKFLOW_STATES
