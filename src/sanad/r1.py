"""R1 -- SBT screen review candidate (for the doctor).

Pure, deterministic evaluation of the configured SBT *screen* on the fixed
synthetic dataset. R1 never establishes SBT or extubation readiness; it reports
whether the recorded data match a configured screen for long enough that a
clinician should review the patient (``docs/EVIDENCE.md`` R1; requirements
Section 2).

The screen is criteria **0** and **a-f** from the frozen baseline, all of which
must hold continuously for **more than 120 min** before R1 is ``met``
(criterion ``R1-⏱``). Each criterion resolves to one of a small set of
sub-outcomes; the shared rules of the baseline then combine them into exactly
one :class:`~sanad.states.EvaluationState` with a reason code:

* an excluded **pathway** (ECMO, chronic ventilation / long-term tracheostomy,
  prone, documented deep sedation, unstable ICP, comfort-only) ->
  ``not_applicable``; **DNR alone is never an exclusion** (R1-pathways);
* **stale** observations (newest > 15 min old) -> ``unknown``/``stale_data``
  for this observation-based rule (AC-DEF-5);
* the **context gate** R1-f (RR > 35, or pH < 7.30 where measured) ->
  ``not_met``/``context_review`` regardless of the other criteria;
* any **missing / unresolved mandatory** item (no SAT, no 12-h reference, no
  valid effort confirmation, an unconfirmed extra pressor, a weight-based dose
  with no weight) -> ``unknown`` naming the item (AC-DEF-7, PBT-1);
* a recorded **negative** (FiO2/PEEP too high, an NMBA infusing, a pressor over
  threshold) -> ``not_met``;
* all criteria satisfied but **not yet 120 min** -> ``not_met`` (building up);
* all criteria satisfied for **> 120 min** -> ``met`` with the approved wording,
  unless an **assessed / deferral** hold covers ``t`` -> ``suppressed`` with the
  hold's review time (R1-episodes).

Clinician confirmations (effort, haemodynamics) are valid for 2 h and end early
if a vasoactive agent starts, stops or changes dose, or sedation increases
(AC-DEF-12); an expired confirmation never satisfies R1-d or R1-e (PBT-11).

Episodes: within one continuous ``met`` run the engine raises a single prompt
regardless of polling rate, duplicate records or midnight (R1-episodes, PBT-4);
:func:`r1_prompt_times` returns the one time per episode a prompt is raised.

Pure: ``(context, t) -> RuleResult``; no I/O, no wall-clock, no mutation of the
inputs. Imports only shared modules (never another rule). Stdlib only.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from enum import Enum
from typing import Iterable, Optional

from .freshness import freshness_gate
from .model import Dataset, Event, Infusion, Observation, RuleResult
from .states import EvaluationState, R1_MET_TEXT, ReasonCode
from .timeline import record_tiebreak, MAX_GAP, duration_held, grid
from .units import UnsupportedUnitError, WeightMissingError, convert_dose

__all__ = [
    "RULE_ID",
    "R1Context",
    "context_for",
    "evaluate_r1",
    "r1_prompt_times",
    "NMBA_DRUGS",
    "EXTRA_VASOACTIVES",
    "EXCLUDED_PATHWAYS",
]

RULE_ID = "R1"

# --- configured thresholds and vocabularies (baseline v3) ------------------

# Criterion a: FiO2 <= 0.5 and PEEP <= 8 cmH2O.
_FIO2_MAX = Decimal("0.5")
_PEEP_MAX = 8

# Criterion e threshold bundle (MODE verbatim).
_SBP_MIN = 90                       # SBP must be strictly greater than this
_NOREPI_MAX = Decimal("10")         # norepinephrine < 10 mcg/min
_DOPA_DOBU_MAX = Decimal("5")       # dopamine / dobutamine < 5 mcg/kg/min

# Criterion f context gate.
_RR_MAX = 35                        # RR > 35 -> not_met
_PH_MIN = Decimal("7.30")           # pH < 7.30 -> not_met (not in the dataset)

# Criterion 0 / confirmation windows.
_SAT_WINDOW = timedelta(hours=12)
_CONFIRM_VALID = timedelta(hours=2)
_REF_LOOKBACK = timedelta(hours=12)   # criterion b reference point
_REF_TOLERANCE = MAX_GAP              # "within 15 min" of t-12h

# Duration: all criteria must hold for *more than* 120 min.
_DURATION_MIN = 120

# Neuromuscular blocking agents (criterion c). Lower-cased drug names.
NMBA_DRUGS = frozenset(
    {"cisatracurium", "rocuronium", "vecuronium", "atracurium",
     "pancuronium", "nmba"}
)

# "Any other vasoactive agent" (criterion e): presence requires a valid
# haemodynamics confirmation (DESIGN: one drug can hide another).
EXTRA_VASOACTIVES = frozenset(
    {"vasopressin", "epinephrine", "adrenaline", "phenylephrine", "milrinone"}
)

# Threshold-bearing pressors handled numerically in criterion e.
_NOREPI = frozenset({"norepinephrine", "noradrenaline"})
_DOPAMINE = frozenset({"dopamine"})
_DOBUTAMINE = frozenset({"dobutamine"})

# Sedatives whose *dose increase* ends a confirmation early (AC-DEF-12).
_SEDATIVES = frozenset({"propofol", "midazolam", "dexmedetomidine", "fentanyl"})

# Pathways that exclude R1 (not_applicable). DNR is deliberately absent.
EXCLUDED_PATHWAYS = frozenset(
    {"vv_ecmo", "va_ecmo", "ecmo", "chronic_ventilation", "long_term_trach",
     "tracheostomy_long_term", "prone", "proning", "deep_sedation",
     "intentional_deep_sedation", "unstable_icp", "raised_icp",
     "comfort_only", "comfort_care"}
)

# Effort / haemodynamics values that count as a positive confirmation.
_EFFORT_OK = frozenset({"adequate", "present", "spontaneous"})
_HAEMO_OK = frozenset({"acceptable", "stable", "ok"})


# --- per-encounter context -------------------------------------------------


@dataclass(frozen=True, slots=True)
class R1Context:
    """Everything R1 needs for one encounter, filtered to that encounter.

    Pure data: the evaluation reads only these records (plus the explicit grid
    time ``t``), so it never touches wall-clock or other encounters.
    """

    encounter: str
    bed: int
    weight_kg: Optional[int]
    code_status: str
    pathways: tuple[str, ...]
    observations: tuple[Observation, ...]
    infusions: tuple[Infusion, ...]
    events: tuple[Event, ...]
    # pH is not carried in the fixed dataset (the ABG feed is out of scope), so
    # it defaults to ``None`` and no oracle scenario supplies it. It is exposed
    # here only so the R1-f pH < 7.30 gate (``docs/EVIDENCE.md`` R1-f) can be
    # exercised end to end through the public evaluator by a unit test.
    ph: Optional[Decimal] = None


def context_for(ds: Dataset, encounter: str) -> R1Context:
    """Build an :class:`R1Context` for one encounter from a loaded dataset."""

    enc = ds.by_encounter[encounter]
    return R1Context(
        encounter=encounter,
        bed=enc.bed,
        weight_kg=enc.weight_kg,
        code_status=enc.code_status,
        pathways=enc.pathways,
        observations=tuple(o for o in ds.observations if o.encounter == encounter),
        infusions=tuple(i for i in ds.infusions if i.encounter == encounter),
        events=tuple(e for e in ds.events if e.encounter == encounter),
    )


# --- small sub-outcome type for a single criterion -------------------------


class _Sub(Enum):
    SATISFIED = "satisfied"
    NOT_MET = "not_met"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class _Crit:
    """One criterion's outcome, with the reason/detail if it blocks ``met``."""

    outcome: _Sub
    reason: ReasonCode = ReasonCode.OK_NOT_MET
    detail: str = ""


