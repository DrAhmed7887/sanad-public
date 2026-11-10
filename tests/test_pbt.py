"""Property-based invariants. This module grows one PBT per task.

PBT-2: equivalent values in supported units return an identical
result; an unsupported unit returns an explicit error (never a guess)
-- requirements.md Section 7, baseline invariant 2.

PBT-1 / PBT-6 / PBT-9 (task 2): the freshness and as-known-at invariants --
a missing/stale mandatory datum never yields ``met`` and names the input
(PBT-1); the rolling view is invariant to day-resets, record order and
duplicate IDs, and a late-documented record changes only evaluations at or
after its documented time (PBT-6); a feed/routing failure is always a visible
state, never quiet (PBT-9).

The hypothesis profile is pinned deterministic in ``conftest.py`` so CI runs
are reproducible (``.kiro/steering/tech.md``). Strategies generate synthetic
values only: no real data, no network.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from sanad.units import (
    SUPPORTED_DOSE_UNITS,
    SUPPORTED_FIO2_UNITS,
    UnsupportedUnitError,
    convert_dose,
    normalise_fio2,
)

# FiO2 fractions in the valid [0.21, 1.0] range, at 0.01 resolution, so each
# has an exact percent twin.
_fio2_fractions = st.integers(min_value=21, max_value=100).map(
    lambda p: Decimal(p) / Decimal(100)
)

# Unit strings that are NOT supported FiO2 units.
_bad_fio2_units = st.text(min_size=1, max_size=12).filter(
    lambda s: s not in SUPPORTED_FIO2_UNITS
)
_bad_dose_units = st.text(min_size=1, max_size=12).filter(
    lambda s: s not in SUPPORTED_DOSE_UNITS
)


# --- PBT-2: equivalent supported units -> identical result ----------------


@given(fraction=_fio2_fractions)
def test_pbt2_fio2_fraction_and_percent_equivalent(fraction: Decimal) -> None:
    """A FiO2 given as a fraction and as the equal percent normalise to the
    identical Decimal (no float drift, no threshold bias)."""

    percent = fraction * Decimal(100)
    assert normalise_fio2(fraction, "fraction") == normalise_fio2(percent, "percent")


@given(fraction=_fio2_fractions)
def test_pbt2_fio2_result_in_fraction_range(fraction: Decimal) -> None:
    """Whatever the input unit, the result is a fraction in [0.21, 1.0]."""

    out = normalise_fio2(fraction * Decimal(100), "percent")
    assert Decimal("0.21") <= out <= Decimal("1.0")


@given(
    dose=st.decimals(
        min_value=Decimal("0.01"), max_value=Decimal("50"),
        places=2, allow_nan=False, allow_infinity=False,
    ),
    weight=st.integers(min_value=40, max_value=150),
)
def test_pbt2_weight_based_dose_is_deterministic(dose: Decimal, weight: int) -> None:
    """Weight-based conversion is a pure product: same inputs -> same output,
    and it equals dose*weight exactly."""

    a = convert_dose(dose, "mcg/kg/min", weight)
    b = convert_dose(dose, "mcg/kg/min", weight)
    assert a == b == dose * Decimal(weight)


# --- PBT-2: unsupported unit -> explicit error ----------------------------


@given(unit=_bad_fio2_units, value=st.integers(min_value=21, max_value=100))
def test_pbt2_unsupported_fio2_unit_errors(unit: str, value: int) -> None:
    with pytest.raises(UnsupportedUnitError):
        normalise_fio2(value, unit)


@given(
    unit=_bad_dose_units,
    dose=st.decimals(
        min_value=Decimal("0.01"), max_value=Decimal("50"),
        places=2, allow_nan=False, allow_infinity=False,
    ),
    weight=st.integers(min_value=40, max_value=150),
)
def test_pbt2_unsupported_dose_unit_errors(unit: str, dose: Decimal, weight: int) -> None:
    with pytest.raises(UnsupportedUnitError):
        convert_dose(dose, unit, weight)


# ==========================================================================
# PBT-1 / PBT-6 / PBT-9 (task 2): freshness, as-known-at and feed failure.
# ==========================================================================

from datetime import datetime, timedelta, timezone  # noqa: E402

from sanad.freshness import freshness_gate, is_fresh  # noqa: E402
from sanad.model import Event, FluidTx, Observation  # noqa: E402
from sanad.states import EvaluationState  # noqa: E402
from sanad.timeline import as_known_at  # noqa: E402

_TZ = timezone(timedelta(hours=1))
_BASE = datetime(2026, 11, 20, 19, 0, tzinfo=_TZ)


def _at(minutes: int) -> datetime:
    """A tz-aware time ``minutes`` after a fixed synthetic base (no wall-clock)."""

    return _BASE + timedelta(minutes=minutes)


def _mk_obs(event_minutes: int) -> Observation:
    return Observation(
        bed=1, encounter="SYN", t=_at(event_minutes),
        fio2=Decimal("0.40"), fio2_unit="fraction", fio2_fraction=Decimal("0.40"),
        peep=5, peep_unit="cmH2O", spo2=96, spo2_quality="good",
        rr=18, sbp=120, hr=80, spont_effort_flag=True,
    )


def _mk_fluid(tx_id: str, kind: str, ml: int, event_m: int, doc_m: int) -> FluidTx:
    return FluidTx(
        bed=1, encounter="SYN", tx_id=tx_id, kind=kind, ml=ml, source="iv",
        event_time=_at(event_m), documented_time=_at(doc_m),
    )


# --- PBT-1: a missing or stale mandatory datum never yields ``met`` --------


@given(
    # A gap strictly greater than 15 min since the newest observation, or no
    # observation at all (count == 0).
    count=st.integers(min_value=0, max_value=5),
    newest_age=st.integers(min_value=16, max_value=600),
)
def test_pbt1_stale_or_missing_is_unknown_never_met(count: int, newest_age: int) -> None:
    t = _at(1000)
    if count == 0:
        obs: list[Observation] = []
    else:
        # Place the newest observation ``newest_age`` minutes before t (stale),
        # and any earlier ones further back.
        obs = [
            _mk_obs(1000 - newest_age - 5 * i) for i in range(count)
        ]
    res = freshness_gate(obs, t)
    assert res.stale is True            # missing or > 15 min old -> stale
    assert res.feed_alert is True       # a visible state, never quiet
    rr = res.as_unknown("R2a")
    # Never ``met`` when a mandatory datum is missing/stale (invariant 1).
    assert rr.state is EvaluationState.UNKNOWN
    assert rr.state is not EvaluationState.MET
    # The missing/stale input is named (newest sample, or "no observation").
    assert rr.detail  # non-empty
    if count == 0:
        assert "no observation" in rr.detail
    else:
        assert "observation" in rr.detail


@given(age=st.integers(min_value=0, max_value=15))
def test_pbt1_within_window_is_fresh(age: int) -> None:
    """Symmetry check: at or under 15 min the newest sample is fresh (so the
    stale gate does not fire spuriously)."""

    t = _at(1000)
    obs = [_mk_obs(1000 - age)]
    assert is_fresh(obs[0], t) is True
    assert freshness_gate(obs, t).stale is False


# --- PBT-6: order / duplicate / day-reset invariance; late doc locality -----

_fluid_txns = st.lists(
    st.tuples(
        st.integers(min_value=0, max_value=1000),   # event minute
        st.integers(min_value=0, max_value=1000),   # extra documentation lag
        st.sampled_from(["in", "out"]),
        st.integers(min_value=1, max_value=2000),    # ml
    ),
    min_size=0, max_size=12,
)


def _build_fluids(spec) -> list[FluidTx]:
    out: list[FluidTx] = []
    for i, (ev, lag, kind, ml) in enumerate(spec):
        out.append(_mk_fluid(f"F{i:03d}", kind, ml, ev, ev + lag))
    return out


@given(spec=_fluid_txns)
def test_pbt6_as_known_at_is_order_independent(spec) -> None:
    """The visible set at t does not depend on input record order or on
    duplicated records (invariant 6). Compared as a multiset: the reduction the
    rules perform (a sum) is order-free, so the invariant is that the same
    records are visible, regardless of input order."""

    fluids = _build_fluids(spec)
    t = _at(500)

    def multiset(records):
        return sorted(
            (f.event_time, f.documented_time, f.tx_id, f.kind, f.ml)
            for f in records
        )

    base = multiset(as_known_at(fluids, t))
    # Reversed input -> identical visible multiset.
    assert multiset(as_known_at(list(reversed(fluids)), t)) == base
    # Only documented_time <= t records are visible.
    assert base == sorted(
        (f.event_time, f.documented_time, f.tx_id, f.kind, f.ml)
        for f in fluids if f.documented_time <= t
    )


@given(
    spec=_fluid_txns,
    late_event=st.integers(min_value=0, max_value=1000),
    late_lag=st.integers(min_value=1, max_value=1000),
)
def test_pbt6_late_record_only_affects_at_or_after_its_doc_time(
    spec, late_event: int, late_lag: int
) -> None:
    """Adding a late-documented record changes the as-known-at view only at and
    after its documented time; every earlier evaluation is byte-for-byte equal
    (invariant 6 / AC-R2b-asknown)."""

    fluids = _build_fluids(spec)
    late = _mk_fluid("LATE", "in", 1000, late_event, late_event + late_lag)
    doc = late.documented_time

    # Strictly before the documented time: the late record is invisible, so the
    # visible view is unchanged by its presence.
    before_t = doc - timedelta(minutes=5)
    assert as_known_at(fluids + [late], before_t) == as_known_at(fluids, before_t)

    # At the documented time: the late record is now visible.
    assert late in as_known_at(fluids + [late], doc)


# --- PBT-9: a feed/routing failure is always a visible state, never quiet ---


@given(
    down_start=st.integers(min_value=0, max_value=400),
    down_len=st.integers(min_value=5, max_value=400),
    probe_offset=st.integers(min_value=0, max_value=399),
)
def test_pbt9_feed_failure_is_never_quiet(
    down_start: int, down_len: int, probe_offset: int
) -> None:
    """While a feed is reported down, the gate always raises a visible alert --
    even if an observation happens to be fresh (invariant 9, AC-R3-failure)."""

    down = Event(
        bed=1, encounter="SYN", type="feed_status",
        start=_at(down_start), end=_at(down_start + down_len), status="down",
    )
    # A fresh observation at the probe time: data are fine, feed is not.
    probe = _at(down_start + probe_offset % down_len)
    fresh_obs = [Observation(
        bed=1, encounter="SYN", t=probe,
        fio2=Decimal("0.40"), fio2_unit="fraction", fio2_fraction=Decimal("0.40"),
        peep=5, peep_unit="cmH2O", spo2=96, spo2_quality="good",
        rr=18, sbp=120, hr=80, spont_effort_flag=True,
    )]
    res = freshness_gate(fresh_obs, probe, events=[down])
    # The probe is inside the half-open down window, so the alert must fire.
    assert res.feed_alert is True


# ==========================================================================
# PBT-3 / PBT-4 / PBT-11 (task 3): R1 holds, episodes and expired confirmations.
# ==========================================================================

from sanad.r1 import (  # noqa: E402
    EXCLUDED_PATHWAYS,
    R1Context,
    evaluate_r1,
    r1_prompt_times,
)
from sanad.states import R1_MET_TEXT, ReasonCode  # noqa: E402
from sanad.timeline import grid  # noqa: E402


def _r1_obs(t: datetime, *, rr: int = 18, sbp: int = 120) -> Observation:
    return Observation(
        bed=1, encounter="SYN", t=t,
        fio2=Decimal("0.40"), fio2_unit="fraction", fio2_fraction=Decimal("0.40"),
        peep=5, peep_unit="cmH2O", spo2=96, spo2_quality="good",
        rr=rr, sbp=sbp, hr=80, spont_effort_flag=True,
    )


def _r1_check(performed: datetime, *, effort: str = "adequate") -> Event:
    return Event(
        bed=1, encounter="SYN", type="vent_check",
        performed_at=performed, documented_at=performed + timedelta(minutes=4),
        effort=effort, haemodynamics="acceptable", cuff_pressure_cmH2O=25,
    )


def _held_ctx(
    start: datetime, end: datetime, *, events_extra: list[Event] | None = None,
    pathways: tuple[str, ...] = (),
) -> R1Context:
    """A context whose screen holds continuously from ``start`` (SAT + checks
    every 2 h, a steady passing observation every 5 min, a 12-h reference)."""

    obs: list[Observation] = []
    o = start - timedelta(hours=12)
    while o <= end:
        obs.append(_r1_obs(o))
        o += timedelta(minutes=5)
    events: list[Event] = [
        Event(bed=1, encounter="SYN", type="sat", t=start, result="pass")
    ]
    c = start
    while c <= end:
        events.append(_r1_check(c))
        c += timedelta(hours=2)
    if events_extra:
        events += events_extra
    return R1Context(
        encounter="SYN", bed=1, weight_kg=80, code_status="full",
        pathways=pathways, observations=tuple(obs), infusions=(),
        events=tuple(events),
    )


# --- PBT-3: an active hold or not-applicable pathway raises no prompt -------


@settings(max_examples=25)
@given(
    defer_from=st.integers(min_value=0, max_value=120),
    defer_len=st.integers(min_value=20, max_value=240),
)
def test_pbt3_active_deferral_suppresses_and_shows_review_time(
    defer_from: int, defer_len: int
) -> None:
    """While an R1 deferral covers t, R1 is ``suppressed`` (never ``met``) and
    the review time is shown (invariant 3). The window is chosen inside a long
    ``met`` span so that, without the hold, R1 would be ``met``."""

    start = _BASE                      # 19:00
    end = start + timedelta(hours=7)
    # The deferral is placed well after the >120-min duration has elapsed.
    d_start = start + timedelta(hours=3) + timedelta(minutes=5 * (defer_from // 5))
    d_until = d_start + timedelta(minutes=5 * (defer_len // 5) + 5)
    deferral = Event(
        bed=1, encounter="SYN", type="deferral", t=d_start, until=d_until,
        reason="procedure", owner="MD-oncall", rule="R1",
    )
    ctx = _held_ctx(start, end, events_extra=[deferral])

    # Probe a grid point strictly inside [d_start, d_until).
    probe = d_start + timedelta(minutes=5)
    if probe >= d_until:
        probe = d_start
    r = evaluate_r1(ctx, probe)
    assert r.state is EvaluationState.SUPPRESSED
    assert r.state is not EvaluationState.MET
    # The hold's review time is shown.
    assert d_until.strftime("%H:%M") in r.detail


@settings(max_examples=len(EXCLUDED_PATHWAYS))
@given(pathway=st.sampled_from(sorted(EXCLUDED_PATHWAYS)))
def test_pbt3_excluded_pathway_never_prompts(pathway: str) -> None:
    """A not-applicable pathway yields ``not_applicable`` and never a prompt
    (invariant 3), even where the screen would otherwise be met."""

    start = _BASE
    end = start + timedelta(hours=3)
    ctx = _held_ctx(start, end, pathways=(pathway,))
    points = grid(start, end)
    for t in points:
        assert evaluate_r1(ctx, t).state is EvaluationState.NOT_APPLICABLE
    assert r1_prompt_times(ctx, points) == []


# --- PBT-4: one prompt per episode, whatever the polling rate / duplicates --


@settings(max_examples=12)
@given(
    step_minutes=st.sampled_from([5, 10, 15]),
    duplicate=st.booleans(),
)
def test_pbt4_one_prompt_per_episode_regardless_of_polling(
    step_minutes: int, duplicate: bool
) -> None:
    """A single uninterrupted ``met`` episode raises exactly one prompt whatever
    the polling rate, duplicate records, or crossing midnight (invariant 4)."""

    start = _BASE                      # 19:00, 20 Nov
    end = start + timedelta(hours=7)   # crosses midnight into 21 Nov
    extra: list[Event] = []
    if duplicate:
        # Duplicate the SAT and a check: duplicates must not add a prompt.
        extra = [
            Event(bed=1, encounter="SYN", type="sat", t=start, result="pass"),
            _r1_check(start),
        ]
    ctx = _held_ctx(start, end, events_extra=extra)
    points = grid(start, end, timedelta(minutes=step_minutes))
    prompts = r1_prompt_times(ctx, points)
    assert len(prompts) == 1
    # And the met message is the exact approved wording where met.
    met_point = prompts[0]
    assert evaluate_r1(ctx, met_point).message == R1_MET_TEXT


# --- PBT-11: an expired confirmation never satisfies R1-d or R1-e -----------


@settings(max_examples=20)
@given(
    gap_minutes=st.integers(min_value=121, max_value=600),
)
def test_pbt11_expired_effort_confirmation_never_met(gap_minutes: int) -> None:
    """When the only effort confirmation is older than 2 h (expired), R1 is
    never ``met`` -- the expired confirmation cannot satisfy R1-d (invariant
    11, AC-DEF-12)."""

    start = _BASE
    # A single check long before t; everything else holds.
    t = start + timedelta(hours=6)
    obs: list[Observation] = []
    o = start - timedelta(hours=12)
    while o <= t:
        obs.append(_r1_obs(o))
        o += timedelta(minutes=5)
    stale_check = _r1_check(t - timedelta(minutes=gap_minutes))
    ctx = R1Context(
        encounter="SYN", bed=1, weight_kg=80, code_status="full",
        pathways=(), observations=tuple(obs), infusions=(),
        events=(
            Event(bed=1, encounter="SYN", type="sat", t=start, result="pass"),
            stale_check,
        ),
    )
    r = evaluate_r1(ctx, t)
    assert r.state is not EvaluationState.MET
    assert r.state is EvaluationState.UNKNOWN
    assert r.reason is ReasonCode.CONFIRMATION_EXPIRED


# ==========================================================================
# PBT-5 / PBT-12 (task 4): R2a is fluid-independent and never tag-suppressed.
# ==========================================================================

from sanad.r2a import (  # noqa: E402
    FLUID_UNKNOWN_LABEL,
    SPO2_BRANCH,
    R2aContext,
    evaluate_r2a,
)


def _r2a_obs(t: datetime, spo2: int, *, quality: str = "good") -> Observation:
    """A synthetic observation with a given SpO2, steady settings."""

    return Observation(
        bed=1, encounter="SYN", t=t,
        fio2=Decimal("0.40"), fio2_unit="fraction", fio2_fraction=Decimal("0.40"),
        peep=5, peep_unit="cmH2O", spo2=spo2, spo2_quality=quality,
        rr=18, sbp=120, hr=80, spont_effort_flag=True,
    )


def _r2a_desat_ctx(
    *, drop_from_minutes: int, events_extra: list[Event] | None = None,
) -> tuple[R2aContext, datetime]:
    """A context with >= 6 h of steady SpO2 96, then a sustained drop to 90.

    Returns the context and a grid time ``t`` at which the SpO2 branch has been
    at or below the median-3 threshold for more than 5 min (so R2a is ``met``
    via the SpO2 branch). ``drop_from_minutes`` is the offset (from ``_BASE``)
    at which the drop starts; the median over the previous 6 h stays ~96.
    """

    obs: list[Observation] = []
    # 6 h of steady 96 before the drop so the median is 96 and history >= 6 h.
    first = _BASE - timedelta(hours=6)
    m = int((first - _BASE).total_seconds() // 60)
    while m < drop_from_minutes:
        obs.append(_r2a_obs(_BASE + timedelta(minutes=m), 96))
        m += 5
    # The drop: SpO2 90 (>= 3 below the 96 median) sustained for 15 min.
    for k in range(4):
        obs.append(_r2a_obs(_BASE + timedelta(minutes=drop_from_minutes + 5 * k), 90))
    t = _BASE + timedelta(minutes=drop_from_minutes + 10)  # 10 min into the drop
    ctx = R2aContext(
        encounter="SYN", bed=1, pathways=(), observations=tuple(obs),
        events=tuple(events_extra or ()),
    )
    return ctx, t


# --- PBT-5: R2a is met for any fluid balance (it never reads fluids) --------


@settings(max_examples=15)
@given(
    # A fluid balance that is negative, zero/low, or simply absent: R2a must be
    # met regardless, because the oxygenation worsening is valid. R2a carries no
    # fluid records at all, so any of these cannot change its result.
    fluid_balance_ml=st.one_of(
        st.none(),
        st.integers(min_value=-5000, max_value=5000),
    ),
    drop_from=st.sampled_from([60, 120, 240, 360]),
)
def test_pbt5_r2a_met_for_any_fluid_balance(
    fluid_balance_ml: int | None, drop_from: int
) -> None:
    """When oxygenation worsening is valid, R2a is ``met`` for any fluid balance
    (negative, low, missing) (invariant 5, AC-R2a-fluid-independent). The
    ``fluid_balance_ml`` parameter is deliberately never passed into the R2a
    context -- the invariant is that it cannot matter. After D29 the "fluid
    balance unknown" label is **not** carried by a standalone R2a result (R2a
    is fluid-independent and cannot see a ledger): the orchestrator adds it for
    a cell only when R2b is ``unknown`` (see
    ``tests/test_oracle_all_beds.py``). So here, at the R2a level, the label
    must be absent."""

    ctx, t = _r2a_desat_ctx(drop_from_minutes=drop_from)
    r = evaluate_r2a(ctx, t)
    assert r.state is EvaluationState.MET
    assert SPO2_BRANCH in r.detail
    assert FLUID_UNKNOWN_LABEL not in r.detail


# --- PBT-12: a planned-change tag never suppresses the SpO2 branch ----------


@settings(max_examples=15)
@given(
    drop_from=st.sampled_from([120, 240, 360]),
    tag_reason=st.sampled_from(
        ["pre-oxygenation for suctioning", "recruitment", "proning", "suctioning"]
    ),
)
def test_pbt12_tag_never_suppresses_spo2_branch(
    drop_from: int, tag_reason: str
) -> None:
    """A planned-change tag covering the desaturation never suppresses the SpO2
    branch: R2a is still ``met`` with the tag active (invariant 12,
    AC-R2a-tags-spo2)."""

    t = _BASE + timedelta(minutes=drop_from + 10)
    tag = Event(
        bed=1, encounter="SYN", type="planned_change",
        start=_BASE + timedelta(minutes=drop_from),
        end=_BASE + timedelta(minutes=drop_from + 20),
        reason=tag_reason,
    )
    ctx, _ = _r2a_desat_ctx(drop_from_minutes=drop_from, events_extra=[tag])
    r_tagged = evaluate_r2a(ctx, t)
    assert r_tagged.state is EvaluationState.MET
    assert SPO2_BRANCH in r_tagged.detail
    # Equivalence: the same desaturation without the tag is also met, so the
    # tag demonstrably did not suppress the branch.
    ctx_no_tag, _ = _r2a_desat_ctx(drop_from_minutes=drop_from)
    assert evaluate_r2a(ctx_no_tag, t).state is EvaluationState.MET


# ==========================================================================
# PBT-6 (task 5): the R2b rolling balance is invariant to day resets, record
# order and duplicate transaction IDs; a late-documented record changes only
# evaluations at or after its documented time (requirements Section 7,
# AC-R2b-dedup-order, AC-R2b-asknown, baseline invariant 6).
#
# Task 2 proved these at the as-known-at layer; here they are asserted at the
# R2b *reduction* (the signed 72-h net the rule compares to +2,000 ml), which
# is the value whose invariance the clinical hazard actually depends on.
# ==========================================================================

from sanad.r2b import R2bContext, rolling_net_ml  # noqa: E402

# Transactions whose event time is spread across a wide span (so some fall
# inside and some outside the 72-h window) and whose documentation lag varies.
_r2b_txns = st.lists(
    st.tuples(
        st.integers(min_value=-5000, max_value=500),   # event minute (rel base)
        st.integers(min_value=0, max_value=5000),       # documentation lag
        st.sampled_from(["in", "out"]),
        st.integers(min_value=1, max_value=3000),        # ml
        st.sampled_from(["iv", "urine", "crrt_net", "crrt_effluent_gross"]),
    ),
    min_size=0, max_size=14,
)


def _mk_r2b_fluid(
    tx_id: str, ev: int, lag: int, kind: str, ml: int, source: str
) -> FluidTx:
    return FluidTx(
        bed=1, encounter="SYN", tx_id=tx_id, kind=kind, ml=ml, source=source,
        event_time=_at(ev), documented_time=_at(ev + lag),
    )


def _build_r2b(spec) -> list[FluidTx]:
    return [
        _mk_r2b_fluid(f"T{i:03d}", ev, lag, kind, ml, source)
        for i, (ev, lag, kind, ml, source) in enumerate(spec)
    ]


def _r2b_ctx(fluids: list[FluidTx]) -> R2bContext:
    # Observations are only used by R2b for the history gate; rolling_net_ml
    # (the function under test here) reads only fluids, so none are needed.
    return R2bContext(
        encounter="SYN", bed=1, anuric=False,
        fluids=tuple(fluids), observations=(),
    )


@given(spec=_r2b_txns)
def test_pbt6_r2b_net_is_order_and_duplicate_invariant(spec) -> None:
    """The 72-h net is identical whatever the record order and however many
    duplicate transaction IDs are present (invariant 6). Reversing the input
    and appending exact-duplicate rows must both leave the net unchanged."""

    fluids = _build_r2b(spec)
    t = _at(500)
    base = rolling_net_ml(_r2b_ctx(fluids), t)

    # Reversed input order -> identical net.
    assert rolling_net_ml(_r2b_ctx(list(reversed(fluids))), t) == base

    # Exact-duplicate rows (same tx_id and fields) -> identical net, because
    # dedup-by-tx_id keeps exactly one of each.
    assert rolling_net_ml(_r2b_ctx(fluids + list(fluids)), t) == base


@given(spec=_r2b_txns)
def test_pbt6_r2b_net_ignores_day_reset_distractor(spec) -> None:
    """The net is computed purely from the transaction ledger; it does not
    depend on any charting-day boundary. Shifting every event across a 07:00
    charting-day reset (by +/- a whole day) shifts which transactions fall in
    the 72-h window, but for a fixed evaluation time the reset itself carries no
    weight: the context has no daily-totals field to read (AC-R2b-no-
    dailytotals), so the only thing that can change a result is the window, not
    a reset. Here we assert the net equals a direct recomputation that knows
    nothing about charting days."""

    fluids = _build_r2b(spec)
    t = _at(500)
    window_start = t - timedelta(hours=72)

    def _counts(tx: FluidTx) -> bool:
        s = tx.source.lower()
        if s.startswith("crrt_"):
            return s == "crrt_net"
        return True

    expected = sum(
        (tx.ml if tx.kind == "in" else -tx.ml)
        for tx in {f.tx_id: f for f in sorted(
            (f for f in fluids if f.documented_time <= t),
            key=lambda f: (f.event_time, f.documented_time, repr(f)),
        )}.values()
        if window_start < tx.event_time <= t and _counts(tx)
    )
    assert rolling_net_ml(_r2b_ctx(fluids), t) == expected


@given(
    spec=_r2b_txns,
    late_event=st.integers(min_value=-5000, max_value=500),
    late_lag=st.integers(min_value=1, max_value=4000),
    late_ml=st.integers(min_value=1, max_value=3000),
)
def test_pbt6_r2b_late_record_only_affects_at_or_after_doc(
    spec, late_event: int, late_lag: int, late_ml: int
) -> None:
    """Adding a late-documented transaction changes the R2b net only at and
    after its documented time; every earlier evaluation is byte-for-byte equal
    (invariant 6 / AC-R2b-asknown; the mechanism behind bed 6)."""

    fluids = _build_r2b(spec)
    late = _mk_r2b_fluid("LATE", late_event, late_lag, "in", late_ml, "iv")
    doc = late.documented_time

    # Strictly before the documented time: the late record is invisible, so the
    # net is unchanged by its presence.
    before_t = doc - timedelta(minutes=5)
    assert (
        rolling_net_ml(_r2b_ctx(fluids + [late]), before_t)
        == rolling_net_ml(_r2b_ctx(fluids), before_t)
    )

    # At the documented time, if the late record's event time is inside the
    # 72-h window, the net increases by exactly its signed ml; otherwise it is
    # unchanged (documented, but outside the rolling window).
    with_late = rolling_net_ml(_r2b_ctx(fluids + [late]), doc)
    without_late = rolling_net_ml(_r2b_ctx(fluids), doc)
    if doc - timedelta(hours=72) < late.event_time <= doc:
        assert with_late == without_late + late_ml
    else:
        assert with_late == without_late


# ==========================================================================
# PBT-10 (task 6): a silent bed is never rendered as safe/stable/clear/green.
#
# requirements Section 7, AC-DEF-4, baseline invariant 10 (the top hazard D06:
# false reassurance). The orchestrator's display contract is: the single
# silence constant is shown iff **no** rule is ``met``, and it never contains a
# banned word; whenever any rule *is* ``met`` the silence text is not used
# (the met rule's own approved wording drives the display instead). This is
# asserted here over *every* combination of per-rule evaluation states, so the
# invariant does not depend on the 17 oracle beds.
# ==========================================================================

from sanad.evaluate import silence_display_text  # noqa: E402
from sanad.model import RuleResult  # noqa: E402
from sanad.states import (  # noqa: E402
    BANNED_SILENCE_WORDS,
    SILENCE_TEXT,
    EvaluationState,
    ReasonCode,
)

# Any of the five evaluation states; only ``MET`` is a positive ("not silent").
_eval_states = st.sampled_from(list(EvaluationState))

# A rule id label (the key in the cell's result map) -- the specific string is
# irrelevant to the silence contract, so a tiny alphabet keeps generation fast.
_rule_ids = st.sampled_from(["R1", "R2a", "R2b", "R3"])


def _mk_result(rule_id: str, state: EvaluationState) -> RuleResult:
    return RuleResult(
        rule_id=rule_id,
        state=state,
        reason=ReasonCode.OK_NOT_MET,
    )


# A results map: 0..4 rules, each with an arbitrary evaluation state. The empty
# map models a cell with no rule run yet (also silent).
_results_maps = st.dictionaries(
    keys=_rule_ids,
    values=_eval_states,
    min_size=0,
    max_size=4,
).map(lambda d: {rid: _mk_result(rid, s) for rid, s in d.items()})


def test_pbt10_silence_text_is_free_of_banned_words() -> None:
    """The single silence constant never contains safe/stable/clear/green."""

    lowered = SILENCE_TEXT.lower()
    for word in BANNED_SILENCE_WORDS:
        assert word not in lowered


@given(results=_results_maps)
def test_pbt10_silent_iff_nothing_met(results) -> None:
    """``display_text`` is the silence constant exactly when no rule is ``met``,
    and empty otherwise -- so a silent bed is always and only rendered with the
    vetted silence string (invariant 10, AC-DEF-4)."""

    any_met = any(r.state is EvaluationState.MET for r in results.values())
    text = silence_display_text(results)
    if any_met:
        assert text == ""
    else:
        assert text == SILENCE_TEXT


@given(results=_results_maps)
def test_pbt10_display_text_never_uses_a_banned_word(results) -> None:
    """Whatever the mix of states, the rendered display text never contains a
    banned reassurance word (safe/stable/clear/green)."""

    text = silence_display_text(results).lower()
    for word in BANNED_SILENCE_WORDS:
        assert word not in text


# ==========================================================================
# PBT-7 / PBT-8 (task 7): the R3 task-tracker invariants.
#
# PBT-7: an episode that is acknowledged but not assessed stays open with its
# deadline -- acknowledging keeps R3 ``met`` and never resolves it (requirements
# Section 7, AC-R3-workflow, AC-DEF-2, baseline invariant 7).
#
# PBT-8: another encounter's task occurring in the same bed never satisfies or
# resets the current encounter's task, in either direction (requirements
# Section 7, AC-R3-encounter, baseline invariant 8).
# ==========================================================================

from sanad.r3 import (  # noqa: E402
    GRACE,
    R3Context,
    evaluate_r3,
    workflow_state_at,
)
from sanad.states import WorkflowState  # noqa: E402


def _r3_check(
    performed_min: int,
    *,
    encounter: str = "SYN",
    effort: str | None = "adequate",
    haemodynamics: str | None = "acceptable",
    cuff: int | None = 25,
    doc_lag: int = 4,
) -> Event:
    return Event(
        bed=1, encounter=encounter, type="vent_check",
        performed_at=_at(performed_min),
        documented_at=_at(performed_min + doc_lag),
        effort=effort, haemodynamics=haemodynamics, cuff_pressure_cmH2O=cuff,
    )


def _r3_ctx(events: list[Event], encounter: str = "SYN") -> R3Context:
    return R3Context(
        encounter=encounter, bed=1, events=tuple(events), observations=()
    )


# A positive admission offset (minutes after base) and an acknowledgement delay
# after the episode goes overdue; both bounded so generation stays fast.
_adm_offset = st.integers(min_value=0, max_value=600)
_ack_delay = st.integers(min_value=0, max_value=90)


@given(adm_off=_adm_offset, ack_delay=_ack_delay)
def test_pbt7_acknowledge_keeps_episode_open_and_met(
    adm_off: int, ack_delay: int
) -> None:
    """With an admission and no valid check, the first-check episode goes
    overdue and stays ``met`` after an acknowledgement -- the episode remains
    open with its deadline, never resolved by the ack alone (invariant 7)."""

    adm = Event(bed=1, encounter="SYN", type="admission", t=_at(adm_off))
    # First check due = admission + 30 min; overdue at due + 10 min grace.
    overdue_at = _at(adm_off) + timedelta(minutes=30) + GRACE
    ack_at = overdue_at + timedelta(minutes=ack_delay)
    ack = Event(
        bed=1, encounter="SYN", type="staff_action", action="acknowledge",
        rule="R3", t=ack_at,
    )
    ctx = _r3_ctx([adm, ack])

    # At the overdue instant the episode is met; its workflow is NOTIFIED until
    # the acknowledgement lands (ACKNOWLEDGED once ack_at <= t).
    r_overdue = evaluate_r3(ctx, overdue_at)
    assert r_overdue.state is EvaluationState.MET
    expected_wf_at_overdue = (
        WorkflowState.ACKNOWLEDGED
        if ack_at <= overdue_at
        else WorkflowState.NOTIFIED
    )
    assert workflow_state_at(ctx, overdue_at) is expected_wf_at_overdue

    # At/after the ack: still met, and the episode is open (acknowledged), not
    # resolved -- acknowledging never closes the episode (AC-DEF-2).
    probe = ack_at + timedelta(minutes=5)
    r = evaluate_r3(ctx, probe)
    assert r.state is EvaluationState.MET
    assert workflow_state_at(ctx, probe) is WorkflowState.ACKNOWLEDGED


from sanad.model import Dataset, Encounter  # noqa: E402
from sanad.r3 import context_for as r3_context_for  # noqa: E402


def _two_encounter_dataset(
    a_events: list[Event], b_events: list[Event]
) -> Dataset:
    """A minimal two-encounter, same-bed dataset (bed 1: A then B)."""

    enc_a = Encounter(
        bed=1, encounter="A", age=60, sex="M", weight_kg=70,
        code_status="full", pathways=(), anuric=False, scenario="syn_a",
    )
    enc_b = Encounter(
        bed=1, encounter="B", age=60, sex="F", weight_kg=70,
        code_status="full", pathways=(), anuric=False, scenario="syn_b",
    )
    events = tuple(a_events) + tuple(b_events)
    return Dataset(
        meta={}, encounters=(enc_a, enc_b),
        observations=(), infusions=(), events=events, fluids=(),
        daily_totals=(),
        by_encounter={"A": enc_a, "B": enc_b},
        by_bed={1: (enc_a, enc_b)},
    )


@given(
    adm_off=_adm_offset,
    other_check_min=st.integers(min_value=0, max_value=600),
)
def test_pbt8_other_encounter_check_never_affects_this_task(
    adm_off: int, other_check_min: int
) -> None:
    """A valid check belonging to a *different* encounter in the same bed never
    satisfies or resets the current encounter's task (invariant 8,
    AC-R3-encounter). Encounter A is admitted with no valid check (so it goes
    overdue); encounter B records a valid check in the same bed. Because
    ``context_for`` is strictly per-encounter, A's result is identical with or
    without B's check present, and B's context never contains any of A's
    events -- no inheritance in either direction."""

    a_adm = Event(bed=1, encounter="A", type="admission", t=_at(adm_off))
    b_check = _r3_check(other_check_min, encounter="B")

    overdue_at = _at(adm_off) + timedelta(minutes=30) + GRACE
    probe = overdue_at + timedelta(minutes=5)

    # Full dataset (A + B) vs A-only: A's per-encounter context must be the same
    # events either way, so A's evaluation is unchanged by B's check.
    ds_both = _two_encounter_dataset([a_adm], [b_check])
    ds_a_only = _two_encounter_dataset([a_adm], [])

    ctx_a_both = r3_context_for(ds_both, "A")
    ctx_a_only = r3_context_for(ds_a_only, "A")

    # The per-encounter context carries only that encounter's events.
    assert all(e.encounter == "A" for e in ctx_a_both.events)
    assert ctx_a_both.events == ctx_a_only.events

    # A is overdue regardless of B's check in the same bed (no inheritance).
    assert evaluate_r3(ctx_a_both, probe).state is EvaluationState.MET
    assert evaluate_r3(ctx_a_only, probe).state is EvaluationState.MET

    # B's context never contains A's admission/overdue history (no inheritance
    # in the other direction either).
    ctx_b = r3_context_for(ds_both, "B")
    assert all(e.encounter == "B" for e in ctx_b.events)
