"""The 5-minute evaluation grid, the as-known-at view and duration tracking.

This module factors three pieces of shared machinery that every rule depends
on (``.kiro/steering/tech.md``: one module per rule, shared machinery in small
modules):

* :func:`grid` -- the single clock-aligned 5-minute grid (…:00, :05, …) that
  every rule is evaluated on, so per-rule results at a given ``t`` line up for
  the combined message (AC-DEF-3).
* :func:`as_known_at` -- the visibility gate: only records whose
  ``documented_time`` is ``<= t`` are visible, placed on the timeline at their
  ``event_time``. A late-documented record therefore changes only evaluations
  at or after its documented time (AC-DEF-11, AC-R2b-asknown, PBT-6).
* :func:`duration_held` -- "more than N min" / "at least N min" over fresh
  samples, counting from the latest start of the required condition, with a gap
  greater than 15 min restarting the clock (AC-DEF-6).

Everything here is pure: inputs in, values out, no I/O, no wall-clock, no
mutation of the inputs. Stdlib only, isolated-mode safe.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from functools import lru_cache
from typing import Iterable, Protocol, TypeVar

__all__ = [
    "STEP",
    "MAX_GAP",
    "grid",
    "floor_to_step",
    "as_known_at",
    "duration_held",
]

# The evaluation grid step and the maximum gap that keeps a duration clock
# running. Both are baseline definitions (5-minute grid; 15-minute gap rule).
STEP = timedelta(minutes=5)
MAX_GAP = timedelta(minutes=15)


class _Documented(Protocol):
    """Anything with the two timeline times the as-known-at view needs.

    Record dataclasses in :mod:`sanad.model` expose both as properties even
    when they coincide (observations) or differ (events, fluids).
    """

    @property
    def event_time(self) -> datetime | None: ...

    @property
    def documented_time(self) -> datetime | None: ...


_R = TypeVar("_R", bound=_Documented)


def floor_to_step(t: datetime, step: timedelta = STEP) -> datetime:
    """Floor ``t`` down to the previous clock-aligned grid point.

    Alignment is to the whole hour (…:00) so 5-minute steps land on :00, :05,
    … regardless of the window's own start. Sub-second and microsecond parts
    are dropped. Pure; independent of the local zone (uses ``t``'s own tzinfo).
    """

    step_s = int(step.total_seconds())
    if step_s <= 0:
        raise ValueError("step must be positive")
    anchor = t.replace(minute=0, second=0, microsecond=0)
    elapsed = int((t - anchor).total_seconds())
    floored = (elapsed // step_s) * step_s
    return anchor + timedelta(seconds=floored)


def grid(
    start: datetime, end: datetime, step: timedelta = STEP
) -> list[datetime]:
    """Return the clock-aligned grid points in ``[start, end]``.

    The first point is ``start`` floored to the step (so a window beginning at
    19:00 or 19:02 both start the grid at 19:00); points then advance by
    ``step`` up to and including ``end``. Returning a list (not a bare
    generator) keeps the grid reproducible and reusable by every rule in a run
    (AC-DEF-3). Deterministic: identical inputs give an identical list.
    """

    if end < start:
        raise ValueError("end must not precede start")
    if step.total_seconds() <= 0:
        raise ValueError("step must be positive")

    points: list[datetime] = []
    t = floor_to_step(start, step)
    while t <= end:
        points.append(t)
        t = t + step
    return points



@lru_cache(maxsize=None)
def record_tiebreak(record: object) -> str:
    """``repr(record)``, computed once per frozen (hashable) record.

    The final sort key that makes record orderings total and deterministic.
    It returns exactly ``repr(record)``, so every order is unchanged; caching
    only avoids rebuilding the same string millions of times per night
    (profiled 9 Nov 2026: about 2.7 million ``repr`` calls per encounter).
    """

    return repr(record)

def as_known_at(records: Iterable[_R], t: datetime) -> list[_R]:
    """Return the records visible at ``t``, ordered for deterministic reduction.

    A record is visible when its ``documented_time`` is ``<= t`` (AC-DEF-11);
    visible records are returned in a canonical order keyed by ``event_time``,
    then ``documented_time``, then ``repr(r)`` as a total tie-breaker, so that
    record/file order and *duplicate* transaction IDs with identical times
    cannot change the returned order and hence cannot change a downstream
    result (invariant 6, PBT-6). ``repr`` of a frozen dataclass is a
    deterministic, total function of its fields, so two records that differ in
    any field sort into the same place regardless of input order, while two
    genuinely identical records sort equally (and are interchangeable).
    Records whose ``event_time`` or ``documented_time`` is ``None`` are treated
    as not-yet-visible and excluded (a record with no time cannot be placed).

    Because the filter is ``documented_time <= t``, adding a record documented
    at ``d`` leaves every evaluation at ``t < d`` byte-for-byte unchanged and
    affects only ``t >= d`` (PBT-6, AC-R2b-asknown).
    """

    visible = [
        r
        for r in records
        if r.documented_time is not None
        and r.event_time is not None
        and r.documented_time <= t
    ]
    visible.sort(key=lambda r: (r.event_time, r.documented_time, record_tiebreak(r)))
    return visible


def duration_held(
    sample_times: Iterable[datetime],
    t: datetime,
    *,
    min_minutes: int,
    strictly_more: bool = False,
    max_gap: timedelta = MAX_GAP,
) -> bool:
    """Has a required condition held for the needed span ending at ``t``?

    ``sample_times`` are the event times of the samples at which the condition
    was *true and fresh* (the caller decides truth and freshness). The run is
    the longest tail of those samples ending at or before ``t`` with no gap
    greater than ``max_gap`` between consecutive samples; the clock starts at
    the first sample of that run (AC-DEF-6). A gap greater than ``max_gap``
    restarts the clock, so bed 9's duration clocks restart after its feed
    outage.

    The held span is ``t - run_start`` measured against ``min_minutes``:

    * ``strictly_more=True``  -> span must be strictly greater ("more than N
      min"; R1 duration fires at the first grid point *after* 120 min).
    * ``strictly_more=False`` -> span must be ``>=`` ("at least N min"; the
      R2a branches fire at onset + 30 / + 5 min).

    Pure and deterministic; the input is sorted defensively so sample order
    never changes the answer. Returns ``False`` if there are no samples, if the
    latest sample is after ``t``, or if the most recent sample is itself more
    than ``max_gap`` before ``t`` (the condition is no longer current).
    """

    times = sorted(s for s in sample_times if s is not None)
    if not times:
        return False

    # Only samples at or before t count; the condition cannot be "held at t"
    # using a future sample.
    past = [s for s in times if s <= t]
    if not past:
        return False

    # The condition must still be current at t: the newest sample may be no
    # more than max_gap before t, otherwise the run has already lapsed.
    if t - past[-1] > max_gap:
        return False

    # Walk back from the newest sample; a gap > max_gap breaks the run.
    run_start = past[-1]
    for earlier, later in zip(past[-2::-1], past[-1:0:-1]):
        if later - earlier > max_gap:
            break
        run_start = earlier

    span = t - run_start
    needed = timedelta(minutes=min_minutes)
    return span > needed if strictly_more else span >= needed
