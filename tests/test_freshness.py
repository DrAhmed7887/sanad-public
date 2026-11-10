"""Freshness tests (T-fresh): the 15-min staleness gate and the feed alert.

Grounded on bed 9 of the frozen oracle (``data/SCENARIOS.md``): a feed outage
with no observations 01:00-02:25 (last at 00:55, next at 02:30). Expected:

* every observation-based rule ``unknown`` (``stale_data``) on the grid from
  01:15 to 02:25 inclusive (AC-DEF-5);
* a feed alert from 01:15;
* fresh again from 02:30.

Plus the :func:`is_fresh` boundary and the ``feed_status`` alert path. The
scenario parts read the fixed dataset (read-only).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from sanad.freshness import (
    FRESH_WINDOW,
    feed_down_at,
    freshness_gate,
    is_fresh,
    newest_observation,
)
from sanad.loader import load_dataset
from sanad.model import Dataset, Event, Observation
from sanad.states import EvaluationState, ReasonCode
from sanad.timeline import grid

TZ = timezone(timedelta(hours=1))


def dt(d=21, h=1, mi=0) -> datetime:
    return datetime(2026, 11, d, h, mi, tzinfo=TZ)


@pytest.fixture(scope="module")
def ds() -> Dataset:
    return load_dataset()


@pytest.fixture(scope="module")
def bed9(ds: Dataset) -> list[Observation]:
    return [o for o in ds.observations if o.encounter == "E09-1120"]


# --- is_fresh boundary -----------------------------------------------------


def _obs(t: datetime) -> Observation:
    # Minimal observation; only event_time matters for freshness.
    from decimal import Decimal

    return Observation(
        bed=9, encounter="E09-1120", t=t,
        fio2=Decimal("0.35"), fio2_unit="fraction", fio2_fraction=Decimal("0.35"),
        peep=5, peep_unit="cmH2O", spo2=96, spo2_quality="good",
        rr=18, sbp=120, hr=86, spont_effort_flag=True,
    )


def test_is_fresh_boundary_is_inclusive_at_15_min() -> None:
    base = dt(h=0, mi=55)
    o = _obs(base)
    assert is_fresh(o, base)                               # 0 min old
    assert is_fresh(o, base + timedelta(minutes=15))       # exactly 15 -> fresh
    assert not is_fresh(o, base + timedelta(minutes=15, seconds=1))
    assert not is_fresh(o, base + timedelta(minutes=20))   # 20 min -> stale


def test_is_fresh_future_observation_is_not_fresh() -> None:
    o = _obs(dt(h=2, mi=30))
    assert not is_fresh(o, dt(h=1, mi=0))  # not yet known
    assert FRESH_WINDOW == timedelta(minutes=15)


# --- bed 9 outage: stale 01:15-02:25, fresh from 02:30 (AC-DEF-5) ----------


def test_bed9_last_before_and_first_after_outage(bed9: list[Observation]) -> None:
    times = sorted(o.event_time for o in bed9)
    # The gap in the feed: 00:55 then 02:30.
    assert dt(h=0, mi=55) in times
    assert dt(h=2, mi=30) in times
    assert dt(h=1, mi=0) not in times  # nothing charted during the outage


@pytest.mark.parametrize(
    "t",
    [dt(h=1, mi=15), dt(h=1, mi=30), dt(h=2, mi=0), dt(h=2, mi=25)],
)
def test_bed9_stale_across_the_outage_window(bed9, t) -> None:
    res = freshness_gate(bed9, t)
    assert res.stale is True
    assert res.feed_alert is True
    # The gate names the newest observation it could see (00:55).
    assert res.newest == dt(h=0, mi=55)
    # And it builds the shared unknown/stale_data result for a rule.
    rr = res.as_unknown("R2a")
    assert rr.state is EvaluationState.UNKNOWN
    assert rr.reason is ReasonCode.STALE_DATA


def test_bed9_fresh_just_before_the_window_and_after_restore(bed9) -> None:
    # 01:10: newest is 00:55, age 15 min -> still fresh (last fresh grid point).
    before = freshness_gate(bed9, dt(h=1, mi=10))
    assert before.stale is False and before.feed_alert is False
    # 02:30: a fresh observation arrives -> fresh again, clocks restart.
    after = freshness_gate(bed9, dt(h=2, mi=30))
    assert after.stale is False and after.feed_alert is False
    assert after.newest == dt(h=2, mi=30)


def test_bed9_whole_outage_grid_is_exactly_0115_to_0225(bed9) -> None:
    # Walk the 5-min grid across the outage and assert the stale span is
    # exactly 01:15..02:25 inclusive, fresh on either side.
    stale_points = [
        t for t in grid(dt(h=0, mi=55), dt(h=2, mi=30))
        if freshness_gate(bed9, t).stale
    ]
    assert stale_points[0] == dt(h=1, mi=15)
    assert stale_points[-1] == dt(h=2, mi=25)
    # Contiguous: every 5-min point between the ends is stale.
    expected = grid(dt(h=1, mi=15), dt(h=2, mi=25))
    assert stale_points == expected


def test_newest_observation_respects_as_known_at(bed9) -> None:
    assert newest_observation(bed9, dt(h=0, mi=55)).event_time == dt(h=0, mi=55)
    # During the outage the newest visible observation is still 00:55.
    assert newest_observation(bed9, dt(h=2, mi=0)).event_time == dt(h=0, mi=55)


# --- feed_status event raises the alert on its own (AC-R3-failure, PBT-9) --


def _feed_status(start, end, status="down") -> Event:
    return Event(
        bed=9, encounter="E09-1120", type="feed_status",
        start=start, end=end, status=status,
    )


def test_bed9_feed_status_event_raises_alert_over_its_window(ds: Dataset) -> None:
    # The real bed 9 feed_status: down 01:00-02:30.
    events9 = [e for e in ds.events
               if e.encounter == "E09-1120" and e.type == "feed_status"]
    assert events9, "bed 9 must carry a feed_status event"
    down = events9[0]
    assert down.status == "down"
    assert down.start == dt(h=1, mi=0) and down.end == dt(h=2, mi=30)
    # The feed is reported down across the whole outage.
    assert feed_down_at(events9, dt(h=1, mi=0)) is True
    assert feed_down_at(events9, dt(h=2, mi=0)) is True
    # ... and not before it starts or after it ends.
    assert feed_down_at(events9, dt(h=0, mi=55)) is False
    assert feed_down_at(events9, dt(h=2, mi=35)) is False


def test_feed_status_down_raises_alert_even_with_fresh_data() -> None:
    # Fresh observation present, but the feed is reported down over t.
    fresh = [_obs(dt(h=1, mi=0))]
    down = _feed_status(dt(h=1, mi=0), dt(h=1, mi=30))
    res = freshness_gate(fresh, dt(h=1, mi=5), events=[down])
    assert res.stale is False          # data themselves are fresh
    assert res.feed_alert is True      # but the failure is still visible


def test_feed_status_open_ended_down_stays_down() -> None:
    down = _feed_status(dt(h=1, mi=0), None)
    assert feed_down_at([down], dt(h=3, mi=0)) is True


def test_feed_status_outside_window_or_restored_does_not_alert() -> None:
    down = _feed_status(dt(h=1, mi=0), dt(h=1, mi=30))
    # Before the window: not down.
    assert feed_down_at([down], dt(h=0, mi=55)) is False
    # After the window: not down.
    assert feed_down_at([down], dt(h=1, mi=35)) is False
    # A non-down status never raises on its own.
    up = _feed_status(dt(h=1, mi=0), dt(h=2, mi=0), status="up")
    assert feed_down_at([up], dt(h=1, mi=30)) is False
