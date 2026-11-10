"""Generate Sanad's synthetic ward for rules v3: 17 fictional ventilated adults, 24 h of data (20 Nov 07:00 -> 21 Nov 07:00).

Deterministic: the same seed gives byte-identical files. Standard library only.
Scenarios and expected outcomes: data/SCENARIOS.md (written before this generator). Rules: docs/EVIDENCE.md v3.
Usage: python3 -I data/generate.py [--seed 42] [--out DIR]
"""
import argparse
import datetime as dt
import json
import pathlib
import random

TZ = dt.timezone(dt.timedelta(hours=1))  # Europe/Madrid in November (CET)
START = dt.datetime(2026, 11, 20, 7, 0, tzinfo=TZ)   # 12 h of pre-shift history
NIGHT = dt.datetime(2026, 11, 20, 19, 0, tzinfo=TZ)  # board shows 19:00-07:00
END = dt.datetime(2026, 11, 21, 7, 0, tzinfo=TZ)
STEP = dt.timedelta(minutes=5)


def at(hhmm):
    """Clock time on the 24-h window: 07:00-23:59 is 20 Nov, 00:00-06:59 is 21 Nov."""
    h, m = map(int, hhmm.split(":"))
    day = 21 if h < 7 else 20
    return dt.datetime(2026, 11, day, h, m, tzinfo=TZ)


def iso(t):
    return t.isoformat(timespec="seconds")


def grid(a=START, b=END):
    t = a
    while t <= b:
        yield t
        t += STEP


# bed, encounter suffix, age, sex, weight_kg (None = missing), code status, pathways, scenario
PATIENTS = [
    (1, "", 64, "M", 82, "full", [], "sbt_candidate"),
    (2, "", 58, "F", 70, "full", [], "sedated_no_sat"),
    (3, "", 71, "M", 90, "full", [], "pressor_unconfirmed"),
    (4, "", 77, "F", 66, "full", [], "flash_oedema"),
    (5, "", 52, "M", 95, "full", [], "fluid_positive_stable"),
    (6, "", 69, "F", 74, "full", [], "fluid_and_oxygen"),
    (7, "", 45, "M", 88, "full", [], "probe_artefact"),
    (8, "", 60, "F", 63, "full", [], "tagged_preoxygenation"),
    (9, "", 55, "M", 79, "full", [], "feed_outage"),
    (10, "", 73, "F", 68, "full", [], "missed_check"),
    (11, "", 39, "M", 85, "full", ["vv_ecmo"], "ecmo"),
    (12, "", 81, "F", 60, "dnr", [], "dnr_sbt_candidate"),
    (13, "A", 66, "M", 77, "full", [], "reassign_A"),
    (13, "B", 49, "F", 72, "full", [], "reassign_B"),
    (14, "", 62, "M", None, "full", [], "weight_missing"),
    (15, "", 57, "F", 69, "full", [], "deferral"),
    (16, "", 50, "M", 92, "full", [], "suction_desat"),
    (17, "", 68, "M", 84, "full", [], "crrt"),
]

SPAN = {"reassign_A": (START, at("22:55")), "reassign_B": (at("23:15"), END)}
SAT = {"sbt_candidate": "20:15", "pressor_unconfirmed": "19:30", "dnr_sbt_candidate": "21:00",
       "weight_missing": "19:30", "deferral": "18:30"}
NET_ML = {"flash_oedema": 300, "fluid_positive_stable": 3200, "fluid_and_oxygen": 1600, "probe_artefact": 800,
          "ecmo": 1000, "reassign_A": 2400}


def enc(bed, suffix):
    return f"E{bed:02d}{suffix}-1120"


def baseline(scn):
    b = dict(fio2=0.35, peep=5, spo2=96, rr=18, sbp=120, hr=86)
    b.update({"sbt_candidate": dict(fio2=0.40), "sedated_no_sat": dict(fio2=0.40, rr=14),
              "pressor_unconfirmed": dict(fio2=0.40, sbp=97, hr=98), "fluid_and_oxygen": dict(fio2=0.40, peep=8),
              "ecmo": dict(fio2=0.30, peep=10, rr=10), "dnr_sbt_candidate": dict(fio2=0.40)}.get(scn, {}))
    return b


def vitals_at(scn, t, b):
    """Scenario-driven FiO2/PEEP/SpO2 at time t (SpO2 is noise-free)."""
    fio2, peep, spo2 = b["fio2"], b["peep"], b["spo2"]
    if scn == "sbt_candidate" and t < NIGHT:
        fio2, peep = 0.50, 8
    if scn == "flash_oedema" and t >= at("02:10"):
        ramp = min(1.0, (t - at("02:10")) / dt.timedelta(minutes=30))
        fio2, peep, spo2 = 0.35 + 0.45 * ramp, 5 + round(7 * ramp), 95 - round(9 * ramp)
    if scn == "fluid_and_oxygen" and t >= at("01:00"):
        fio2, peep, spo2 = 0.55, 10, 93
    if scn == "tagged_preoxygenation" and at("04:00") <= t < at("04:05"):
        fio2 = 1.0
    if scn == "suction_desat" and at("03:00") <= t < at("03:10"):
        fio2, spo2 = 1.0, 82
    return round(fio2, 2), peep, spo2