_SAT = _Crit(_Sub.SATISFIED)


# --- helpers ---------------------------------------------------------------


def _infusion_active(inf: Infusion, t: datetime) -> bool:
    """True when ``inf`` is running at ``t`` (half-open ``[start, end)``)."""

    return inf.start <= t < inf.end


def _active_infusions(ctx: R1Context, t: datetime) -> list[Infusion]:
    return [i for i in ctx.infusions if _infusion_active(i, t)]


def _visible_obs(ctx: R1Context, t: datetime) -> list[Observation]:
    """Observations visible at ``t`` (documented <= t), sorted by event time.

    Observations in this dataset are documented at their event time, so the
    visibility gate is ``event_time <= t``. Each encounter has at most one
    observation per event time, so sorting by ``(event_time, repr)`` is a total,
    deterministic order equivalent to :func:`sanad.timeline.as_known_at` here
    while avoiding an O(n log n) ``repr`` sort of the whole set on every call.
    """

    visible = [o for o in ctx.observations if o.documented_time <= t]
    visible.sort(key=lambda o: (o.event_time, record_tiebreak(o)))
    return visible


def _newest_fresh(ctx: R1Context, t: datetime) -> Optional[Observation]:
    """The newest observation visible at ``t`` (as-known-at)."""

    visible = _visible_obs(ctx, t)
    return visible[-1] if visible else None


