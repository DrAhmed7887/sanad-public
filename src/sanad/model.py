"""Dataclasses for the dataset records and the engine's results.

Records mirror the inspected JSONL/JSON fields (see ``data/DATA_CARD.md``).
Design choices that protect determinism and the invariants:

* Every record keeps **two times where they differ** -- ``event_time`` (where
  it sits on the timeline) and ``documented_time`` (the visibility gate for the
  as-known-at view, AC-DEF-11). Observations in this dataset are documented at
  their event time, so a single ``t`` is kept; events and fluids carry both.
* ``datetime`` values are timezone-aware (the dataset is ``+01:00``); the
  engine never relies on the local zone.
* Fluid ``ml`` and cuff pressures stay integers; FiO2 is carried as
  :class:`~decimal.Decimal` to avoid float threshold error.
* All record dataclasses are ``frozen`` so loaded data cannot be mutated by a
  rule (rule functions are pure).

Stdlib only.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Optional

from .states import EvaluationState, ReasonCode, WorkflowState

__all__ = [
    "Observation",
    "Infusion",
    "Event",
    "FluidTx",
    "Encounter",
    "DailyTotal",
    "Dataset",
    "RuleResult",
    "GridCell",
]


@dataclass(frozen=True, slots=True)
class Observation:
    """A 5-minute ventilator/monitor sample.

    FiO2 is stored both as its charted value+unit (``fio2`` / ``fio2_unit``) and
    normalised to a fraction (``fio2_fraction``) by the loader via
    :mod:`sanad.units`, so a reading charted ``40`` percent and ``0.40``
    fraction compare identically (AC-DEF-8).
    """

    bed: int
    encounter: str
    t: datetime
    fio2: Decimal
    fio2_unit: str
    fio2_fraction: Decimal
    peep: int
    peep_unit: str
    spo2: int
    spo2_quality: str
    rr: int
    sbp: int
    hr: int
    spont_effort_flag: bool

    @property
    def event_time(self) -> datetime:
        return self.t

    @property
    def documented_time(self) -> datetime:
        # Observations in this dataset are documented at their event time.
        return self.t


@dataclass(frozen=True, slots=True)
class Infusion:
    """A continuous infusion with its raw dose+unit (converted in units.py)."""

    bed: int
    encounter: str
    drug: str
    dose: Decimal
    unit: str
    start: datetime
    end: datetime


@dataclass(frozen=True, slots=True)
class Event:
    """A tagged-union event, discriminated by :attr:`type`.

    Only the fields relevant to a given ``type`` are populated; the rest stay
    ``None``. Keeping one flexible record (rather than a class per type) keeps
    the loader simple while the rule modules switch on ``type``.

    type -> populated fields:
      * ``sat``            : t, result
      * ``rass``           : t, value
      * ``vent_check``     : performed_at, documented_at, effort,
                             haemodynamics, cuff_pressure_cmH2O
      * ``planned_change`` : start, end, reason
      * ``feed_status``    : start, end, status
      * ``deferral``       : t, until, reason, owner, rule
      * ``staff_action``   : t, action, by, rule
      * ``admission``      : t
      * ``discharge``      : t
    """

    bed: int
    encounter: str
    type: str
    t: Optional[datetime] = None
    # sat
    result: Optional[str] = None
    # rass
    value: Optional[int] = None
    # vent_check
    performed_at: Optional[datetime] = None
    documented_at: Optional[datetime] = None
    effort: Optional[str] = None
    haemodynamics: Optional[str] = None
    cuff_pressure_cmH2O: Optional[int] = None
    # planned_change / feed_status
    start: Optional[datetime] = None
    end: Optional[datetime] = None
    reason: Optional[str] = None
    status: Optional[str] = None
    # deferral
    until: Optional[datetime] = None
    owner: Optional[str] = None
    rule: Optional[str] = None
    # staff_action
    action: Optional[str] = None
    by: Optional[str] = None

    @property
    def event_time(self) -> Optional[datetime]:
        """Where the event sits on the timeline.

        For a ventilation check this is when it was *performed*; for the others
        it is the single ``t`` / window ``start`` recorded.
        """

        if self.type == "vent_check":
            return self.performed_at
        if self.type in ("planned_change", "feed_status"):
            return self.start
        return self.t

    @property
    def documented_time(self) -> Optional[datetime]:
        """When the event became visible (the as-known-at gate, AC-DEF-11)."""

        if self.type == "vent_check":
            return self.documented_at
        return self.event_time


@dataclass(frozen=True, slots=True)
class FluidTx:
    """One intake/output transaction from the fluid ledger."""

    bed: int
    encounter: str
    tx_id: str
    kind: str  # "in" | "out"
    ml: int
    source: str  # "iv" | "urine" | "crrt_net" | "crrt_*_gross"
    event_time: datetime
    documented_time: datetime


@dataclass(frozen=True, slots=True)
class Encounter:
    """A patient encounter (bed 13 has two: a reassignment)."""

    bed: int
    encounter: str
    age: int
    sex: str
    weight_kg: Optional[int]
    code_status: str  # "full" | "dnr"
    pathways: tuple[str, ...]
    anuric: bool
    scenario: str


@dataclass(frozen=True, slots=True)
class DailyTotal:
    """Charting-day net that resets at 07:00. A distractor: never used by a
    rule. Loaded only so tests can prove it is ignored (AC-R2b-no-dailytotals).
    """

    bed: int
    encounter: str
    charting_day_from_0700: str
    net_ml: int


@dataclass(frozen=True, slots=True)
class Dataset:
    """All loaded records, grouped by encounter and by bed for lookup.

    ``daily_totals`` is present but deliberately segregated so that any rule
    using it would have to reach past this boundary -- making the "never used"
    property testable.
    """

    meta: dict
    encounters: tuple[Encounter, ...]
    observations: tuple[Observation, ...]
    infusions: tuple[Infusion, ...]
    events: tuple[Event, ...]
    fluids: tuple[FluidTx, ...]
    daily_totals: tuple[DailyTotal, ...]
    by_encounter: dict[str, Encounter]
    by_bed: dict[int, tuple[Encounter, ...]]


@dataclass(frozen=True, slots=True)
class RuleResult:
    """The outcome of evaluating one rule at one grid time."""

    rule_id: str
    state: EvaluationState
    reason: ReasonCode
    detail: str = ""
    message: str = ""
    episode_id: Optional[str] = None


@dataclass(frozen=True, slots=True)
class GridCell:
    """Per-bed, per-time result bundle produced by the orchestrator."""

    bed: int
    encounter: str
    t: datetime
    results: dict[str, RuleResult] = field(default_factory=dict)
    combined_message: str = ""
    feed_alert: bool = False
    display_text: str = ""
    workflow_states: dict[str, WorkflowState] = field(default_factory=dict)
