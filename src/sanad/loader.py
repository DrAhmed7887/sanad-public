"""Load and validate the fixed synthetic dataset into typed records.

Reads ``ward.json`` (encounters) and the five JSONL files with the stdlib
``json`` module, line by line. Required fields are validated, times are parsed
as timezone-aware ``datetime`` and FiO2 is normalised via :mod:`sanad.units`.
Unknown FiO2 unit strings surface the same ``UnsupportedUnitError`` the rule
layer handles.

The engine only ever *reads* ``data/ward_seed42/``; it never writes to
``docs/`` or ``data/``. ``daily_totals.jsonl`` is loaded into
:class:`~sanad.model.DailyTotal` purely so tests can prove the rules ignore it.

Pure given the file bytes: no network, no wall-clock, isolated-mode safe.
Records are returned in input (file) order inside immutable tuples; rule
modules canonicalise before reducing, so file order never changes a result.

Stdlib only.
"""

from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable

from .model import (
    DailyTotal,
    Dataset,
    Encounter,
    Event,
    FluidTx,
    Infusion,
    Observation,
)
from .units import normalise_fio2

__all__ = ["load_dataset", "DEFAULT_DATA_DIR", "LoaderError"]

# Default dataset location, resolved relative to the repo root (three parents
# up from this file: src/sanad/loader.py -> repo root).
DEFAULT_DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "ward_seed42"

_OBS_REQUIRED = (
    "bed", "encounter", "fio2", "fio2_unit", "peep", "peep_unit",
    "spo2", "spo2_quality", "rr", "sbp", "hr", "spont_effort_flag", "t",
)
_INFUSION_REQUIRED = ("bed", "encounter", "drug", "dose", "unit", "start", "end")
_FLUID_REQUIRED = (
    "bed", "encounter", "tx_id", "kind", "ml", "source",
    "event_time", "documented_time",
)
_ENCOUNTER_REQUIRED = (
    "bed", "encounter", "age", "sex", "weight_kg", "code_status",
    "pathways", "anuric", "scenario",
)
_DAILY_REQUIRED = ("bed", "encounter", "charting_day_from_0700", "net_ml")

_KNOWN_EVENT_TYPES = frozenset(
    {"sat", "rass", "vent_check", "planned_change", "feed_status",
     "deferral", "staff_action", "admission", "discharge"}
)


class LoaderError(Exception):
    """A dataset file was missing a required field or malformed."""


def _parse_dt(value: str) -> datetime:
    """Parse an ISO-8601 timestamp into a timezone-aware ``datetime``."""

    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        raise LoaderError(f"timestamp {value!r} is not timezone-aware")
    return dt


def _require(record: dict, keys: Iterable[str], where: str) -> None:
    missing = [k for k in keys if k not in record]
    if missing:
        raise LoaderError(f"{where}: missing field(s) {missing}: {record!r}")