# --- criterion 0: SAT within the previous 12 h -----------------------------


def _crit_0_sat(ctx: R1Context, t: datetime) -> _Crit:
    sats = [
        e for e in ctx.events
        if e.type == "sat"
        and e.event_time is not None
        and e.documented_time is not None
        and e.documented_time <= t
        and (e.result or "").strip().lower() in ("pass", "not_indicated")
    ]
    if not sats:
        return _Crit(_Sub.UNKNOWN, ReasonCode.SAT_NOT_RECORDED, "no SAT recorded")
    latest = max(sats, key=lambda e: e.event_time)  # type: ignore[arg-type]
    age = t - latest.event_time  # type: ignore[operator]
    if age > _SAT_WINDOW:
        return _Crit(
            _Sub.UNKNOWN, ReasonCode.SAT_NOT_RECORDED,
            f"latest SAT {latest.event_time.isoformat()} older than 12 h",  # type: ignore[union-attr]
        )
    return _SAT


# --- criterion a: FiO2 <= 0.5 and PEEP <= 8 --------------------------------


def _crit_a_fio2_peep(obs: Observation) -> _Crit:
    if obs.fio2_fraction <= _FIO2_MAX and obs.peep <= _PEEP_MAX:
        return _SAT
    return _Crit(
        _Sub.NOT_MET, ReasonCode.OK_NOT_MET,
        f"FiO2 {obs.fio2_fraction} / PEEP {obs.peep} above screen",
    )


# --- criterion b: FiO2 and PEEP <= their value ~12 h earlier ---------------


def _reference_near(ctx: R1Context, t: datetime) -> Optional[Observation]:
    """The observation nearest ``t-12h`` within 15 min, as known at ``t``."""

    target = t - _REF_LOOKBACK
    visible = _visible_obs(ctx, t)
    best: Optional[Observation] = None
    best_gap: Optional[timedelta] = None
    for o in visible:
        gap = abs(o.event_time - target)
        if gap > _REF_TOLERANCE:
            continue
        # Nearest wins; ties broken by the earlier event time (deterministic).
        if best_gap is None or gap < best_gap:
            best, best_gap = o, gap
    return best


def _crit_b_twelve_h(
    ctx: R1Context, t: datetime, obs: Observation, *, ref_missing_ok: bool = False
) -> _Crit:
    ref = _reference_near(ctx, t)
    if ref is None:
        # At the real evaluation time a missing reference is ``unknown``
        # (AC-DEF-7). During the *continuity* look-back (``ref_missing_ok``) the
        # reference may simply predate the dataset, which is not a recorded
        # worsening, so it must not break an otherwise-held run: the criterion
        # that genuinely starts the clock (e.g. the SAT) still dominates. A
        # recorded *worsening* below still breaks the run in both modes.
        if ref_missing_ok:
            return _SAT
        return _Crit(
            _Sub.UNKNOWN, ReasonCode.TWELVE_H_REF_MISSING,
            "no observation within 15 min of t-12h",
        )
    if obs.fio2_fraction <= ref.fio2_fraction and obs.peep <= ref.peep:
        return _SAT
    return _Crit(
        _Sub.NOT_MET, ReasonCode.OK_NOT_MET,
        "FiO2/PEEP not <= their value 12 h earlier",
    )


# --- criterion c: no NMBA infusing -----------------------------------------


def _crit_c_nmba(ctx: R1Context, t: datetime) -> _Crit:
    for inf in _active_infusions(ctx, t):
        if inf.drug.strip().lower() in NMBA_DRUGS:
            return _Crit(
                _Sub.NOT_MET, ReasonCode.NMBA_INFUSING,
                f"{inf.drug} infusing",
            )
    return _SAT


# --- clinician confirmation validity (AC-DEF-12) ---------------------------


