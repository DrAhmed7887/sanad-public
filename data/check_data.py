"""Check that the generated ward contains exactly the facts SCENARIOS.md (v3) promises.

These are DATA checks (inputs exist as described), not tests of the rules engine, which is not built yet.
Usage: python3 -I data/check_data.py [data/ward_seed42]   Writes data/check_results.txt; exit 1 on any failure.
"""
import datetime as dt
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).parent
D = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else HERE / "ward_seed42"
load = lambda n: [json.loads(l) for l in (D / f"{n}.jsonl").read_text().splitlines()]
obs, ev, fl, inf = load("observations"), load("events"), load("fluids"), load("infusions")
ward = json.loads((D / "ward.json").read_text())
T = dt.datetime.fromisoformat
TZ = dt.timezone(dt.timedelta(hours=1))
lines, fails = [], []


def at(hhmm):
    h, m = map(int, hhmm.split(":"))
    return dt.datetime(2026, 11, 21 if h < 7 else 20, h, m, tzinfo=TZ)


def check(cid, name, ok, detail=""):
    line = f"{'PASS' if ok else 'FAIL'}  {cid}  {name}{('  — ' + detail) if detail else ''}"
    lines.append(line)
    print(line)
    if not ok:
        fails.append(cid)


def of(rows, e):
    return [r for r in rows if r["encounter"] == e]


def fio2(r):
    return r["fio2"] / 100 if r["fio2_unit"] == "percent" else r["fio2"]


def net_known(e, t):
    """72-h net as known at t: documented by t, event in (t-72h, t], deduplicated, gross CRRT ignored."""
    uniq = {x["tx_id"]: x for x in of(fl, e)}.values()
    keep = [x for x in uniq if T(x["documented_time"]) <= t and t - dt.timedelta(hours=72) < T(x["event_time"]) <= t
            and not x["source"].endswith("_gross")]
    return sum(x["ml"] if x["kind"] == "in" else -x["ml"] for x in keep)


def obs_at(e, t):
    return next((r for r in of(obs, e) if T(r["t"]) == t), None)


E = lambda b, s="": f"E{b:02d}{s}-1120"
check("DC01", "24 h of observations for an all-day bed (289 points)", len(of(obs, E(1))) == 289, str(len(of(obs, E(1)))))
b1 = of(obs, E(1))
check("DC02", "bed 1 FiO2 in both units at night, all normalise to 0.40", {r["fio2_unit"] for r in b1 if T(r["t"]) >= at("19:00")} == {"fraction", "percent"}
      and all(abs(fio2(r) - 0.40) < 1e-9 for r in b1 if T(r["t"]) >= at("19:00")))
check("DC03", "bed 1 pre-shift FiO2 0.50 / PEEP 8 (R1 b lookback)", all(fio2(r) == 0.50 and r["peep"] == 8 for r in b1 if T(r["t"]) < at("19:00")))
sat = {e["encounter"]: e["t"] for e in ev if e["type"] == "sat"}
check("DC04", "SAT times: bed 1 20:15, 3 19:30, 12 21:00, 14 19:30, 15 18:30; none for 2, 4", sat.get(E(1), "")[11:16] == "20:15"
      and sat.get(E(3), "")[11:16] == "19:30" and sat.get(E(12), "")[11:16] == "21:00" and sat.get(E(14), "")[11:16] == "19:30"
      and sat.get(E(15), "")[11:16] == "18:30" and E(2) not in sat and E(4) not in sat)
vc = [e for e in ev if e["type"] == "vent_check"]
check("DC05", "every check has the required fields", all(e.get("effort") and e.get("haemodynamics") and e.get("cuff_pressure_cmH2O") is not None for e in vc))
check("DC06", "bed 3 checks record haemodynamics 'md_review_requested'; vasopressin present",
      all(e["haemodynamics"] == "md_review_requested" for e in of(vc, E(3))) and any(i["drug"] == "vasopressin" for i in of(inf, E(3))))
b4 = {r["t"][11:16]: r for r in of(obs, E(4)) if T(r["t"]) >= at("02:05") and T(r["t"]) <= at("02:50")}
check("DC07", "bed 4 SpO2 96→95→93→92 at 02:05/02:10/02:15/02:20; FiO2 0.50 and PEEP 7 at 02:20",
      [b4[k]["spo2"] for k in ("02:05", "02:10", "02:15", "02:20")] == [96, 95, 93, 92] and b4["02:20"]["fio2"] == 0.5 and b4["02:20"]["peep"] == 7)
for b, s, want in ((4, "", 300), (5, "", 3200), (7, "", 800), (11, "", 1000), (13, "A", 2400)):
    t = at("22:55") if s == "A" else at("06:55")
    check(f"DC08-{b}{s}", f"bed {b}{s} 72-h net as known = {want:+} ml", net_known(E(b, s), t) == want, f"got {net_known(E(b, s), t):+}")
