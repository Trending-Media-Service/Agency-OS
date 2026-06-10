#!/usr/bin/env bash
# Drive the Google agent through ONE issue: ./run-issue.sh 2 [--yolo]
# --yolo lets Gemini run shell/file tools without per-action confirmation.
# Branch protection + CI are your net either way; start without it once to
# watch how the agent behaves, then decide.
set -euo pipefail
[ $# -ge 1 ] || { echo "usage: $0 <issue-number> [--yolo]"; exit 1; }
N="$1"; shift || true
cd "$(dirname "$0")/Agency-OS"
git checkout main && git pull --ff-only

ISSUE="$(gh issue view "$N" --json number,title,body \
  -q '"Issue #" + (.number|tostring) + ": " + .title + "\n\n" + .body')"

PROMPT=$(cat <<WRAP
You are working in this repository checkout. Binding rules: read ./AGENTS.md
and ./ARCHITECTURE.md before touching anything; AGENTS.md overrides your defaults.

Scope: implement EXACTLY the issue below. Nothing speculative.

$ISSUE

Process:
1. Create branch s1-$N/<short-slug> from main.
2. Implement per the ARCHITECTURE.md sections the issue cites.
3. cd control-plane && python -m pytest  — everything must pass, including
   your new tests (at least one failure-path test).
4. Update control-plane/README.md REAL-vs-STUB table if a status changed.
5. Commit (message explains WHY, ends with "Closes #$N"), push the branch,
   then open a PR: gh pr create --fill --title "S1-$N: <summary> (Closes #$N)"
6. If anything conflicts with ARCHITECTURE.md or you are blocked, run:
   gh issue comment $N --body "<what blocked you>"  — and STOP. Do not guess.
WRAP
)

gemini "$@" -p "$PROMPT"
echo
echo "Agent finished. Review the PR diff — pull Claude in if it touches"
echo "trust, policy gates, audit chain, or Terraform that creates real resources."