def _active_dose_at(
    ctx: R1Context, drug: str, t: datetime, *, exclude: Optional[Infusion] = None
) -> Optional[Decimal]:
    """Dose (raw, in its own unit) of ``drug`` running at ``t``, or ``None``.

    ``t`` uses the half-open ``[start, end)`` rule. ``exclude`` lets the caller
    ignore the very row whose start is being judged. When more than one row of
    the same drug overlaps ``t`` (should not happen in this dataset) the highest
    dose is returned, so a concurrent higher rate is never missed.
    """

    best: Optional[Decimal] = None
    for inf in ctx.infusions:
        if exclude is not None and inf is exclude:
            continue
        if inf.drug.strip().lower() != drug:
            continue
        if not _infusion_active(inf, t):
            continue
        dose = _to_decimal_dose(inf.dose)
        if best is None or dose > best:
            best = dose
    return best


def _is_sedation_increase(
    ctx: R1Context, inf: Infusion, start: datetime
) -> bool:
    """True when sedative row ``inf`` (starting in the interval) is an increase.

    Per the baseline, a confirmation ends early only when *sedation increases*
    (``docs/EVIDENCE.md`` R1 confirmations), not when a sedative is started at a
    lower rate, decreased, or stopped. ``inf`` is an increase when no infusion
    of the same sedative was running at ``start`` (a new start from zero) or
    when its dose is strictly greater than the same sedative's dose active at
    ``start``. If the two doses are charted in units that cannot be compared,
    the change is treated conservatively as an increase (cannot prove it is a
    decrease).
    """

    drug = inf.drug.strip().lower()
    prior = _active_dose_at(ctx, drug, start, exclude=inf)
    if prior is None:
        # No same-drug sedative running at ``start`` -> a new start is an
        # increase from zero.
        return True
    # Same drug in this dataset always carries the same (mcg/kg/min) unit, so a
    # direct Decimal dose comparison is exact. A differing unit would make the
    # comparison unsafe; fall back to treating it as an increase.
    prior_unit = None
    for other in ctx.infusions:
        if other is inf:
            continue
        if other.drug.strip().lower() == drug and _infusion_active(other, start):
            prior_unit = other.unit.strip().lower()
            break
    if prior_unit is not None and prior_unit != inf.unit.strip().lower():
        return True
    return _to_decimal_dose(inf.dose) > prior


def _confirmation_invalidated_between(
    ctx: R1Context, start: datetime, t: datetime
) -> bool:
    """A vasoactive start/stop/dose-change or sedation increase in ``(start, t]``.

    Such an event ends an earlier confirmation's validity early (AC-DEF-12),
    so a confirmation recorded at ``start`` can no longer be relied on at ``t``.
    A sedative that *starts, decreases or stops* does not end validity: only a
    sedation *increase* does (``docs/EVIDENCE.md`` R1 confirmations).
    """

    for inf in ctx.infusions:
        drug = inf.drug.strip().lower()
        is_vaso = (
            drug in EXTRA_VASOACTIVES or drug in _NOREPI
            or drug in _DOPAMINE or drug in _DOBUTAMINE
        )
        # A vasoactive start or stop inside the interval ends validity.
        if is_vaso:
            if start < inf.start <= t:
                return True
            if start < inf.end <= t:
                return True
        # A sedation *increase* ends validity. A sedative row beginning in the
        # interval only counts when it is a new start from zero or a strictly
        # higher dose than the same sedative running at ``start`` -- a start at
        # a lower rate, a decrease or a stop must not end validity.
        if drug in _SEDATIVES and start < inf.start <= t:
            if _is_sedation_increase(ctx, inf, start):
                return True
    return False


def _latest_valid_confirmation(
    ctx: R1Context, t: datetime, field: str
) -> tuple[Optional[str], bool]:
    """Return ``(value, expired)`` for the latest confirmation of ``field``.

    ``field`` is ``"effort"`` or ``"haemodynamics"``. ``value`` is the recorded
    assessment of the latest vent_check visible at ``t`` whose performed time is
    at or before ``t``; ``expired`` is True when that confirmation is older than
    2 h or was ended early by a vasoactive/sedation change (AC-DEF-12, PBT-11).
    ``value`` is ``None`` when no confirmation was ever recorded.
    """

    checks = [
        e for e in ctx.events
        if e.type == "vent_check"
        and e.performed_at is not None
        and e.documented_at is not None
        and e.documented_at <= t
        and e.performed_at <= t
    ]
    if not checks:
        return None, False
    latest = max(checks, key=lambda e: e.performed_at)  # type: ignore[arg-type]
    value = getattr(latest, field)
    performed = latest.performed_at
    assert performed is not None
    expired = (t - performed) > _CONFIRM_VALID
    if not expired and _confirmation_invalidated_between(ctx, performed, t):
        expired = True
    return value, expired