def observations(rng, bed, e, scn, b):
    a, z = SPAN.get(scn, (START, END))
    rows = []
    for i, t in enumerate(grid(a, z)):
        if scn == "feed_outage" and at("01:00") <= t < at("02:30"):
            continue
        fio2, peep, spo2 = vitals_at(scn, t, b)
        quality = "good"
        if scn == "probe_artefact" and t == at("03:00"):
            spo2, quality = 74, "poor"
        pct = scn == "sbt_candidate" and t >= NIGHT and i % 2
        rows.append(dict(t=iso(t), bed=bed, encounter=e, fio2=round(fio2 * 100) if pct else fio2,
                         fio2_unit="percent" if pct else "fraction", peep=peep, peep_unit="cmH2O",
                         spo2=spo2, spo2_quality=quality, rr=b["rr"] + rng.choice([-1, 0, 1]),
                         spont_effort_flag=scn not in ("sedated_no_sat", "ecmo"),
                         sbp=b["sbp"] + rng.randint(-4, 5), hr=b["hr"] + rng.randint(-3, 3)))
    if scn == "probe_artefact":
        rows.append(dict(rows[-1], t=iso(at("03:01") + dt.timedelta(seconds=30)), spo2=74, spo2_quality="poor"))
    return sorted(rows, key=lambda r: r["t"])


def infusions(bed, e, scn):
    s, z = iso(START - dt.timedelta(hours=6)), iso(END)
    rx = {"sedated_no_sat": [("propofol", 50, "mcg/kg/min")],
          "pressor_unconfirmed": [("norepinephrine", 8, "mcg/min"), ("vasopressin", 0.03, "units/min")],
          "weight_missing": [("norepinephrine", 0.08, "mcg/kg/min")]}.get(scn, [])
    return [dict(bed=bed, encounter=e, drug=d, dose=v, unit=u, start=s, end=z) for d, v, u in rx]


def check(bed, e, when, haemo="acceptable", doc_delay=4):
    t = at(when) if isinstance(when, str) else when
    return dict(bed=bed, encounter=e, type="vent_check", performed_at=iso(t),
                documented_at=iso(t + dt.timedelta(minutes=doc_delay)),
                effort="adequate", haemodynamics=haemo, cuff_pressure_cmH2O=25)


def events(bed, e, scn):
    ev = []
    if scn in SAT:
        ev.append(dict(bed=bed, encounter=e, type="sat", result="pass", t=iso(at(SAT[scn]))))
    if scn == "sedated_no_sat":
        ev.append(dict(bed=bed, encounter=e, type="rass", value=-4, t=iso(at("19:00"))))
    if scn == "tagged_preoxygenation":
        ev.append(dict(bed=bed, encounter=e, type="planned_change", reason="pre-oxygenation for suctioning",
                       start=iso(at("04:00")), end=iso(at("04:05"))))
    if scn == "suction_desat":
        ev.append(dict(bed=bed, encounter=e, type="planned_change", reason="suctioning",
                       start=iso(at("03:00")), end=iso(at("03:10"))))
    if scn == "feed_outage":
        ev.append(dict(bed=bed, encounter=e, type="feed_status", status="down", start=iso(at("01:00")), end=iso(at("02:30"))))
    if scn == "deferral":
        ev.append(dict(bed=bed, encounter=e, type="deferral", rule="R1", until=iso(at("01:30")),
                       reason="planned procedure overnight", owner="MD-oncall", t=iso(at("20:45"))))
    if scn == "missed_check":
        ev.append(dict(bed=bed, encounter=e, type="staff_action", action="acknowledge", rule="R3", t=iso(at("01:12")), by="RN-night-2"))
    if scn == "reassign_A":
        ev.append(dict(bed=bed, encounter=e, type="discharge", t=iso(at("23:00"))))
    if scn == "reassign_B":
        ev.append(dict(bed=bed, encounter=e, type="admission", t=iso(at("23:15"))))
    # 2-hourly ventilation checks (odd hours), each with the required fields
    if scn == "reassign_A":
        times = [f"{h:02d}:00" for h in range(7, 23, 2)] + ["22:50"]
    elif scn == "reassign_B":
        times = ["23:40", "01:35", "03:30", "05:25"]
    else:
        times = [f"{h:02d}:00" for h in list(range(7, 24, 2)) + list(range(1, 7, 2))]
        if scn == "missed_check":
            times.remove("01:00")
    haemo = "md_review_requested" if scn == "pressor_unconfirmed" else "acceptable"
    ev += [check(bed, e, x, haemo) for x in times]
    if scn == "missed_check":
        ev.append(check(bed, e, "01:50", doc_delay=2))
    return sorted(ev, key=lambda x: x.get("t") or x.get("start") or x.get("performed_at"))


