#!/bin/zsh
# ship.sh: the autonomous loop's publish step for the current build/* branch.
#   local checks → base check → clinical gate → push → PR to main → CI on the pinned head
#   → independent review (reviewer run from origin/main) → squash-merge with --match-head-commit.
# Usage: scripts/ship.sh "PR title" [body-file]
# Exit: 0 merged · 2 review BLOCK (fix, or override after checking every finding) · 3 CI failed
#       4 needs the clinical lead (clinical files changed) or the review was invalid/refused · 1 other error.
# Never force-pushes, never touches main directly, never merges a red build.
set -euo pipefail
cd "$(dirname "$0")/.."
title=${1:?usage: scripts/ship.sh "PR title" [body-file]}
branch=$(git rev-parse --abbrev-ref HEAD)
[[ $branch == build/* ]] || { print -u2 "ship: run from a build/* branch (now on $branch)"; exit 1; }
[[ -z $(git status --porcelain) ]] || { print -u2 "ship: commit your changes first"; exit 1; }

PY=python3; [[ -x .venv/bin/python ]] && PY=.venv/bin/python
if [[ ${SHIP_TESTED_SHA:-} == $(git rev-parse HEAD) ]]; then
  print "== local checks: already run on ${SHIP_TESTED_SHA:0:10} by the caller (CI still runs everything)"
else
  print "== local checks"
  $PY -I data/check_data.py >/dev/null
  $PY -m pytest -q >/dev/null
fi

git fetch -q origin main
base=$(git rev-parse origin/main)
head=$(git rev-parse HEAD)
git merge-base --is-ancestor "$base" "$head" || { print -u2 "ship: main has moved; rebase on origin/main and rerun"; exit 1; }

# Hard gate: clinical rules, expected outcomes and data are the clinical lead's to sign (CLAUDE.md).
clinical=$(git diff --name-only "$base...$head" -- docs/EVIDENCE.md data ":(exclude)data/check_data.py")
if [[ -n $clinical ]]; then
  print -u2 "ship: clinical files changed; needs the clinical lead's sign-off before merge:"; print -u2 "$clinical"; exit 4
fi

print "== push $branch"
git push -q -u origin "$branch"

pr=$(gh pr view "$branch" --json number -q .number 2>/dev/null || true)
if [[ -z $pr ]]; then
  if [[ -n ${2:-} ]]; then gh pr create -B main -H "$branch" -t "$title" -F "$2" >/dev/null
  else gh pr create -B main -H "$branch" -t "$title" -b "Autonomous build loop (see CLAUDE.md)." >/dev/null; fi
  pr=$(gh pr view "$branch" --json number -q .number)
fi
[[ $(gh pr view "$pr" --json baseRefName -q .baseRefName) == main ]] || { print -u2 "ship: PR #$pr does not target main"; exit 1; }
print "== PR #$pr"
merge_email=$(git config user.email)  # squash merges otherwise take the account's primary (personal) email (D25)
[[ $merge_email == *@users.noreply.github.com ]] || { print -u2 "ship: git user.email must be the GitHub noreply address (D25), got '$merge_email'"; exit 1; }

print "== waiting for CI on ${head:0:10}"
sleep 8
# GitHub can take a while to register the run; `gh pr checks` errors with "no checks reported" until then,
# which used to be read as a CI failure (8 Nov: task 1 stopped with CI green). Wait up to 3 min for checks to appear.
for (( w = 0; w < 18; w++ )); do
  gh pr checks "$pr" 2>&1 | grep -q 'no checks reported' || break
  sleep 10
done
if ! gh pr checks "$pr" --watch --fail-fast >/dev/null 2>&1; then
  gh pr checks "$pr" || true
  print -u2 "ship: CI failed on PR #$pr"; exit 3
fi
ci=$(gh run list --commit "$head" --workflow ci --json conclusion -q '.[0].conclusion' 2>/dev/null || true)
[[ $ci == success ]] || { print -u2 "ship: workflow 'ci' has not succeeded on ${head:0:10} (got '${ci:-none}')"; exit 3; }

if [[ -n ${SHIP_OVERRIDE:-} ]]; then
  # An override applies only to a review the conductor has read: the same head SHA, already posted on the PR.
  [[ ${SHIP_OVERRIDE_SHA:-} == "$head" ]] || { print -u2 "ship: SHIP_OVERRIDE needs SHIP_OVERRIDE_SHA=$head (the reviewed commit)"; exit 1; }
  # The latest review comment must be for this head AND base (header line) and end in a BLOCK footer (last line).
  last=$(gh pr view "$pr" --json comments -q '[.comments[] | select(.body | startswith("### Independent AI review"))][-1].body')
  header=${last%%$'\n'*}
  footer=$(print -r -- "$last" | sed '/^[[:space:]]*$/d' | tail -1)
  [[ $header == *"of \`${head:0:10}\` against \`${base:0:10}\`"* && $footer == "_Parsed verdict: **BLOCK**"* ]] \
    || { print -u2 "ship: the latest review is not a valid BLOCK for ${head:0:10} on base ${base:0:10}; run without override first"; exit 1; }
  [[ $footer != *"for commit"* || $footer == *"for commit \`$head\`"* ]] || { print -u2 "ship: review footer names another commit"; exit 1; }
  gh pr comment "$pr" --body "**Review override by the conductor** for \`${head:0:10}\`: ${SHIP_OVERRIDE}" >/dev/null
  print "== review BLOCK overridden for ${head:0:10} (reasons posted)"
  git fetch -q origin main
  [[ $(git rev-parse origin/main) == "$base" ]] || { print -u2 "ship: main moved; rebase and rerun"; exit 1; }
  gh pr merge "$pr" --squash --delete-branch --match-head-commit "$head" --author-email "$merge_email" >/dev/null
  git switch -q main && git pull -q --ff-only
  print "merged PR #$pr into main (override)"; exit 0
fi

print "== independent review (reviewer from origin/main)"
reviewer="$(mktemp -d)/review_pr.py"
if git cat-file -e origin/main:scripts/review_pr.py 2>/dev/null; then
  git show origin/main:scripts/review_pr.py > "$reviewer"
else
  cp scripts/review_pr.py "$reviewer"  # bootstrap only: the PR that first adds the reviewer to main
  print "   (bootstrap: main has no reviewer yet, using the branch copy)"
fi
set +e
out=$(python3 "$reviewer" "$pr" "$head" "$base"); rc=$?
set -e
rm -rf "$(dirname "$reviewer")"
print -r -- "$out"
reviewed=$(print -r -- "$out" | sed -n 's/^REVIEWED_SHA: //p')
if (( rc == 2 )); then
  # To override: read this review, check every [BLOCK] finding against the code, then rerun with
  # SHIP_OVERRIDE="reasons" SHIP_OVERRIDE_SHA=<this head>. Invalid reviews (exit 4) and CI failures never.
  print -u2 "ship: review BLOCK on PR #$pr for ${head:0:10} (read it, fix, or override that exact SHA)"; exit 2
elif (( rc == 4 )); then print -u2 "ship: review invalid or refused; not overridable"; exit 4
elif (( rc != 0 )); then print -u2 "ship: review failed to run"; exit 1; fi

[[ $reviewed == "$head" ]] || { print -u2 "ship: reviewed ${reviewed:0:10} but head is ${head:0:10}; rerun"; exit 1; }
git fetch -q origin main
[[ $(git rev-parse origin/main) == "$base" ]] || { print -u2 "ship: main moved during review; rebase and rerun"; exit 1; }
[[ $(gh pr view "$pr" --json baseRefName -q .baseRefName) == main ]] || { print -u2 "ship: PR #$pr does not target main"; exit 1; }
print "== merge ${head:0:10}"
gh pr merge "$pr" --squash --delete-branch --match-head-commit "$head" --author-email "$merge_email" >/dev/null
git switch -q main && git pull -q --ff-only
print "merged PR #$pr into main"