# --- criterion d: valid adequate-effort confirmation -----------------------


def _crit_d_effort(ctx: R1Context, t: datetime) -> _Crit:
    value, expired = _latest_valid_confirmation(ctx, t, "effort")
    if value is None:
        return _Crit(
            _Sub.UNKNOWN, ReasonCode.MISSING_ITEM,
            "no effort confirmation recorded",
        )
    if expired:
        return _Crit(
            _Sub.UNKNOWN, ReasonCode.CONFIRMATION_EXPIRED,
            "effort confirmation expired",
        )
    if value.strip().lower() in _EFFORT_OK:
        return _SAT
    # A recorded, non-positive assessment is a recorded negative.
    return _Crit(
        _Sub.NOT_MET, ReasonCode.OK_NOT_MET,
        f"effort recorded as {value!r}",
    )


# --- criterion e: haemodynamics --------------------------------------------


def _pressor_mcg_per_min(
    inf: Infusion, weight_kg: Optional[int]
) -> Decimal:
    """Absolute mcg/min for a threshold pressor, converting mcg/kg/min.

    Used for the norepinephrine ``< 10 mcg/min`` threshold (baseline R1-e).
    Raises :class:`~sanad.units.WeightMissingError` when a weight-based dose has
    no weight (AC-DEF-9) and :class:`~sanad.units.UnsupportedUnitError` for an
    unresolvable unit; the caller turns either into ``unknown``.
    """

    return convert_dose(inf.dose, inf.unit, weight_kg)


def _pressor_mcg_per_kg_per_min(
    inf: Infusion, weight_kg: Optional[int]
) -> Decimal:
    """Weight-indexed mcg/kg/min for the dopamine / dobutamine threshold.

    The baseline threshold for dopamine and dobutamine is ``< 5 mcg/kg/min``
    (``docs/EVIDENCE.md`` R1-e), so the comparison must be in mcg/kg/min, not
    absolute mcg/min. A dose already charted in ``mcg/kg/min`` needs no numeric
    conversion, but the threshold itself is weight-based, so a recorded weight
    is still required; a dose charted in ``mcg/min`` is divided by the recorded
    weight to obtain mcg/kg/min. Either way the threshold is weight-based, so a
    missing weight raises :class:`~sanad.units.WeightMissingError` ->
    ``unknown``/``weight_missing`` (AC-DEF-9; never a guessed weight). An
    unresolvable unit raises :class:`~sanad.units.UnsupportedUnitError` ->
    ``unknown``.
    """

    unit = inf.unit.strip().lower()
    if unit == "mcg/kg/min":
        # Already weight-indexed, but the dopamine/dobutamine threshold is
        # weight-based: without a recorded weight the engine cannot establish
        # that the configured mcg/kg/min comparison is valid for this patient
        # (missing means unknown, never a guessed weight -- shared "Units"
        # definition and AC-DEF-9). A recorded weight is required even though
        # the dose needs no numeric conversion.
        if weight_kg is None:
            raise WeightMissingError(
                "dopamine/dobutamine threshold is weight-based (mcg/kg/min) "
                "but no weight is recorded"
            )
        return _to_decimal_dose(inf.dose)
    if unit == "mcg/min":
        if weight_kg is None:
            raise WeightMissingError(
                "dopamine/dobutamine threshold is weight-based (mcg/kg/min) "
                "but no weight is recorded"
            )
        # convert_dose(mcg/min) is a pass-through; divide by weight to index it.
        absolute = convert_dose(inf.dose, inf.unit, weight_kg)
        return absolute / _to_decimal_dose(weight_kg)
    # Any other unit has no mcg/kg/min meaning: explicit error, never a guess.
    raise UnsupportedUnitError(
        f"unsupported dose unit {inf.unit!r} for a mcg/kg/min threshold"
    )


def _to_decimal_dose(value: object) -> Decimal:
    """Exact Decimal for a dose/weight value without a binary-float detour."""

    if isinstance(value, Decimal):
        return value
    if isinstance(value, float):
        return Decimal(repr(value))
    return Decimal(str(value))