def fluids(rng, bed, e, scn):
    """Zero-net in/out pairs every 3 h (same time, so a window edge never splits a pair) + the scenario's net."""
    txs, n = [], 0

    def tx(kind, ml, t, source, doc=None):
        nonlocal n
        n += 1
        txs.append(dict(tx_id=f"F{bed:02d}{e[3:4] if e[3:4].isalpha() else ''}-{n:04d}", bed=bed, encounter=e,
                        kind=kind, ml=ml, source=source, event_time=iso(t), documented_time=iso(doc or t)))

    if scn == "reassign_B":
        tx("in", 500, at("23:20"), "iv")
        tx("out", 100, at("01:00"), "urine")
        tx("out", 100, at("04:00"), "urine")
        return txs
    a, z = SPAN.get(scn, (START, END))
    t = END - dt.timedelta(hours=84)
    while t <= min(z, END):
        if not (scn == "crrt" and t > at("12:00")):  # last urine output at 10:00
            ml = rng.choice([200, 300, 400])
            tx("in", ml, t, "iv")
            tx("out", ml, t, "urine")
        t += dt.timedelta(hours=3)
    tx("in", NET_ML.get(scn, 500), at("08:00"), "iv")
    if scn == "fluid_and_oxygen":
        tx("in", 1000, at("20:00"), "iv", doc=at("02:00"))  # charted 6 h late
    if scn == "crrt":
        tx("in", 5500, at("09:00"), "iv")  # IV total +6.0 L with the 500 ml above
        for h in ("10:00", "16:00", "22:00", "04:00"):
            tx("out", 875, at(h), "crrt_net")
            tx("out", 18875, at(h), "crrt_effluent_gross")
            tx("in", 18000, at(h), "crrt_replacement_gross")
    if scn in ("fluid_positive_stable", "fluid_and_oxygen"):
        dup_idx = (2, 6) if scn == "fluid_positive_stable" else (4,)
        txs += [dict(txs[i]) for i in dup_idx if txs[i]["kind"] == "in"] or [dict(txs[0])]
    return txs


def daily_totals(txs):
    """Charting-day counters that reset at 07:00: a distractor (rules must use transactions)."""
    days = {}
    for x in {x["tx_id"]: x for x in txs}.values():
        if x["source"].endswith("_gross"):
            continue
        day = (dt.datetime.fromisoformat(x["event_time"]) - dt.timedelta(hours=7)).date().isoformat()
        days[day] = days.get(day, 0) + (x["ml"] if x["kind"] == "in" else -x["ml"])
    return [dict(bed=txs[0]["bed"], encounter=txs[0]["encounter"], charting_day_from_0700=d, net_ml=v)
            for d, v in sorted(days.items())]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    out = pathlib.Path(a.out or pathlib.Path(__file__).parent / f"ward_seed{a.seed}")
    out.mkdir(parents=True, exist_ok=True)
    rng = random.Random(a.seed)
    files = {k: [] for k in ("observations", "infusions", "events", "fluids", "daily_totals")}
    patients = []
    for bed, sfx, age, sex, kg, code, path, scn in PATIENTS:
        e, b = enc(bed, sfx), baseline(scn)
        patients.append(dict(bed=bed, encounter=e, age=age, sex=sex, weight_kg=kg, code_status=code,
                             pathways=path, anuric=False, scenario=scn, fictional=True))
        files["observations"] += observations(rng, bed, e, scn, b)
        files["infusions"] += infusions(bed, e, scn)
        files["events"] += events(bed, e, scn)
        fx = fluids(rng, bed, e, scn)
        files["fluids"] += fx
        files["daily_totals"] += daily_totals(fx)
    meta = dict(seed=a.seed, rules_baseline="v3", data_start=iso(START), night_start=iso(NIGHT), night_end=iso(END),
                step_minutes=5, beds=17, encounters=len(PATIENTS),
                note="Fictional patients. Synthetic data only. Not for clinical use.")
    (out / "ward.json").write_text(json.dumps(dict(meta=meta, patients=patients), indent=1) + "\n")
    for name, rows in files.items():
        (out / f"{name}.jsonl").write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in rows))
    print(f"wrote {out}: " + ", ".join(f"{k}={len(v)}" for k, v in files.items()))


if __name__ == "__main__":
    main()
