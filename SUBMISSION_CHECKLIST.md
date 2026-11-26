# Sanad: Kiroween 2026 submission checklist

> **FICTIONAL DATA · SIMULATION · NOT FOR CLINICAL USE**

Category: Frankenstein. Criteria source: [`JUDGES.md`](JUDGES.md) and [`docs/JUDGING_GUIDE.md`](docs/JUDGING_GUIDE.md) (`kiroween.devpost.com/rules`, read November 7, 2026).

## Public links

- **Repository:** <https://github.com/DrAhmed7887/sanad-public>
- **Live board (GitHub Pages):** <https://drahmed7887.github.io/sanad-public/>
- **Demo video (YouTube, 2:49):** <https://youtu.be/2LObw4ZvmOE>

## Verification checklist

- **Rules baseline signed:** `docs/EVIDENCE.md` baseline v3 is frozen by hash in `docs/BASELINE.md`, confirmed signed by the clinical lead on 26 Nov 2026, and verified by `python3 -I scripts/hooks/baseline_check.py` (`12/12` frozen clinical files match `BASELINE.md` v3).
- **CI green on `main`:** [`.github/workflows/ci.yml`](.github/workflows/ci.yml) passes secret/personal-pattern checks, seed-42 reproducibility, 29 data checks, and the full pytest + Playwright suite.
- **GitHub Pages live:** [`.github/workflows/pages.yml`](.github/workflows/pages.yml) builds `index.html` and deploys <https://drahmed7887.github.io/sanad-public/> with HTTP 200 and required fictional/simulation labels.
- **Headline count reproducible:** `python3 -I scripts/alert_burden.py --check` matches `eval/results/alert-burden.json` (657 of 9,848 checks `met`; 11 messages: 9 on-call doctor, 2 night nurse; re-verified 26 Nov 2026).
- **Local Python 3.12 gates:** `python3 -I data/check_data.py` and `python3 -I scripts/alert_burden.py --check` passed cleanly on 26 Nov 2026 (full `python3 -m pytest -q` passes in CI and Python 3.12 environments).
- **Kiro credits verified:** `3,506.02` credits remaining (`>= 1,500` reserved) confirmed 26 Nov 2026; no additional `kiro-cli` run required.
- **Logged-out inspection:** The public repository homepage, live board (including Screen-1 scenario jumps and custom-bed sandbox), workflow images, and 2:49 YouTube demo all open without login or install.
- **Claims bounded:** All Devpost and README wording is grounded in [`CLAIMS.md`](CLAIMS.md) and [`README.md`](README.md#limits), with no clinical-benefit claim.
