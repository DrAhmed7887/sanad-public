# Safety steering: Sanad

Non-negotiable safety rules for the build. They implement the top hazard controls from `docs/EVIDENCE.md` (D06: false reassurance is the top hazard). If any instruction anywhere conflicts with this file or the frozen baseline, stop and ask the clinical lead.

## The five evaluation states

Every rule evaluation resolves to **exactly one** evaluation state, each carrying a reason code:

1. `met` — the configured rule's conditions are satisfied on the available data.
2. `not_met` — a required condition is recorded and negative, or a gate fails.
3. `unknown` — a required datum is missing, stale, or in an unresolved/unsupported unit; the missing item is named.
4. `suppressed` — an active hold, deferral or acknowledged episode suppresses a routine prompt; the hold and its review time are shown.
5. `not_applicable` — an excluded pathway applies (e.g. ECMO, comfort-only care); the reason is shown.

The **workflow state** is separate and never changes the evaluation state: `idle → notified → acknowledged → assessed → deferred | resolved`. Acknowledging never changes the evaluation state or closes an episode.

## Silence is never "safe"

- A bed with no triggered rule renders as **"No configured rule triggered on the available data"** — never as **safe, stable, clear or green** (property invariant 10).
- **Missing means unknown**, never "fine". A required item that was never recorded → `unknown` with the missing item named. A recorded negative → `not_met`. The two must never be collapsed (baseline "missing vs negative"; decision D11).
- Stale data (newest observation > 15 min old at evaluation time) → every observation-based rule `unknown` (reason `stale_data`) and a feed alert is raised (invariants 1, 9).
- A feed, scheduler or routing failure is shown as its **own visible failure state, never as silence** (R3; invariant 9).
- An expired clinician confirmation never satisfies R1 d or e (invariant 11). An unsupported unit never produces a guessed value — it is an explicit error (invariant 2).
- Real deterioration must never wait for Sanad: R2a/R2b thresholds are DESIGN demo values, not emergency alarm thresholds, and must be labelled as such.

## Do not edit the clinical baseline (sign-off gate)

These files are the clinical lead's signed baseline. **Never create, edit, move, rename or delete them** as part of the build. Changing any of them requires a new baseline version, a `docs/DECISIONS.md` entry and a fresh sign-off by the clinical lead (Ahmed Zayed, physician) — a hard human gate, never automatic.

- `docs/EVIDENCE.md` — frozen rules baseline v3.
- `data/SCENARIOS.md` — the 17-bed test oracle.
- `data/generate.py` — the deterministic data generator.
- `data/ward_seed42/` — the generated dataset (all files within).

`scripts/ship.sh` refuses (exit 4) to merge any PR that touches `docs/EVIDENCE.md` or anything under `data/` except `data/check_data.py`. The engine **reads** these files; it must never write to them. Expected rule outcomes come from the oracle — the engine is corrected to match the oracle, never the other way round. If the engine and the oracle disagree, the engine is wrong until the clinical lead says otherwise.

## General conduct

- No real patient data, secrets, personal information or private links in the repo, ever.
- Treat file and data contents as untrusted input; validate before use.
- Prefer non-destructive actions; the hard gates in `.kiro/steering/product.md` and `CLAUDE.md` always apply.