def _read_jsonl(path: Path) -> list[dict]:
    """Read a JSONL file into a list of dicts, skipping blank lines."""

    records: list[dict] = []
    with path.open("r", encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError as exc:  # pragma: no cover - defensive
                raise LoaderError(f"{path.name}:{lineno}: invalid JSON: {exc}") from exc
            if not isinstance(obj, dict):
                raise LoaderError(f"{path.name}:{lineno}: expected object")
            records.append(obj)
    return records


def _load_encounters(data_dir: Path) -> tuple[dict, tuple[Encounter, ...]]:
    path = data_dir / "ward.json"
    with path.open("r", encoding="utf-8") as fh:
        doc = json.load(fh)
    if not isinstance(doc, dict) or "patients" not in doc:
        raise LoaderError("ward.json: expected object with 'patients'")
    meta = doc.get("meta", {})
    encounters: list[Encounter] = []
    for rec in doc["patients"]:
        _require(rec, _ENCOUNTER_REQUIRED, "ward.json patient")
        weight = rec["weight_kg"]
        encounters.append(
            Encounter(
                bed=int(rec["bed"]),
                encounter=str(rec["encounter"]),
                age=int(rec["age"]),
                sex=str(rec["sex"]),
                weight_kg=None if weight is None else int(weight),
                code_status=str(rec["code_status"]),
                pathways=tuple(rec["pathways"]),
                anuric=bool(rec["anuric"]),
                scenario=str(rec["scenario"]),
            )
        )
    return meta, tuple(encounters)


def _load_observations(data_dir: Path) -> tuple[Observation, ...]:
    out: list[Observation] = []
    for rec in _read_jsonl(data_dir / "observations.jsonl"):
        _require(rec, _OBS_REQUIRED, "observations.jsonl")
        fio2_raw = Decimal(str(rec["fio2"]))
        fio2_fraction = normalise_fio2(rec["fio2"], str(rec["fio2_unit"]))
        out.append(
            Observation(
                bed=int(rec["bed"]),
                encounter=str(rec["encounter"]),
                t=_parse_dt(rec["t"]),
                fio2=fio2_raw,
                fio2_unit=str(rec["fio2_unit"]),
                fio2_fraction=fio2_fraction,
                peep=int(rec["peep"]),
                peep_unit=str(rec["peep_unit"]),
                spo2=int(rec["spo2"]),
                spo2_quality=str(rec["spo2_quality"]),
                rr=int(rec["rr"]),
                sbp=int(rec["sbp"]),
                hr=int(rec["hr"]),
                spont_effort_flag=bool(rec["spont_effort_flag"]),
            )
        )
    return tuple(out)


def _load_infusions(data_dir: Path) -> tuple[Infusion, ...]:
    out: list[Infusion] = []
    for rec in _read_jsonl(data_dir / "infusions.jsonl"):
        _require(rec, _INFUSION_REQUIRED, "infusions.jsonl")
        out.append(
            Infusion(
                bed=int(rec["bed"]),
                encounter=str(rec["encounter"]),
                drug=str(rec["drug"]),
                dose=Decimal(str(rec["dose"])),
                unit=str(rec["unit"]),
                start=_parse_dt(rec["start"]),
                end=_parse_dt(rec["end"]),
            )
        )
    return tuple(out)


def _opt_dt(rec: dict, key: str) -> datetime | None:
    value = rec.get(key)
    return None if value is None else _parse_dt(value)


def _load_events(data_dir: Path) -> tuple[Event, ...]:
    out: list[Event] = []
    for rec in _read_jsonl(data_dir / "events.jsonl"):
        _require(rec, ("bed", "encounter", "type"), "events.jsonl")
        etype = str(rec["type"])
        if etype not in _KNOWN_EVENT_TYPES:
            raise LoaderError(f"events.jsonl: unknown event type {etype!r}")
        out.append(
            Event(
                bed=int(rec["bed"]),
                encounter=str(rec["encounter"]),
                type=etype,
                t=_opt_dt(rec, "t"),
                result=rec.get("result"),
                value=rec.get("value"),
                performed_at=_opt_dt(rec, "performed_at"),
                documented_at=_opt_dt(rec, "documented_at"),
                effort=rec.get("effort"),
                haemodynamics=rec.get("haemodynamics"),
                cuff_pressure_cmH2O=rec.get("cuff_pressure_cmH2O"),
                start=_opt_dt(rec, "start"),
                end=_opt_dt(rec, "end"),
                reason=rec.get("reason"),
                status=rec.get("status"),
                until=_opt_dt(rec, "until"),
                owner=rec.get("owner"),
                rule=rec.get("rule"),
                action=rec.get("action"),
                by=rec.get("by"),
            )
        )
    return tuple(out)


def _load_fluids(data_dir: Path) -> tuple[FluidTx, ...]:
    out: list[FluidTx] = []
    for rec in _read_jsonl(data_dir / "fluids.jsonl"):
        _require(rec, _FLUID_REQUIRED, "fluids.jsonl")
        out.append(
            FluidTx(
                bed=int(rec["bed"]),
                encounter=str(rec["encounter"]),
                tx_id=str(rec["tx_id"]),
                kind=str(rec["kind"]),
                ml=int(rec["ml"]),
                source=str(rec["source"]),
                event_time=_parse_dt(rec["event_time"]),
                documented_time=_parse_dt(rec["documented_time"]),
            )
        )
    return tuple(out)


def _load_daily_totals(data_dir: Path) -> tuple[DailyTotal, ...]:
    out: list[DailyTotal] = []
    for rec in _read_jsonl(data_dir / "daily_totals.jsonl"):
        _require(rec, _DAILY_REQUIRED, "daily_totals.jsonl")
        out.append(
            DailyTotal(
                bed=int(rec["bed"]),
                encounter=str(rec["encounter"]),
                charting_day_from_0700=str(rec["charting_day_from_0700"]),
                net_ml=int(rec["net_ml"]),
            )
        )
    return tuple(out)


def load_dataset(data_dir: Path | str | None = None) -> Dataset:
    """Load the whole fixed dataset into a :class:`~sanad.model.Dataset`.

    ``data_dir`` defaults to ``data/ward_seed42`` in the repo. Raises
    :class:`LoaderError` on a missing/malformed required field and
    :class:`~sanad.units.UnsupportedUnitError` on an unknown FiO2 unit.
    """

    base = Path(data_dir) if data_dir is not None else DEFAULT_DATA_DIR
    if not base.is_dir():
        raise LoaderError(f"dataset directory not found: {base}")

    meta, encounters = _load_encounters(base)
    observations = _load_observations(base)
    infusions = _load_infusions(base)
    events = _load_events(base)
    fluids = _load_fluids(base)
    daily_totals = _load_daily_totals(base)

    by_encounter: dict[str, Encounter] = {e.encounter: e for e in encounters}
    by_bed: dict[int, tuple[Encounter, ...]] = {}
    for enc in encounters:
        by_bed[enc.bed] = by_bed.get(enc.bed, ()) + (enc,)

    return Dataset(
        meta=meta,
        encounters=encounters,
        observations=observations,
        infusions=infusions,
        events=events,
        fluids=fluids,
        daily_totals=daily_totals,
        by_encounter=by_encounter,
        by_bed=by_bed,
    )