def _crit_e_haemo(ctx: R1Context, t: datetime, obs: Observation) -> _Crit:
    # Threshold part: SBP must be > 90 on the fresh observation.
    if obs.sbp <= _SBP_MIN:
        return _Crit(
            _Sub.NOT_MET, ReasonCode.OK_NOT_MET,
            f"SBP {obs.sbp} not > {_SBP_MIN}",
        )

    active = _active_infusions(ctx, t)
    extra_present: list[str] = []
    for inf in active:
        drug = inf.drug.strip().lower()
        if drug in _NOREPI:
            try:
                dose = _pressor_mcg_per_min(inf, ctx.weight_kg)
            except WeightMissingError:
                return _Crit(
                    _Sub.UNKNOWN, ReasonCode.WEIGHT_MISSING,
                    f"{inf.drug} dose needs a weight",
                )
            except UnsupportedUnitError:
                return _Crit(
                    _Sub.UNKNOWN, ReasonCode.UNSUPPORTED_UNIT,
                    f"{inf.drug} unit {inf.unit!r} unsupported",
                )
            if dose >= _NOREPI_MAX:
                return _Crit(
                    _Sub.NOT_MET, ReasonCode.OK_NOT_MET,
                    f"norepinephrine {dose} mcg/min not < {_NOREPI_MAX}",
                )
        elif drug in _DOPAMINE or drug in _DOBUTAMINE:
            try:
                dose = _pressor_mcg_per_kg_per_min(inf, ctx.weight_kg)
            except WeightMissingError:
                return _Crit(
                    _Sub.UNKNOWN, ReasonCode.WEIGHT_MISSING,
                    f"{inf.drug} dose needs a weight",
                )
            except UnsupportedUnitError:
                return _Crit(
                    _Sub.UNKNOWN, ReasonCode.UNSUPPORTED_UNIT,
                    f"{inf.drug} unit {inf.unit!r} unsupported",
                )
            if dose >= _DOPA_DOBU_MAX:
                return _Crit(
                    _Sub.NOT_MET, ReasonCode.OK_NOT_MET,
                    f"{inf.drug} {dose} mcg/kg/min not < {_DOPA_DOBU_MAX}",
                )
        elif drug in EXTRA_VASOACTIVES:
            extra_present.append(inf.drug)

    if extra_present:
        # An extra agent requires a valid haemodynamics confirmation. Display
        # *all* active agents (sorted, de-duplicated) so one drug cannot hide
        # another -- bed 3 shows both norepinephrine and vasopressin.
        value, expired = _latest_valid_confirmation(ctx, t, "haemodynamics")
        agents = ", ".join(sorted({i.drug for i in active}))
        if value is None or expired or value.strip().lower() not in _HAEMO_OK:
            return _Crit(
                _Sub.UNKNOWN, ReasonCode.HAEMO_UNCONFIRMED,
                f"extra vasoactive present; agents: {agents}",
            )
    return _SAT


# --- criterion f: context gate (RR > 35, pH < 7.30) ------------------------


def _crit_f_gate(obs: Observation, ph: Optional[Decimal] = None) -> Optional[_Crit]:
    """Return a blocking ``not_met`` when the context gate fires, else ``None``.

    The gate is a pre-screen: if it fires it dominates every other criterion
    (R1-f). pH is not in the dataset, so it is only ever supplied by a unit
    test.
    """

    if obs.rr > _RR_MAX:
        return _Crit(
            _Sub.NOT_MET, ReasonCode.CONTEXT_REVIEW,
            f"RR {obs.rr} > {_RR_MAX}",
        )
    if ph is not None and ph < _PH_MIN:
        return _Crit(
            _Sub.NOT_MET, ReasonCode.CONTEXT_REVIEW,
            f"pH {ph} < {_PH_MIN}",
        )
    return None


# --- pathways --------------------------------------------------------------


def _excluded_pathway(ctx: R1Context) -> Optional[str]:
    for p in ctx.pathways:
        if p.strip().lower() in EXCLUDED_PATHWAYS:
            return p
    return None


# --- active hold (assessed / deferral) -------------------------------------


@dataclass(frozen=True, slots=True)
class _Hold:
    until: datetime
    reason: str
    owner: str


