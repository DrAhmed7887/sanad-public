"""R2b -- fluid-accounting review (low-priority, from the recorded ledger).

Pure, deterministic evaluation of the configured *fluid-accounting* review on
the fixed synthetic dataset. R2b is a low-priority prompt computed from the
recorded intake/output ledger; it never establishes fluid overload and must not
treat a gap in charting as zero (``docs/EVIDENCE.md`` R2b; requirements
Section 4). Its ``+2,000 ml`` threshold is a DESIGN demo value, not an alarm
threshold.

The balance R2b reduces over is the **72-hour rolling net as known at t**:

* **as known at t** -- only transactions whose ``documented_time <= t`` are
  visible, each placed on the timeline at its ``event_time`` (AC-R2b-asknown,
  AC-DEF-11). A transaction given at 20:00 but charted at 02:00 is invisible
  until 02:00 and then counts at its 20:00 event time (bed 6).
* **deduplicated by transaction ID** -- a ``tx_id`` seen more than once counts
  once; its canonical record is chosen deterministically so record order and
  duplicates cannot change the net (AC-R2b-dedup-order, invariant 6; bed 5).
* **summed by event time over the previous 72 h** -- only transactions with
  ``event_time`` in ``(t - 72 h, t]`` enter the sum; ``in`` adds, ``out``
  subtracts.
* **CRRT: net only** -- among CRRT sources only ``crrt_net`` removal is counted;
  gross effluent and replacement volumes are ignored entirely (AC-R2b-crrt;
  bed 17's net falls as each ``crrt_net`` entry becomes known, while the
  18 L gross effluent/replacement pair never enters the sum).
* **no charting-day totals** -- the ``daily_totals`` distractor (which resets at
  07:00) is never read; it is not even part of R2b's context (AC-R2b-no-
  dailytotals).

Gating, in the baseline's safety order:

* fewer than **6 h of history** on this encounter -> ``unknown`` /
  ``insufficient_history`` (AC-R2b-hist; bed 13B until first observation + 6 h);
* **output not charted** -- no urine or drain output in the previous 6 h and the
  patient is not documented anuric -> ``unknown`` / ``output_not_charted``; the
  computed net is still shown and missing output is never treated as zero
  (AC-R2b-coverage; bed 17 all night);
* otherwise the net ``> +2,000 ml`` -> ``met`` (bed 5, bed 6 from 02:00,
  bed 13A), else ``not_met`` (beds 4, 7, 11).

Unlike R2a, **no pathway excludes R2b**: it applies on ECMO and every other
pathway (AC-R2b-pathways; bed 11 is ``not_met``, not ``not_applicable``).

Pure: ``(context, t) -> RuleResult``; no I/O, no wall-clock, no mutation of the
inputs. Imports only shared modules (never another rule). Stdlib only.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

from .model import Dataset, FluidTx, Observation, RuleResult
from .states import EvaluationState, ReasonCode
from .timeline import as_known_at

__all__ = [
    "RULE_ID",
    "R2bContext",
    "context_for",
    "evaluate_r2b",
    "rolling_net_ml",
    "ROLLING_WINDOW",
    "COVERAGE_WINDOW",
    "HISTORY",
    "THRESHOLD_ML",
    "CRRT_COUNTED_SOURCES",
    "OUTPUT_SOURCES",
]

RULE_ID = "R2b"

# --- configured thresholds and windows (DESIGN demo values, baseline v3) ----

# The rolling balance window and the positive-balance threshold. "> +2,000 ml"
# is a strict comparison so exactly +2,000 ml is not yet met.
ROLLING_WINDOW = timedelta(hours=72)
THRESHOLD_ML = 2000

# Output-coverage look-back: no urine/drain output in the previous 6 h (and not
# anuric) means the ledger is incomplete, so the balance is unknown rather than
# a reassuring number built on an assumed-zero output.
COVERAGE_WINDOW = timedelta(hours=6)

# Minimum encounter history before R2b will produce a balance result; measured
# from the encounter's first observation (shared with R2a so a reassignment's
# new encounter clears both gates together).
HISTORY = timedelta(hours=6)

# CRRT: only charted *net* removal counts. Gross effluent and replacement
# volumes (large matched flows that net to roughly the clinician-charted
# removal) are ignored so they cannot swamp the balance (AC-R2b-crrt).
CRRT_COUNTED_SOURCES = frozenset({"crrt_net"})

# A source string names a CRRT record when it starts with this prefix; any CRRT
# source not in CRRT_COUNTED_SOURCES is a gross flow and is ignored.
_CRRT_PREFIX = "crrt_"

# Output sources that count as "output charted" for the coverage check. CRRT net
# removal is deliberately *not* here: it is a machine net, not charted urine or
# drain output, so it never satisfies coverage (bed 17 stays output_not_charted
# all night despite its crrt_net entries).
OUTPUT_SOURCES = frozenset({"urine", "drain"})


# --- per-encounter context --------------------------------------------------


@dataclass(frozen=True, slots=True)
class R2bContext:
    """Everything R2b needs for one encounter, filtered to that encounter.

    Pure data: the evaluation reads only these records (plus the explicit grid
    time ``t``). ``daily_totals`` is deliberately **absent** -- R2b cannot read
    the charting-day distractor because it is not even in scope
    (AC-R2b-no-dailytotals, PBT-6). ``observations`` are carried only to measure
    history for the >= 6 h gate; R2b reads no observation values.
    """

    encounter: str
    bed: int
    anuric: bool
    fluids: tuple[FluidTx, ...]
    observations: tuple[Observation, ...]


def context_for(ds: Dataset, encounter: str) -> R2bContext:
    """Build an :class:`R2bContext` for one encounter from a loaded dataset."""

    enc = ds.by_encounter[encounter]
    return R2bContext(
        encounter=encounter,
        bed=enc.bed,
        anuric=enc.anuric,
        fluids=tuple(f for f in ds.fluids if f.encounter == encounter),
        observations=tuple(o for o in ds.observations if o.encounter == encounter),
    )


# --- helpers ----------------------------------------------------------------


def _counts_toward_balance(tx: FluidTx) -> bool:
    """Does this transaction enter the net balance at all?

    Non-CRRT transactions (``iv``, ``urine``, ``drain``, ...) always count. CRRT
    transactions count only when their source is a *net* removal; gross CRRT
    effluent/replacement flows are ignored (AC-R2b-crrt).
    """

    source = tx.source.strip().lower()
    if source.startswith(_CRRT_PREFIX):
        return source in CRRT_COUNTED_SOURCES
    return True


def _signed_ml(tx: FluidTx) -> int:
    """The signed contribution of ``tx`` to the net (``in`` +, ``out`` -)."""

    return tx.ml if tx.kind.strip().lower() == "in" else -tx.ml


def _dedup_by_tx_id(visible: list[FluidTx]) -> list[FluidTx]:
    """Keep one record per ``tx_id`` from an already canonically-ordered list.

    ``visible`` comes from :func:`sanad.timeline.as_known_at`, which sorts by
    ``(event_time, documented_time, repr)`` -- a total, deterministic order. The
    first occurrence of each ``tx_id`` in that order is therefore a
    deterministic choice independent of input/file order, so duplicate IDs
    cannot change the net (AC-R2b-dedup-order, invariant 6). Duplicate records
    that are byte-for-byte equal are naturally collapsed; the dataset's
    duplicates are exact repeats, so the chosen record carries the same value
    either way.
    """

    seen: set[str] = set()
    out: list[FluidTx] = []
    for tx in visible:
        if tx.tx_id in seen:
            continue
        seen.add(tx.tx_id)
        out.append(tx)
    return out


def rolling_net_ml(ctx: R2bContext, t: datetime) -> int:
    """The 72-hour rolling net balance in ml, as known at ``t``.

    Deterministic reduction: take the transactions visible at ``t`` (documented
    ``<= t``) in canonical order, deduplicate by ``tx_id``, keep those whose
    ``event_time`` lies in ``(t - 72 h, t]`` and that count toward the balance
    (CRRT gross flows excluded), then sum their signed ml. Order-, duplicate-
    and day-reset-invariant by construction (PBT-6).
    """

    visible = as_known_at(list(ctx.fluids), t)
    deduped = _dedup_by_tx_id(visible)
    window_start = t - ROLLING_WINDOW
    return sum(
        _signed_ml(tx)
        for tx in deduped
        if window_start < tx.event_time <= t and _counts_toward_balance(tx)
    )


def _output_charted_recently(ctx: R2bContext, t: datetime) -> bool:
    """Is any urine/drain output charted in ``(t - 6 h, t]`` as known at ``t``?

    Only transactions documented at ``t`` count (as-known-at); a late-charted
    output becomes "recent" exactly when it becomes visible. CRRT net removal
    does not count as charted output here (see :data:`OUTPUT_SOURCES`).
    """

    visible = as_known_at(list(ctx.fluids), t)
    window_start = t - COVERAGE_WINDOW
    return any(
        tx.kind.strip().lower() == "out"
        and tx.source.strip().lower() in OUTPUT_SOURCES
        and window_start < tx.event_time <= t
        for tx in visible
    )


def _history_span(ctx: R2bContext, t: datetime) -> Optional[timedelta]:
    """How much observation history is available on this encounter at ``t``.

    Measured from the earliest observation visible at ``t`` (as-known-at), the
    same basis R2a uses, so a reassignment's new encounter (bed 13B) clears the
    >= 6 h gate for R2a and R2b at the same grid point. ``None`` when no
    observation is visible yet.
    """

    visible = as_known_at(list(ctx.observations), t)
    if not visible:
        return None
    return t - visible[0].event_time


def _net_detail(net_ml: int) -> str:
    """A human-readable signed litre figure for the computed net (shown always).

    Uses integer-exact arithmetic on millilitres; the litre figure is formatted
    to one decimal place for display only (no threshold comparison uses it).
    """

    litres = net_ml / 1000
    return f"net {litres:+.2f} L ({net_ml:+d} ml) over 72 h"


# --- the public evaluation --------------------------------------------------


def evaluate_r2b(ctx: R2bContext, t: datetime) -> RuleResult:
    """Evaluate R2b for one encounter at grid time ``t`` -> one state + reason.

    Ordering follows the baseline's safety order: the >= 6 h history gate, then
    the output-coverage gate (missing output is ``unknown``, never an assumed
    zero), then the ``> +2,000 ml`` balance. No pathway excludes R2b
    (AC-R2b-pathways); the computed net is shown in the detail of every
    non-history result so the figure is auditable even when the state is
    ``unknown`` (bed 17).
    """

    # 1. Fewer than 6 h of history on this encounter -> unknown. (No net can be
    #    shown yet: there is too little of the encounter to trust a 72-h sum.)
    span = _history_span(ctx, t)
    if span is None or span < HISTORY:
        return RuleResult(
            rule_id=RULE_ID,
            state=EvaluationState.UNKNOWN,
            reason=ReasonCode.INSUFFICIENT_HISTORY,
            detail="fewer than 6 h of history on this encounter",
        )

    net_ml = rolling_net_ml(ctx, t)
    net_detail = _net_detail(net_ml)

    # 2. Output coverage: no urine/drain output in the previous 6 h and not
    #    documented anuric -> unknown (output_not_charted). The computed net is
    #    still shown; missing output is never treated as zero (AC-R2b-coverage).
    if not ctx.anuric and not _output_charted_recently(ctx, t):
        return RuleResult(
            rule_id=RULE_ID,
            state=EvaluationState.UNKNOWN,
            reason=ReasonCode.OUTPUT_NOT_CHARTED,
            detail=f"no urine/drain output charted in the previous 6 h; {net_detail}",
        )

    # 3. Balance strictly greater than +2,000 ml -> met, else not_met.
    if net_ml > THRESHOLD_ML:
        return RuleResult(
            rule_id=RULE_ID,
            state=EvaluationState.MET,
            reason=ReasonCode.OK_NOT_MET,
            detail=net_detail,
        )
    return RuleResult(
        rule_id=RULE_ID,
        state=EvaluationState.NOT_MET,
        reason=ReasonCode.OK_NOT_MET,
        detail=net_detail,
    )
