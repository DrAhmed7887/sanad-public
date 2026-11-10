"""R2a -- oxygenation trend review (independent of fluid balance).

Pure, deterministic evaluation of the configured *oxygenation trend* on the
fixed synthetic dataset. R2a never establishes deterioration and is **not an
emergency alarm**; its thresholds are DESIGN demo values (``docs/EVIDENCE.md``
R2a; requirements Section 3). It surfaces worsening oxygenation *independently*
of fluid balance so a flash event is never masked by a quiet fluid ledger
(AC-R2a-fluid-independent, PBT-5).

Two branches, either of which makes R2a ``met`` (``docs/EVIDENCE.md`` R2a):

* **Settings branch** -- FiO2 is at least ``0.10`` above its 6-hour minimum, or
  PEEP is at least ``2`` cmH2O above its 6-hour minimum, sustained for at least
  30 min. The 6-hour minimum **excludes tagged planned-change windows**
  (pre-oxygenation, recruitment, proning): a transient spike inside a tag must
  not depress the minimum and then read as an elevation when the tag ends, and
  a reading taken *inside* a tag is itself excluded from the sustained-elevation
  samples (AC-R2a-settings; bed 4 would fire 02:50; bed 8 not_met).
* **SpO2 branch** -- good-quality SpO2 is at least ``3`` points below the median
  of good-quality SpO2 over the previous 6 h, sustained for at least 5 min,
  whether or not a target is documented; the target is shown when present. A
  planned-change tag **never** suppresses this branch (AC-R2a-spo2,
  AC-R2a-quality, AC-R2a-tags-spo2, PBT-12; bed 4 met 02:20, bed 6 met 01:05,
  bed 7 not_met -- artefact ignored, bed 16 met 03:05 during tagged suctioning).

Gating, in the baseline's safety order:

* an excluded **pathway** (ECMO, comfort-only care) -> ``not_applicable``
  (AC-R2a-na);
* fewer than **6 h of history** on this encounter -> ``unknown`` /
  ``insufficient_history`` (AC-R2a-hist);
* **stale** observations (newest > 15 min old) -> ``unknown`` / ``stale_data``
  for this observation-based rule (AC-DEF-5);
* otherwise either branch ``met`` -> ``met`` (fluid-independent; the detail
  lists the firing branch and the SpO2 target, and the orchestrator appends the
  "fluid balance unknown" label for that cell only when R2b is ``unknown`` --
  D29, since whether the fluid ledger is incomplete is R2b's result, not R2a's);
  if neither branch is ``met`` **and** neither branch has any usable in-window
  datum (no good-quality SpO2 *and* no untagged settings sample in the last 6 h)
  -> ``unknown`` / ``missing_item`` (missing is never a silent ``not_met``);
  otherwise -> ``not_met``.

Pure: ``(context, t) -> RuleResult``; no I/O, no wall-clock, no mutation of the
inputs. Imports only shared modules (never another rule). Stdlib only.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from statistics import median
from typing import Optional

from .freshness import freshness_gate
from .model import Dataset, Event, Observation, RuleResult
from .states import EvaluationState, ReasonCode
from .timeline import MAX_GAP, duration_held, record_tiebreak

__all__ = [
    "RULE_ID",
    "R2aContext",
    "context_for",
    "evaluate_r2a",
    "SETTINGS_BRANCH",
    "SPO2_BRANCH",
    "FLUID_UNKNOWN_LABEL",
    "GOOD_QUALITY",
    "TAGGED_REASONS",
    "EXCLUDED_PATHWAYS",
]

RULE_ID = "R2a"

# --- configured thresholds (DESIGN demo values, baseline v3) ----------------

# Settings branch: FiO2 >= +0.10 above the 6-h minimum, or PEEP >= +2 above it,
# sustained for at least 30 min.
_FIO2_RISE = Decimal("0.10")
_PEEP_RISE = 2
_SETTINGS_MIN_MINUTES = 30

# SpO2 branch: good-quality SpO2 >= 3 points below the 6-h good-quality median,
# sustained for at least 5 min.
_SPO2_DROP = 3
_SPO2_MIN_MINUTES = 5

# History and look-back windows.
_HISTORY = timedelta(hours=6)
_LOOKBACK = timedelta(hours=6)

# SpO2 sample quality that counts. Anything else is ignored in the SpO2 branch
# (bed 7's "poor" artefact at 03:00/03:01:30).
GOOD_QUALITY = "good"

# Branch labels carried in ``RuleResult.detail`` when ``met``.
SETTINGS_BRANCH = "settings branch"
SPO2_BRANCH = "SpO2 branch"

# R2a is independent of fluid balance; the orchestrator appends this label to
# R2a's ``met`` detail for a cell only when R2b is ``unknown`` on the same data
# (the baseline applies it "if fluid data are missing or incomplete" -- that
# condition is R2b's result, which R2a cannot see). R2a itself never adds it
# (D29). The combined R2a+R2b message is assembled separately by the
# orchestrator when both are ``met`` (task 6).
FLUID_UNKNOWN_LABEL = "fluid balance unknown"

# Planned-change reasons whose windows are excluded from the settings branch's
# 6-hour minimum (matched case-insensitively on a substring; the dataset uses
# free-text reasons such as "pre-oxygenation for suctioning", "suctioning").
TAGGED_REASONS = frozenset(
    {"pre-oxygenation", "preoxygenation", "pre oxygenation", "recruitment",
     "proning", "prone", "suctioning", "suction"}
)

# Pathways that make R2a not_applicable (ECMO, comfort-only care). Unlike R2b,
# ECMO *does* exclude R2a (AC-R2a-na).
EXCLUDED_PATHWAYS = frozenset(
    {"vv_ecmo", "va_ecmo", "ecmo", "comfort_only", "comfort_care"}
)


# --- per-encounter context --------------------------------------------------


@dataclass(frozen=True, slots=True)
class R2aContext:
    """Everything R2a needs for one encounter, filtered to that encounter.

    Pure data: the evaluation reads only these records (plus the explicit grid
    time ``t``). R2a deliberately carries **no fluid records** -- it is
    independent of fluid balance by construction (AC-R2a-fluid-independent,
    PBT-5). ``spo2_target`` is optional and shown when present; no oracle bed
    documents one, so it defaults to ``None``.
    """

    encounter: str
    bed: int
    pathways: tuple[str, ...]
    observations: tuple[Observation, ...]
    events: tuple[Event, ...]
    spo2_target: Optional[int] = None


def context_for(ds: Dataset, encounter: str) -> R2aContext:
    """Build an :class:`R2aContext` for one encounter from a loaded dataset."""

    enc = ds.by_encounter[encounter]
    return R2aContext(
        encounter=encounter,
        bed=enc.bed,
        pathways=enc.pathways,
        observations=tuple(o for o in ds.observations if o.encounter == encounter),
        events=tuple(e for e in ds.events if e.encounter == encounter),
    )


# --- helpers ----------------------------------------------------------------


def _visible_obs(ctx: R2aContext, t: datetime) -> list[Observation]:
    """Observations visible at ``t`` (documented <= t), sorted by event time.

    Observations in this dataset are documented at their event time, so the
    visibility gate is ``event_time <= t``. Sorting by ``(event_time, repr)``
    is a total, deterministic order (equivalent here to
    :func:`sanad.timeline.as_known_at`) that keeps duplicate/odd input order
    from changing a result.
    """

    visible = [o for o in ctx.observations if o.documented_time <= t]
    visible.sort(key=lambda o: (o.event_time, record_tiebreak(o)))
    return visible


def _excluded_pathway(ctx: R2aContext) -> Optional[str]:
    for p in ctx.pathways:
        if p.strip().lower() in EXCLUDED_PATHWAYS:
            return p
    return None


def _history_span(ctx: R2aContext, t: datetime) -> Optional[timedelta]:
    """How much observation history is available on this encounter at ``t``.

    The span is ``t - earliest visible observation event time``; ``None`` when
    no observation is visible yet. Used for the >= 6 h gate (AC-R2a-hist); a
    newly admitted encounter (bed 13B) stays ``insufficient_history`` until
    exactly 6 h after its first observation.
    """

    visible = _visible_obs(ctx, t)
    if not visible:
        return None
    return t - visible[0].event_time


def _tagged_windows(ctx: R2aContext, t: datetime) -> list[tuple[datetime, datetime]]:
    """Half-open ``[start, end)`` planned-change windows visible at ``t``.

    Only ``planned_change`` events already documented at ``t`` and whose reason
    matches :data:`TAGGED_REASONS` are returned. An open (``None``) end is
    treated as still active to ``t`` (never happens in the dataset, kept safe).
    """

    windows: list[tuple[datetime, datetime]] = []
    for e in ctx.events:
        if e.type != "planned_change":
            continue
        if e.documented_time is None or e.documented_time > t:
            continue
        if e.start is None:
            continue
        reason = (e.reason or "").strip().lower()
        if not any(tag in reason for tag in TAGGED_REASONS):
            continue
        end = e.end if e.end is not None else t + timedelta(microseconds=1)
        windows.append((e.start, end))
    return windows


def _in_tag(windows: list[tuple[datetime, datetime]], when: datetime) -> bool:
    """True when ``when`` falls inside any half-open tagged window."""

    return any(start <= when < end for start, end in windows)


def _settings_has_data(ctx: R2aContext, t: datetime) -> bool:
    """True when at least one *untagged* settings sample sits in ``(t-6h, t]``.

    The settings branch's 6-hour minimum (and its elevation run) is taken over
    untagged in-window samples only. If every in-window sample falls inside a
    tagged planned-change window there is **no usable settings datum** and the
    branch cannot be evaluated -- that is "missing", not a recorded negative
    (safety steering: missing means unknown, never fine; PBT-1).
    """

    visible = _visible_obs(ctx, t)
    if not visible:
        return False
    windows = _tagged_windows(ctx, t)
    window_start = t - _LOOKBACK
    return any(
        window_start < o.event_time <= t and not _in_tag(windows, o.event_time)
        for o in visible
    )


def _spo2_has_data(ctx: R2aContext, t: datetime) -> bool:
    """True when at least one *good-quality* SpO2 sample sits in ``(t-6h, t]``.

    The SpO2 branch ignores poor-quality samples entirely (AC-R2a-quality). If
    every in-window SpO2 sample is poor quality there is **no usable SpO2
    datum** and the branch cannot be evaluated -- "missing", not a recorded
    negative (safety steering: missing means unknown, never fine; PBT-1).
    """

    visible = _visible_obs(ctx, t)
    window_start = t - _LOOKBACK
    return any(
        window_start < o.event_time <= t and _good_spo2(o) for o in visible
    )


# --- settings branch --------------------------------------------------------


def _settings_reference_floor(
    untagged: list[Observation], t: datetime
) -> tuple[Decimal, int]:
    """The FiO2/PEEP 6-h minima the current elevation is measured against.

    The baseline is the **6-hour minimum** (decision D14: a 6-h minimum defeats
    a creeping rise that a "recent stable baseline" would miss). Taken naively
    over ``(t - 6 h, t]`` that minimum would, for a *sustained step change*,
    eventually become the elevated value itself once the pre-change samples age
    out of the sliding window -- so a genuine, still-present elevation would
    silently stop being "elevated" (bed 6's 0.40 baseline ages out and the
    branch would wrongly drop even though FiO2 is still 0.55). That is a
    false-reassurance failure (the top hazard D06): the setting has *not*
    returned to baseline, so R2a must stay met.

    To keep the minimum tied to the patient's established baseline rather than
    to the elevation itself, the 6-h reference window is **anchored to just
    before the onset of the current elevation episode**. The current episode is
    the maximal contiguous (<=15-min-gap) tail of untagged samples that are *at
    or above the newest sample* on both FiO2 and PEEP -- for a step rise
    (bed 6) that is every elevated sample back to the step, for a creeping rise
    (D14) it reaches back over the whole creep, and for settings already back
    at baseline the newest value is the baseline so the episode spans the flat
    history and the anchor cannot step back -- the window then degenerates to
    the plain 6-h minimum. The minima are taken over the 6 h ending at the
    sample immediately before that onset, so a rise that has outlasted 6 h is
    still measured against the pre-rise floor.

    Deterministic and terminating: the anchor only ever moves strictly backward
    in event time, bounded by the number of samples.
    """

    anchor = t
    fio2_min = min(o.fio2_fraction for o in untagged)
    peep_min = min(o.peep for o in untagged)

    while True:
        window = [
            o for o in untagged if anchor - _LOOKBACK < o.event_time <= anchor
        ]
        if not window:
            break
        fio2_min = min(o.fio2_fraction for o in window)
        peep_min = min(o.peep for o in window)

        newest = window[-1]
        # The current elevation episode: the contiguous (<=15-min-gap) tail of
        # untagged samples at or above the newest FiO2 *and* PEEP. Walk back.
        onset_idx = len(window) - 1
        for i in range(len(window) - 2, -1, -1):
            if window[i + 1].event_time - window[i].event_time > MAX_GAP:
                break
            if (
                window[i].fio2_fraction < newest.fio2_fraction
                or window[i].peep < newest.peep
            ):
                break
            onset_idx = i

        onset_time = window[onset_idx].event_time
        before = [o for o in untagged if o.event_time < onset_time]
        if not before:
            # The episode reaches the earliest untagged sample: no earlier
            # baseline to anchor to -> keep the current 6-h minimum.
            break
        new_anchor = before[-1].event_time
        if new_anchor >= anchor:
            break
        anchor = new_anchor

    return fio2_min, peep_min


def _settings_branch_met(ctx: R2aContext, t: datetime) -> bool:
    """FiO2/PEEP sustained >= their 6-h-minimum + rise for at least 30 min?

    The 6-hour minimum is taken over good observations **excluding** samples
    inside a tagged planned-change window, so a transient spike cannot depress
    the minimum (AC-R2a-settings). A sample taken inside a tag is likewise
    excluded from the elevation run (a tagged spike is not a sustained setting
    change). The minimum is the pre-elevation 6-h floor
    (:func:`_settings_reference_floor`), so a *sustained* step rise stays
    "elevated" rather than silently becoming its own baseline once the
    pre-change samples age out (D14; bed 6 stays met to 07:00). The run is
    measured with the shared 15-min gap rule at the "at least 30 min" (``>=``)
    comparison, so the branch is met at onset + 30 min.
    """

    visible = _visible_obs(ctx, t)
    if not visible:
        return False
    windows = _tagged_windows(ctx, t)

    # Untagged samples up to t, kept in event-time order. The elevation run and
    # its onset are measured over these; the reference floor walks back through
    # them to the pre-elevation window (see _settings_reference_floor).
    untagged = [
        o for o in visible
        if o.event_time <= t and not _in_tag(windows, o.event_time)
    ]
    if not untagged:
        return False

    # Only the last 6 h of untagged samples are candidates for the *current*
    # elevation run (the baseline look-back for the reference is handled by the
    # anchored floor, which may reach further back).
    window_start = t - _LOOKBACK
    in_window = [o for o in untagged if window_start < o.event_time <= t]
    if not in_window:
        return False

    fio2_min, peep_min = _settings_reference_floor(untagged, t)
    fio2_threshold = fio2_min + _FIO2_RISE
    peep_threshold = peep_min + _PEEP_RISE

    def _is_elevated(o: Observation) -> bool:
        return o.fio2_fraction >= fio2_threshold or o.peep >= peep_threshold

    # The elevation must be *current* at t: the newest untagged sample must
    # itself be elevated, otherwise the settings have returned to baseline and
    # the branch is no longer met (a trailing recovery within the 15-min gap
    # must not keep the branch alive).
    if not _is_elevated(in_window[-1]):
        return False

    # Samples (untagged, in last 6 h) where FiO2 or PEEP sits at/above
    # threshold.
    elevated = [o.event_time for o in in_window if _is_elevated(o)]
    return duration_held(
        elevated, t, min_minutes=_SETTINGS_MIN_MINUTES, strictly_more=False,
    )


# --- SpO2 branch ------------------------------------------------------------


def _good_spo2(obs: Observation) -> bool:
    return obs.spo2_quality.strip().lower() == GOOD_QUALITY


def _spo2_reference_median(good: list[Observation], t: datetime) -> float:
    """The 6-h good-quality SpO2 median the current desaturation is measured on.

    The baseline is the median of good-quality SpO2 over the previous 6 h
    (``docs/EVIDENCE.md`` R2a; decision D15). Taken naively over ``(t - 6 h,
    t]`` that median would, for a *sustained* desaturation, drift down toward
    the depressed value as the pre-drop samples age out of the sliding window,
    so a genuine, still-present drop would silently stop reading as "3 below
    the median" (bed 6 sits at 93 from 01:00; by ~04:00 the window is mostly
    93s and the median falls to 93, which would wrongly clear the branch even
    though SpO2 has *not* recovered). That is a false-reassurance failure (the
    top hazard D06): the drop has not recovered, so R2a must stay met.

    To keep the median tied to the patient's established oxygenation rather
    than to the desaturation itself, the 6-h reference window is **anchored to
    just before the onset of the current desaturation episode**. The current
    episode is the maximal contiguous (<=15-min-gap) tail of good samples that
    are *at or below the newest good value* -- for a step drop (bed 6) that is
    every depressed sample back to the step, for a gradual decline (the D15
    "creeping" concern) it reaches back over the whole decline, and for a brief
    dip that has recovered (bed 16 at 03:10) the newest value is the recovered
    high so the episode is the whole flat history and the anchor cannot step
    back -- the window then degenerates to the plain 6-h median. The median is
    taken over the 6 h ending at the sample immediately before that onset, so a
    drop that has outlasted 6 h is still measured against the pre-drop level.

    Deterministic and terminating: the anchor only ever moves strictly backward
    in event time, bounded by the number of samples.
    """

    anchor = t
    ref = median(sorted(o.spo2 for o in good))

    while True:
        window = [o for o in good if anchor - _LOOKBACK < o.event_time <= anchor]
        if not window:
            break
        ref = median(sorted(o.spo2 for o in window))

        newest = window[-1]
        # The current desaturation episode: the contiguous (<=15-min-gap) tail
        # of good samples at or below the newest value. Walk back from newest.
        onset_idx = len(window) - 1
        for i in range(len(window) - 2, -1, -1):
            if window[i + 1].event_time - window[i].event_time > MAX_GAP:
                break
            if window[i].spo2 > newest.spo2:
                break
            onset_idx = i

        onset_time = window[onset_idx].event_time
        before = [o for o in good if o.event_time < onset_time]
        if not before:
            # The episode reaches the earliest available sample: no earlier
            # baseline to anchor to -> keep the current 6-h median.
            break
        new_anchor = before[-1].event_time
        if new_anchor >= anchor:
            break
        anchor = new_anchor

    return ref


def _spo2_branch_met(ctx: R2aContext, t: datetime) -> bool:
    """Good-quality SpO2 >= 3 below the 6-h good-quality median for >= 5 min?

    The median is the pre-desaturation 6-h good-quality median
    (:func:`_spo2_reference_median`); poor-quality samples are ignored entirely
    (AC-R2a-quality; bed 7). Anchoring the median to just before the onset of
    the current drop keeps a *sustained* desaturation reading as "3 below
    median" rather than letting the median drift down to the depressed value
    and silently clear the branch (D15; bed 6 stays met to 07:00). A
    good-quality sample counts toward the desaturation run when it is at least
    3 points below that median. Planned-change tags are **not** consulted here:
    the branch is never suppressed by a tag (AC-R2a-tags-spo2, PBT-12; bed 16
    fires during tagged suctioning). The run uses the 15-min gap rule at the
    "at least 5 min" (``>=``) comparison, so the branch is met at onset + 5 min.
    """

    visible = _visible_obs(ctx, t)
    # All good-quality samples up to t, in event-time order; the anchored
    # reference median may look back further than 6 h (see
    # _spo2_reference_median), while the current run is taken from the last 6 h.
    good_all = [o for o in visible if o.event_time <= t and _good_spo2(o)]
    if not good_all:
        return False

    window_start = t - _LOOKBACK
    good = [o for o in good_all if window_start < o.event_time <= t]
    if not good:
        return False

    ref = _spo2_reference_median(good_all, t)
    threshold = ref - _SPO2_DROP

    # The desaturation must be *current* at t: the newest good-quality sample
    # must itself be at/below threshold, otherwise SpO2 has recovered and the
    # branch is no longer met (bed 16 recovers to 96 at 03:10 -> not_met, even
    # though the 03:05 low sample is only 5 min earlier).
    if good[-1].spo2 > threshold:
        return False

    low = [o.event_time for o in good if o.spo2 <= threshold]
    return duration_held(
        low, t, min_minutes=_SPO2_MIN_MINUTES, strictly_more=False,
    )


# --- the public evaluation --------------------------------------------------


def evaluate_r2a(ctx: R2aContext, t: datetime) -> RuleResult:
    """Evaluate R2a for one encounter at grid time ``t`` -> one state + reason.

    Ordering follows the baseline's safety order: pathway exclusion, then the
    >= 6 h history gate, then stale data, then the two branches. R2a fires
    regardless of fluid balance and, standalone, is labelled "fluid balance
    unknown" (AC-R2a-fluid-independent, PBT-5).
    """

    # 1. Excluded pathway -> not_applicable (ECMO, comfort-only).
    excluded = _excluded_pathway(ctx)
    if excluded is not None:
        reason = (
            ReasonCode.COMFORT_ONLY
            if excluded.strip().lower() in ("comfort_only", "comfort_care")
            else ReasonCode.ECMO
        )
        return RuleResult(
            rule_id=RULE_ID,
            state=EvaluationState.NOT_APPLICABLE,
            reason=reason,
            detail=f"pathway {excluded}",
        )

    # 2. Fewer than 6 h of history on this encounter -> unknown.
    span = _history_span(ctx, t)
    if span is None or span < _HISTORY:
        return RuleResult(
            rule_id=RULE_ID,
            state=EvaluationState.UNKNOWN,
            reason=ReasonCode.INSUFFICIENT_HISTORY,
            detail="fewer than 6 h of history on this encounter",
        )

    # 3. Stale / absent observations -> unknown (stale_data), feed alert.
    gate = freshness_gate(ctx.observations, t, ctx.events)
    if gate.stale:
        return gate.as_unknown(RULE_ID)

    # 4. Either branch met -> met (fluid-independent).
    #
    # R2a is independent of fluid balance and never reads a fluid record
    # (AC-R2a-fluid-independent, PBT-5). The ``met`` detail lists the firing
    # branch(es) and the SpO2 target when documented -- but **not** the
    # "fluid balance unknown" label. The baseline only applies that label
    # "if fluid data are missing or incomplete"; whether the fluid ledger is
    # missing/incomplete is R2b's result, which R2a (by construction) cannot
    # see. So the label is attached later by the orchestrator, for the same
    # cell, only when R2b is ``unknown`` (``evaluate.evaluate_cell``; D29,
    # clinical lead 9 Nov). Previously it was appended here unconditionally,
    # which showed "fluid balance unknown" even beside a complete R2b ledger
    # (bed 6 at 02:00) -- the defect D29 corrects. The rules stay independent:
    # R2a's own state and reason are unchanged, only its displayed detail is
    # completed by the cell that can see both rules.
    settings = _settings_branch_met(ctx, t)
    spo2 = _spo2_branch_met(ctx, t)
    if settings or spo2:
        branches = []
        if spo2:
            branches.append(SPO2_BRANCH)
        if settings:
            branches.append(SETTINGS_BRANCH)
        detail = ", ".join(branches)
        if ctx.spo2_target is not None:
            detail += f"; SpO2 target {ctx.spo2_target}%"
        return RuleResult(
            rule_id=RULE_ID,
            state=EvaluationState.MET,
            reason=ReasonCode.OK_NOT_MET,
            detail=detail,
        )

    # 5. Neither branch met. Before concluding not_met, check that at least
    #    one branch could actually be *evaluated* on the available data. If
    #    every in-window SpO2 sample is poor quality **and** every in-window
    #    settings sample is inside a tagged planned-change window, there is no
    #    usable oxygenation datum at all: that is missing, not a recorded
    #    negative, and must read as unknown -- never a silent not_met (safety
    #    steering: missing means unknown, never fine; PBT-1). A single usable
    #    datum in either branch is enough to assert not_met.
    settings_data = _settings_has_data(ctx, t)
    spo2_data = _spo2_has_data(ctx, t)
    if not settings_data and not spo2_data:
        missing = "good-quality SpO2 and untagged ventilator settings"
        return RuleResult(
            rule_id=RULE_ID,
            state=EvaluationState.UNKNOWN,
            reason=ReasonCode.MISSING_ITEM,
            detail=f"no usable oxygenation data in the last 6 h: {missing}",
        )

    # 6. At least one branch was evaluable and neither fired -> not_met.
    return RuleResult(
        rule_id=RULE_ID,
        state=EvaluationState.NOT_MET,
        reason=ReasonCode.OK_NOT_MET,
        detail="no settings or SpO2 worsening sustained",
    )
