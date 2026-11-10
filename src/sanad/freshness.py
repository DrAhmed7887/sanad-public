"""Freshness: the 15-minute staleness test and the feed/outage alert.

The top hazard is false reassurance (``.kiro/steering/safety.md``), so stale or
absent data must never read as "fine":

* :func:`is_fresh` -- an observation is fresh at ``t`` when it is no more than
  15 minutes old (``t - event_time <= 15 min``).
* :func:`freshness_gate` -- if the newest observation *as known at* ``t`` is
  older than 15 minutes (or there is none at all), every observation-based rule
  must return ``unknown`` with reason ``stale_data`` and a feed alert is raised
  (AC-DEF-5). A ``feed_status`` event reporting the feed down over an interval
  covering ``t`` also raises the alert, as its own visible failure state --
  never silence (AC-R3-failure, invariant 9, PBT-9).

The gate reports *facts* (is it stale, is the feed down, what is the newest
sample); the rule modules turn ``stale`` into the ``unknown``/``stale_data``
result via the shared :mod:`sanad.states`. This keeps the staleness decision in
one place (so PBT-1 can rely on it) while leaving each rule's own result type to
the rule.

Pure, deterministic, stdlib only; ``t`` is always an explicit input.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Iterable, Optional

from .model import Event, Observation
from .states import EvaluationState, ReasonCode
from .timeline import MAX_GAP, as_known_at

__all__ = [
    "FRESH_WINDOW",
    "FEED_DOWN_STATUSES",
    "FreshnessResult",
    "is_fresh",
    "newest_observation",
    "feed_down_at",
    "freshness_gate",
]

# An observation is fresh while it is at most this old. Equal to the duration
# gap rule by design: a single 5-minute grid gap keeps data fresh, a missed
# run (> 15 min) goes stale (bed 9).
FRESH_WINDOW = MAX_GAP  # 15 minutes

# ``feed_status`` values that mean the feed is not delivering data. Matched
# case-insensitively; anything else (e.g. "up", "restored") does not raise the
# alert on its own.
FEED_DOWN_STATUSES = frozenset({"down", "outage", "lost", "disconnected", "failed"})


@dataclass(frozen=True, slots=True)
class FreshnessResult:
    """The outcome of the freshness gate at one grid time.

    * ``stale``      -- the newest visible observation is older than the fresh
      window (or there is none). Observation-based rules become
      ``unknown``/``stale_data`` (AC-DEF-5).
    * ``feed_alert`` -- a visible failure state must be shown. True whenever the
      data are stale *or* a ``feed_status`` event reports the feed down at
      ``t`` (AC-R3-failure, PBT-9).
    * ``newest``     -- the newest visible observation's event time, or ``None``
      when none is visible; carried so a rule can name why it is ``unknown``.
    """

    stale: bool
    feed_alert: bool
    newest: Optional[datetime]

    def as_unknown(self, rule_id: str):
        """Build the shared ``unknown``/``stale_data`` result for a rule.

        Imported lazily to avoid a cycle (``model`` imports nothing from here);
        rule modules call this so the stale handling is written once.
        """

        from .model import RuleResult  # local import: keep module graph acyclic

        detail = (
            f"newest observation {self.newest.isoformat()}"
            if self.newest is not None
            else "no observation recorded"
        )
        return RuleResult(
            rule_id=rule_id,
            state=EvaluationState.UNKNOWN,
            reason=ReasonCode.STALE_DATA,
            detail=detail,
        )


def is_fresh(
    obs: Observation, t: datetime, window: timedelta = FRESH_WINDOW
) -> bool:
    """True when ``obs`` is no more than ``window`` old at ``t``.

    A future observation (event time after ``t``) is not fresh: it is not yet
    known. The boundary is inclusive, so an observation exactly 15 min old at a
    grid point is still fresh (bed 9 is fresh at t = last + 15 min, stale at
    last + 20 min).
    """

    age = t - obs.event_time
    if age < timedelta(0):
        return False
    return age <= window


def newest_observation(
    observations: Iterable[Observation], t: datetime
) -> Optional[Observation]:
    """The latest observation visible at ``t`` (as-known-at), or ``None``.

    Uses :func:`sanad.timeline.as_known_at` so documentation lag is honoured and
    the choice is deterministic (sorted by event time).
    """

    visible = as_known_at(list(observations), t)
    return visible[-1] if visible else None


def feed_down_at(events: Iterable[Event], t: datetime) -> bool:
    """True when a ``feed_status`` event reports the feed down over ``t``.

    Only events already *documented* at ``t`` are considered (as-known-at); an
    event's window is half-open ``[start, end)`` -- the feed is down from its
    start up to but not including its end, so the feed is "restored" exactly at
    ``end`` (bed 9's outage ends at 02:30, when a fresh observation arrives). An
    open (``None``) end is treated as "still down". Status is matched against
    :data:`FEED_DOWN_STATUSES` case-insensitively.
    """

    for e in events:
        if e.type != "feed_status":
            continue
        if e.documented_time is None or e.documented_time > t:
            continue
        if (e.status or "").strip().lower() not in FEED_DOWN_STATUSES:
            continue
        start = e.start
        if start is None or start > t:
            continue
        if e.end is not None and e.end <= t:
            continue
        return True
    return False


def freshness_gate(
    observations: Iterable[Observation],
    t: datetime,
    events: Iterable[Event] = (),
    window: timedelta = FRESH_WINDOW,
) -> FreshnessResult:
    """Decide the freshness/feed state for one bed at grid time ``t``.

    ``observations`` and ``events`` are that bed's records (the caller may pass
    the whole set; the gate applies as-known-at itself). The result is:

    * ``stale`` when the newest visible observation is older than ``window`` or
      there is no visible observation at all -> every observation-based rule
      becomes ``unknown``/``stale_data`` (AC-DEF-5).
    * ``feed_alert`` when ``stale`` is true or a ``feed_status`` event reports
      the feed down at ``t`` -> a visible failure state, never silence
      (AC-R3-failure, PBT-9).

    Pure and deterministic.
    """

    obs_list = list(observations)
    newest = newest_observation(obs_list, t)
    newest_time = newest.event_time if newest is not None else None

    stale = newest is None or not is_fresh(newest, t, window)
    feed_down = feed_down_at(list(events), t)
    return FreshnessResult(
        stale=stale,
        feed_alert=stale or feed_down,
        newest=newest_time,
    )
