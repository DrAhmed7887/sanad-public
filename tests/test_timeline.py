"""Timeline tests (T-timeline): grid, as-known-at and the 15-min gap rule.

These exercise the shared machinery every rule stands on:

* the 5-minute clock-aligned grid (AC-DEF-3);
* the as-known-at view that hides late documentation -- grounded on the real
  bed 6 record charted at 20:00 but documented 02:00 (AC-DEF-11, AC-R2b-asknown);
* ``duration_held`` "more than N" vs "at least N" and the >15-min gap that
  restarts the clock (AC-DEF-6), including bed 9's outage.

The scenario-grounded parts read the fixed dataset under ``data/ward_seed42/``;
they read only, never write (safety steering).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from sanad.loader import load_dataset
from sanad.model import Dataset
from sanad.timeline import (
    MAX_GAP,
    STEP,
    as_known_at,
    duration_held,
    floor_to_step,
    grid,
)

TZ = timezone(timedelta(hours=1))  # dataset zone +01:00


def dt(y=2026, mo=11, d=20, h=19, mi=0) -> datetime:
    return datetime(y, mo, d, h, mi, tzinfo=TZ)


@pytest.fixture(scope="module")
def ds() -> Dataset:
    return load_dataset()


# --- grid: 5-minute clock alignment (AC-DEF-3) ----------------------------


def test_grid_is_clock_aligned_on_five_minutes() -> None:
    points = grid(dt(h=19, mi=0), dt(h=20, mi=0))
    assert points[0] == dt(h=19, mi=0)
    assert points[-1] == dt(h=20, mi=0)
    # 12 steps of 5 min across one hour, inclusive of both ends -> 13 points.
    assert len(points) == 13
    for p in points:
        assert p.minute % 5 == 0
        assert p.second == 0 and p.microsecond == 0
    # Consecutive points differ by exactly the step.
    assert all(b - a == STEP for a, b in zip(points, points[1:]))


def test_grid_floors_a_ragged_start_to_the_step() -> None:
    # A window that opens at 19:02:30 still starts the grid at 19:00.
    start = dt(h=19, mi=2).replace(second=30)
    points = grid(start, dt(h=19, mi=20))
    assert points[0] == dt(h=19, mi=0)
    assert points[1] == dt(h=19, mi=5)


def test_floor_to_step_anchors_to_the_hour() -> None:
    assert floor_to_step(dt(h=19, mi=4)) == dt(h=19, mi=0)
    assert floor_to_step(dt(h=19, mi=5)) == dt(h=19, mi=5)
    assert floor_to_step(dt(h=19, mi=59)) == dt(h=19, mi=55)


def test_grid_is_deterministic_and_covers_the_night_window(ds: Dataset) -> None:
    start = datetime.fromisoformat(ds.meta["night_start"])
    end = datetime.fromisoformat(ds.meta["night_end"])
    a = grid(start, end)
    b = grid(start, end)
    assert a == b  # re-run -> identical
    # 19:00 to 07:00 next day inclusive = 12 h = 145 five-minute points.
    assert a[0] == start and a[-1] == end
    assert len(a) == 145


def test_grid_rejects_backwards_window() -> None:
    with pytest.raises(ValueError):
        grid(dt(h=20), dt(h=19))


# --- as_known_at: late documentation is hidden (AC-DEF-11) ----------------


def test_as_known_at_hides_bed6_late_documented_litre(ds: Dataset) -> None:
    # Bed 6: 1.0 L charted at event 20:00 but documented only at 02:00.
    bed6 = [f for f in ds.fluids if f.encounter == "E06-1120"]
    late = next(f for f in bed6 if f.tx_id == "F06-0060")
    assert late.event_time == dt(d=20, h=20, mi=0)
    assert late.documented_time == dt(d=21, h=2, mi=0)

    # Just before its documented time the litre is invisible ...
    before = as_known_at(bed6, dt(d=21, h=1, mi=55))
    assert late not in before
    # ... and from its documented time it is visible, placed at its event time.
    at_doc = as_known_at(bed6, dt(d=21, h=2, mi=0))
    assert late in at_doc
    # Visible records are ordered by event time (stable for reduction).
    event_times = [f.event_time for f in at_doc]
    assert event_times == sorted(event_times)


def test_as_known_at_boundary_is_inclusive_and_places_at_event_time(ds: Dataset) -> None:
    bed6 = [f for f in ds.fluids if f.encounter == "E06-1120"]
    late = next(f for f in bed6 if f.tx_id == "F06-0060")
    # documented_time <= t is inclusive: visible exactly at the documented time.
    assert late in as_known_at(bed6, late.documented_time)
    # One microsecond earlier it is still hidden.
    just_before = late.documented_time - timedelta(microseconds=1)
    assert late not in as_known_at(bed6, just_before)


def test_as_known_at_is_order_independent(ds: Dataset) -> None:
    bed6 = [f for f in ds.fluids if f.encounter == "E06-1120"]
    t = dt(d=21, h=3, mi=0)
    forward = as_known_at(bed6, t)
    reversed_in = as_known_at(list(reversed(bed6)), t)
    # Same visible set, same canonical order regardless of input order.
    assert forward == reversed_in


# --- duration_held: more-than vs at-least and the 15-min gap (AC-DEF-6) ----


def _samples(start_min: int, count: int, step_min: int = 5) -> list[datetime]:
    return [dt(h=20, mi=start_min) + timedelta(minutes=step_min * i)
            for i in range(count)]


def test_duration_strictly_more_fires_only_after_threshold() -> None:
    # Condition true every 5 min from 20:00; "more than 120 min".
    samples = _samples(0, 40)  # 20:00 .. 23:15
    start = dt(h=20, mi=0)
    # At exactly +120 min, "more than" is NOT yet met.
    assert not duration_held(
        [s for s in samples if s <= start + timedelta(minutes=120)],
        start + timedelta(minutes=120),
        min_minutes=120, strictly_more=True,
    )
    # At the next grid point (+125 min) it is met.
    t = start + timedelta(minutes=125)
    assert duration_held(
        [s for s in samples if s <= t], t,
        min_minutes=120, strictly_more=True,
    )


def test_duration_at_least_fires_at_onset_plus_n() -> None:
    samples = _samples(0, 12)  # 20:00 .. 20:55
    start = dt(h=20, mi=0)
    # "At least 30 min" is met exactly at onset + 30 min.
    t = start + timedelta(minutes=30)
    assert duration_held(
        [s for s in samples if s <= t], t,
        min_minutes=30, strictly_more=False,
    )
    # One grid step earlier it is not yet met.
    t_early = start + timedelta(minutes=25)
    assert not duration_held(
        [s for s in samples if s <= t_early], t_early,
        min_minutes=30, strictly_more=False,
    )


def test_duration_gap_over_15_min_restarts_the_clock() -> None:
    # Samples every 5 min 20:00..20:55, then an outage, resuming 22:00.
    before = _samples(0, 12)  # 20:00..20:55
    after = [dt(h=22, mi=0) + timedelta(minutes=5 * i) for i in range(12)]  # 22:00..22:55
    samples = before + after
    # At 22:30, only the post-gap run (from 22:00) counts: 30 min held.
    t = dt(h=22, mi=30)
    assert duration_held(samples, t, min_minutes=30, strictly_more=False)
    # The earlier run cannot be glued across the >15-min gap: at 22:05 the
    # post-gap run is only 5 min, so "at least 30 min" is not met even though
    # samples span 20:00..22:05.
    t2 = dt(h=22, mi=5)
    assert not duration_held(samples, t2, min_minutes=30, strictly_more=False)


def test_duration_lapses_when_newest_sample_is_stale() -> None:
    # Condition last true at 20:00; at 20:20 the newest sample is 20 min old
    # (> 15-min gap) so the run has lapsed -> not held.
    samples = [dt(h=20, mi=0)]
    assert not duration_held(samples, dt(h=20, mi=20),
                             min_minutes=5, strictly_more=False)
    # Still current at exactly +15 min.
    assert duration_held([dt(h=20, mi=0), dt(h=20, mi=5)],
                         dt(h=20, mi=5), min_minutes=5, strictly_more=False)


def test_duration_empty_or_future_only_is_not_held() -> None:
    assert not duration_held([], dt(h=20), min_minutes=5)
    future = [dt(h=21, mi=0)]
    assert not duration_held(future, dt(h=20, mi=0), min_minutes=5)


def test_duration_is_order_independent() -> None:
    samples = _samples(0, 12)
    t = dt(h=20, mi=30)
    forward = duration_held(samples, t, min_minutes=30)
    shuffled = duration_held(list(reversed(samples)), t, min_minutes=30)
    assert forward == shuffled is True


def test_max_gap_constant_is_15_minutes() -> None:
    assert MAX_GAP == timedelta(minutes=15)
    assert STEP == timedelta(minutes=5)
