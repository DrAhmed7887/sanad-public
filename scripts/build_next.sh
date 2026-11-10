#!/bin/zsh
# build_next.sh: unattended builder. Takes the next unchecked task from $SANAD_TASKS (default: the ward-board spec),
# has Kiro implement it headless (file read/write only; this script runs the tests), then ships it through
# scripts/ship.sh (CI + independent review + merge). Feeds test failures and review BLOCKs back to Kiro.
# Usage: scripts/build_next.sh [max_tasks]   (default 1).  Log: ~/Library/Logs/sanad-build.log
# Setup once: python3.12 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
# Exit: 0 progress or nothing left · 2 stopped and needs the conductor (branch kept) · 1 error.
set -uo pipefail
export PATH="/opt/homebrew/bin:$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
cd "$(dirname "$0")/.."
LOG="$HOME/Library/Logs/sanad-build.log"
LOCK="/tmp/sanad-build.lock"
TASKS=${SANAD_TASKS:-.kiro/specs/ward-board/tasks.md}; SPEC=${TASKS:h}
max=${1:-1}
log() { print -r -- "$(date '+%F %T') $*" | tee -a "$LOG"; }
notify() { osascript -e "display notification \"$1\" with title \"Sanad builder\"" >/dev/null 2>&1 || true; }

if ! mkdir "$LOCK" 2>/dev/null; then log "another build is running; exiting"; exit 0; fi
trap 'rmdir "$LOCK" 2>/dev/null' EXIT

kiro() {  # kiro "<prompt>" → runs Kiro headless as the sanad-builder agent (.kiro/agents: file tools only + hooks); output appended to the log
  timeout 1500 kiro-cli chat --agent sanad-builder --no-interactive --trust-tools=read,write "$1" >> "$LOG" 2>&1
}

PY=python3; [[ -x .venv/bin/python ]] && PY=.venv/bin/python   # project venv has pytest + hypothesis
tests_ok() {  # writes failures to /tmp/sanad-test-out.txt
  { $PY -I data/check_data.py && $PY -m pytest -q -x; } > /tmp/sanad-test-out.txt 2>&1
}

for (( n = 0; n < max; n++ )); do
  git switch -q main && git pull -q --ff-only || { log "cannot update main"; exit 1; }
  line=$(grep -n -m1 -E '^- \[ \] [0-9]+\.' "$TASKS" || true)
  [[ -n $line ]] || { log "all tasks in $TASKS are done"; notify "All ${SPEC:t} tasks are done"; exit 0; }
  lineno=${line%%:*}
  task=$(print -r -- "$line" | sed -E 's/^[0-9]+:- \[ \] ([0-9]+)\. (.*)$/\1|\2/')
  num=${task%%|*}; title=${task#*|}
  branch="build/${SPEC:t}-task-$num"
  log "== task $num: $title"
  git switch -q -c "$branch" 2>/dev/null || git switch -q "$branch"

  base_prompt="Implement task $num (\"$title\") from $TASKS, following .kiro/steering/*.md and $SPEC/design.md and requirements.md. Read CLAUDE.md first. Write the code under src/sanad/ and the tests listed for the task under tests/ (scenario-oracle tests against data/SCENARIOS.md and property-based tests with hypothesis). Also fill the Test and Code columns of the matching rows in docs/TRACE.md. Never modify docs/EVIDENCE.md, data/SCENARIOS.md, data/generate.py, data/ward_seed42/, docs/UI_FLOW.md or $SPEC/requirements.md. Do not mark the task done; the build script does that. Do not run git. You have no shell in this session: do not try to run commands or subagents; the build script runs the tests after you finish and sends you any failures."
  kiro "$base_prompt"
  for (( t = 1; t <= 3; t++ )); do
    tests_ok && break
    log "tests failing (attempt $t); sending the failures to Kiro"
    kiro "$base_prompt

The test run failed. Fix the code (or a wrong test that contradicts data/SCENARIOS.md: the scenarios are the oracle and must not change). Output of the failing run:
$(tail -80 /tmp/sanad-test-out.txt)"
  done
  if ! tests_ok; then log "task $num: tests still failing after 3 fixes; stopping"; notify "Task $num needs the conductor (tests)"; exit 2; fi

  sed -i '' "${lineno}s/^- \[ \]/- [x]/" "$TASKS"
  git add -A
  git commit -q -m "feat: task $num $title (built by Kiro)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" || { log "nothing to commit for task $num"; exit 1; }

  for (( r = 1; r <= 3; r++ )); do
    SHIP_TESTED_SHA=$(git rev-parse HEAD) scripts/ship.sh "feat: task $num $title" >> "$LOG" 2>&1; rc=$?  # tests_ok just ran on this exact tree
    (( rc == 0 )) && { log "task $num merged"; notify "Task $num merged: $title"; break; }
    if (( rc == 2 )); then
      pr=$(gh pr view "$branch" --json number -q .number)
      review=$(gh pr view "$pr" --json comments -q '[.comments[] | select(.body | startswith("### Independent AI review"))][-1].body')
      log "task $num: review BLOCK (round $r); sending findings to Kiro"
      kiro "$base_prompt

An independent reviewer blocked the PR. Check each [BLOCK] and [FIX] finding against the code and fix the ones that are correct. Ignore findings that would change the frozen clinical files. Review:
$review"
      if ! tests_ok; then log "task $num: tests broke while fixing review findings; stopping"; notify "Task $num needs the conductor"; exit 2; fi
      git add -A && git commit -q -m "fix: task $num review findings (round $r)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" || true
      continue
    fi
    log "task $num: ship.sh exit $rc (3 CI, 4 clinical gate or invalid review, 1 error); stopping"
    notify "Task $num needs the conductor (ship exit $rc)"; exit 2
  done
  [[ $(git rev-parse --abbrev-ref HEAD) == main ]] || { log "task $num: still blocked after 3 review rounds; stopping"; notify "Task $num needs the conductor (review)"; exit 2; }
done
log "done: $max task(s) this run"