check("DC09", "bed 5 has 2 duplicate IDs; naive sum differs", len(of(fl, E(5))) - len({x['tx_id'] for x in of(fl, E(5))}) == 2)
check("DC10", "bed 6 known net +1600 at 01:55 and +2600 at 02:00 (late entry)", net_known(E(6), at("01:55")) == 1600 and net_known(E(6), at("02:00")) == 2600,
      f"{net_known(E(6), at('01:55'))} / {net_known(E(6), at('02:00'))}")
b6 = obs_at(E(6), at("01:00"))
check("DC11", "bed 6 at 01:00: FiO2 0.55, PEEP 10, SpO2 93", (b6["fio2"], b6["peep"], b6["spo2"]) == (0.55, 10, 93))
check("DC12", "bed 7 poor SpO2 only at 03:00 and 03:01:30", sorted(r["t"][11:19] for r in of(obs, E(7)) if r["spo2_quality"] == "poor") == ["03:00:00", "03:01:30"])
check("DC13", "bed 8 tag 04:00-04:05; bed 16 tag 03:00-03:10", any(e["type"] == "planned_change" and e["start"][11:16] == "04:00" for e in of(ev, E(8)))
      and any(e["type"] == "planned_change" and e["end"][11:16] == "03:10" for e in of(ev, E(16))))
b9 = sorted(r["t"][11:16] for r in of(obs, E(9)) if at("00:50") <= T(r["t"]) <= at("02:35"))
check("DC14", "bed 9: last obs 00:55, next 02:30", b9 == ["00:50", "00:55", "02:30", "02:35"], ",".join(b9))
c10 = [e["performed_at"][11:16] for e in sorted(of(vc, E(10)), key=lambda e: T(e["performed_at"])) if at("22:00") <= T(e["performed_at"]) <= at("03:00")]
check("DC15", "bed 10 checks 23:00, 01:50 (documented 01:52), 03:00; ack 01:12", c10 == ["23:00", "01:50", "03:00"]
      and any(e["type"] == "staff_action" and e["t"][11:16] == "01:12" for e in of(ev, E(10))))
check("DC16", "bed 11 VV-ECMO; bed 12 DNR", "vv_ecmo" in next(p for p in ward["patients"] if p["bed"] == 11)["pathways"]
      and next(p for p in ward["patients"] if p["bed"] == 12)["code_status"] == "dnr")
a13 = of(obs, E(13, "A"))
b13 = of(obs, E(13, "B"))
check("DC17", "bed 13: encounter A ends 22:55, B starts 23:15; distinct encounter IDs on tasks", a13[-1]["t"][11:16] == "22:55" and b13[0]["t"][11:16] == "23:15"
      and {e["encounter"] for e in vc if e["bed"] == 13} == {E(13, "A"), E(13, "B")})
check("DC18", "bed 13B checks 23:40, 01:35, 03:30, 05:25; net +300", sorted(e["performed_at"][11:16] for e in of(vc, E(13, "B"))) == ["01:35", "03:30", "05:25", "23:40"]
      and net_known(E(13, "B"), at("06:55")) == 300)
check("DC19", "bed 14 weight missing and norepinephrine in mcg/kg/min", next(p for p in ward["patients"] if p["bed"] == 14)["weight_kg"] is None
      and any(i["unit"] == "mcg/kg/min" and i["drug"] == "norepinephrine" for i in of(inf, E(14))))
check("DC20", "bed 15 deferral at 20:45 until 01:30", any(e["type"] == "deferral" and e["t"][11:16] == "20:45" and e["until"][11:16] == "01:30" for e in of(ev, E(15))))
b16 = {r["t"][11:16]: r["spo2"] for r in of(obs, E(16)) if at("02:55") <= T(r["t"]) <= at("03:10")}
check("DC21", "bed 16 SpO2 96, 82, 82, 96 at 02:55/03:00/03:05/03:10 (good quality)", [b16[k] for k in ("02:55", "03:00", "03:05", "03:10")] == [96, 82, 82, 96])
uo17 = [x for x in of(fl, E(17)) if x["source"] == "urine"]
check("DC22", "bed 17 last urine output 10:00 on 20 Nov; net +4250 at 19:00 and +2500 at 06:55 (gross CRRT ignored)",
      max(T(x["event_time"]) for x in uo17) == at("10:00") and net_known(E(17), at("19:00")) == 4250 and net_known(E(17), at("06:55")) == 2500,
      f"{net_known(E(17), at('19:00'))} / {net_known(E(17), at('06:55'))}")
check("DC23", "all other beds have urine output within every 6-h night window", all(
    any(x["source"] == "urine" and t - dt.timedelta(hours=6) <= T(x["event_time"]) <= t for x in of(fl, E(b)))
    for b in (1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 14, 15, 16) for t in (at("19:00"), at("23:00"), at("03:00"), at("06:55"))))
check("DC24", "every timestamp has a +01:00 offset", all(r["t"].endswith("+01:00") for r in obs))
check("DC25", "all patients flagged fictional", all(p["fictional"] for p in ward["patients"]))
lines.append(f"\n{len(fails)} failed" if fails else "\nall data checks passed")
print(lines[-1])
(HERE / "check_results.txt").write_text(f"data checks for {D.name} (rules v3), {len(lines) - 1} checks\n" + "\n".join(lines) + "\n")
sys.exit(1 if fails else 0)