def _active_hold(ctx: R1Context, t: datetime) -> Optional[_Hold]:
    """The latest R1 deferral/assessed hold covering ``t``, or ``None``.

    A ``deferral`` (rule R1) recorded at ``d`` with ``until`` suppresses R1 over
    ``[d, until)``; at ``until`` the hold lapses and R1 re-evaluates, possibly
    starting a new episode (R1-episodes). A ``staff_action`` of ``assessed``
    acts like a deferral with a default review window is *not* assumed here --
    only explicit deferrals carry an ``until``. Only records visible at ``t``
    (documented) are considered.
    """

    best: Optional[_Hold] = None
    best_start: Optional[datetime] = None
    for e in ctx.events:
        if e.type != "deferral":
            continue
        if (e.rule or "").strip().upper() not in ("R1", ""):
            continue
        start = e.event_time
        if start is None or e.documented_time is None or e.documented_time > t:
            continue
        if e.until is None:
            continue
        if start <= t < e.until:
            if best_start is None or start > best_start:
                best = _Hold(
                    until=e.until,
                    reason=e.reason or "",
                    owner=e.owner or "",
                )
                best_start = start
    return best


# --- full single-criterion bundle ------------------------------------------


def _all_criteria_satisfied(
    ctx: R1Context, t: datetime, *, for_duration: bool = False
) -> bool:
    """True when every criterion 0, a-f is *satisfied* on fresh data at ``t``.

    Used to build the duration sample set; does not apply the gate/pathway/hold
    logic (those are handled in :func:`evaluate_r1`). Returns ``False`` whenever
    data are stale, a criterion is unknown or not_met, or the gate fires.

    ``for_duration`` relaxes only criterion b's *missing-reference* case (a 12-h
    reference that predates the dataset is not a recorded worsening, so it must
    not break the continuity run that the SAT or another criterion anchors). A
    recorded worsening still breaks the run.
    """

    if _excluded_pathway(ctx) is not None:
        return False
    gate = freshness_gate(ctx.observations, t, ctx.events)
    if gate.stale:
        return False
    obs = _newest_fresh(ctx, t)
    if obs is None:
        return False
    if _crit_f_gate(obs, ctx.ph) is not None:
        return False
    crits = (
        _crit_0_sat(ctx, t),
        _crit_a_fio2_peep(obs),
        _crit_b_twelve_h(ctx, t, obs, ref_missing_ok=for_duration),
        _crit_c_nmba(ctx, t),
        _crit_d_effort(ctx, t),
        _crit_e_haemo(ctx, t, obs),
    )
    return all(c.outcome is _Sub.SATISFIED for c in crits)


def _duration_satisfied(ctx: R1Context, t: datetime) -> bool:
    """Have all criteria held continuously for more than 120 min ending at t?

    The samples are the grid points at or before ``t`` where every criterion is
    satisfied; :func:`~sanad.timeline.duration_held` applies the 15-min gap rule
    and the strict "more than" comparison so R1 fires at the first grid point
    *after* 120 min (R1-⏱). The look-back uses ``for_duration=True`` so a 12-h
    reference that predates the dataset does not spuriously shorten the run.
    """

    samples = [
        g for g in grid(t - timedelta(minutes=_DURATION_MIN) - MAX_GAP, t)
        if _all_criteria_satisfied(ctx, g, for_duration=True)
    ]
    return duration_held(
        samples, t, min_minutes=_DURATION_MIN, strictly_more=True,
    )


# --- the public evaluation -------------------------------------------------


