# CLAUDE.md: Sanad

Offline demo of sourced night-shift review rules for ventilated ICU patients, on synthetic data only. Kiroween 2026 entry (Frankenstein category). The clinical lead is the physician who signs the rules.

## Source of truth
- Rules: `docs/EVIDENCE.md` (frozen baseline v3). Changes: `docs/DECISIONS.md`. Traceability: `docs/TRACE.md`. Hashes: `docs/BASELINE.md`.
- Test oracle: `data/SCENARIOS.md` (17 beds). Data: `data/generate.py --seed 42`, checks `data/check_data.py`.
- Kiro is the builder: specs, steering and hooks live in `/.kiro` (never gitignored).

## Autonomous build loop (no approval needed between steps)
1. Pick the next task from `.kiro/specs/*/tasks.md` (or the traceability matrix's "open" items).
2. Work on a branch `build/<short-name>`. Kiro writes the code from the spec; Claude conducts and fixes.
3. Run locally: `python3 -I data/check_data.py` and the test suite. Never push a red build.
4. Push the branch and open a PR (`scripts/ship.sh`).
5. GitHub CI must pass (`.github/workflows/ci.yml`).
6. An independent AI review is posted on the PR (`scripts/review_pr.py`: Gemini 4 Argon on the Google Cloud credit, Terra on Azure as fallback; reviewer model differs from the builder). Every finding is checked against the code before acting. BLOCK findings are fixed on the same branch; then the loop repeats from step 3.
7. Squash-merge to `main` when CI is green and the review says APPROVE. Delete the branch.
   - At most 3 review rounds per PR. Override (`SHIP_OVERRIDE="reasons" SHIP_OVERRIDE_SHA=<reviewed head> scripts/ship.sh …`) is allowed only on a valid review already posted for that exact commit when **every** [BLOCK] finding was checked against the code and rejected, with the reasons posted on the PR. Invalid reviews and CI failures are never overridden.
   - `ship.sh` refuses to merge any PR that touches `docs/EVIDENCE.md` or anything under `data/` except `data/check_data.py`: that is the clinical lead's sign-off gate (exit 4).
8. Update `docs/TRACE.md` (test and code columns) in the same PR as the code it describes.

## Hard gates (stop and ask the clinical lead; never automatic)
- Any change to a clinical rule, threshold or expected outcome (needs a new version and sign-off).
- Making the repo public, publishing or posting anything **publicly** (blog, social, video), recording, or submitting. (Commits, PRs and review comments in this private repo are part of the loop, not posting.)
- Spending money, or credits beyond this project's named budget (Kiro credits; reviewer calls on cloud credits up to about $1 a day).
- Signing in, accepting terms, or entering any credential.
- Force-pushing `main`, rewriting published history, or deleting branches other than merged `build/*` ones, repos or data.

## Never in this repo
Real patient data, secrets, personal information about the team, private links. Banned public wording is listed in `docs/EVIDENCE.md`.