def evaluate_r1(ctx: R1Context, t: datetime) -> RuleResult:
    """Evaluate R1 for one encounter at grid time ``t`` -> one state + reason.

    The combination order below is the baseline's safety ordering: a pathway
    exclusion and stale data come before the gate; the gate comes before any
    missing/negative criterion; a missing mandatory item (``unknown``) is
    reported before a plain negative; and ``met`` is reached only when every
    criterion is satisfied for more than 120 min and no hold is active.
    """

    # 1. Excluded pathway -> not_applicable (DNR alone never excludes).
    excluded = _excluded_pathway(ctx)
    if excluded is not None:
        return RuleResult(
            rule_id=RULE_ID,
            state=EvaluationState.NOT_APPLICABLE,
            reason=ReasonCode.PATHWAY_EXCLUDED,
            detail=f"pathway {excluded}",
        )

    # 2. Stale / absent observations -> unknown (stale_data), feed alert.
    gate = freshness_gate(ctx.observations, t, ctx.events)
    if gate.stale:
        return gate.as_unknown(RULE_ID)

    obs = _newest_fresh(ctx, t)
    if obs is None:  # pragma: no cover - stale already covers this
        return RuleResult(
            rule_id=RULE_ID, state=EvaluationState.UNKNOWN,
            reason=ReasonCode.STALE_DATA, detail="no observation recorded",
        )

    # 3. Context gate (R1-f) dominates everything else.
    gate_crit = _crit_f_gate(obs, ctx.ph)
    if gate_crit is not None:
        return RuleResult(
            rule_id=RULE_ID, state=EvaluationState.NOT_MET,
            reason=gate_crit.reason, detail=gate_crit.detail,
        )

    # 4. Evaluate the criteria once.
    c0 = _crit_0_sat(ctx, t)
    ca = _crit_a_fio2_peep(obs)
    cb = _crit_b_twelve_h(ctx, t, obs)
    cc = _crit_c_nmba(ctx, t)
    cd = _crit_d_effort(ctx, t)
    ce = _crit_e_haemo(ctx, t, obs)

    # 5. Any ``unknown`` dominates a plain ``not_met`` (missing vs negative,
    #    AC-DEF-7, PBT-1). Deterministic priority: SAT, haemodynamics/weight,
    #    effort, 12-h reference -- matching the oracle (bed 2 sat_not_recorded;
    #    bed 3 haemo_unconfirmed; bed 14 weight_missing).
    for crit in (c0, ce, cd, cb):
        if crit.outcome is _Sub.UNKNOWN:
            return RuleResult(
                rule_id=RULE_ID, state=EvaluationState.UNKNOWN,
                reason=crit.reason, detail=crit.detail,
            )

    # 6. Any recorded negative -> not_met.
    for crit in (ca, cb, cc, cd, ce):
        if crit.outcome is _Sub.NOT_MET:
            return RuleResult(
                rule_id=RULE_ID, state=EvaluationState.NOT_MET,
                reason=crit.reason, detail=crit.detail,
            )

    # 7. All criteria satisfied. Check the > 120 min duration.
    if not _duration_satisfied(ctx, t):
        return RuleResult(
            rule_id=RULE_ID, state=EvaluationState.NOT_MET,
            reason=ReasonCode.OK_NOT_MET,
            detail="criteria hold; duration not yet > 120 min",
        )

    # 8. Met -- but an active hold suppresses the routine prompt.
    hold = _active_hold(ctx, t)
    if hold is not None:
        return RuleResult(
            rule_id=RULE_ID, state=EvaluationState.SUPPRESSED,
            reason=ReasonCode.HELD_DEFERRED,
            detail=(
                f"deferred until {hold.until.isoformat()}"
                + (f" ({hold.reason})" if hold.reason else "")
                + (f" by {hold.owner}" if hold.owner else "")
            ),
        )

    # 9. Met: present the approved wording. The per-episode prompt (and its
    #    episode id) is derived over the grid by :func:`r1_prompt_times`; the
    #    per-``t`` result stays O(1) in the number of grid points, so the
    #    orchestrator can evaluate the whole night cheaply.
    return RuleResult(
        rule_id=RULE_ID, state=EvaluationState.MET,
        reason=ReasonCode.OK_NOT_MET, detail="", message=R1_MET_TEXT,
    )


def _is_met_point(ctx: R1Context, t: datetime) -> bool:
    """True when R1 resolves to ``met`` at ``t`` (not suppressed)."""

    if _excluded_pathway(ctx) is not None:
        return False
    gate = freshness_gate(ctx.observations, t, ctx.events)
    if gate.stale:
        return False
    if _active_hold(ctx, t) is not None:
        return False
    if not _all_criteria_satisfied(ctx, t):
        return False
    return _duration_satisfied(ctx, t)


def r1_prompt_times(ctx: R1Context, points: Iterable[datetime]) -> list[datetime]:
    """Return the one grid time per ``met`` episode a prompt is raised.

    Walking the grid in order, a prompt is raised at the first ``met`` point of
    each contiguous ``met`` run; a run is broken by any non-``met`` point
    (suppressed, not_met, unknown, not_applicable, stale). This yields exactly
    one prompt per episode regardless of polling rate, duplicate records or
    midnight (R1-episodes, PBT-4): bed 1 -> one prompt; bed 15 -> two prompts.
    """

    prompts: list[datetime] = []
    prev_met = False
    for t in points:
        met = _is_met_point(ctx, t)
        if met and not prev_met:
            prompts.append(t)
        prev_met = met
    return prompts
