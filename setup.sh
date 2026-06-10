#!/usr/bin/env bash
# Agency OS — one-time setup: guardrails -> main, branch protection, Gemini CLI.
# Prereqs: git, gh (logged in: `gh auth login`), node >= 20.
# Run from a folder containing: AGENTS.md GEMINI.md ci.yml
#                               pull_request_template.md copilot-instructions.md
set -euo pipefail
REPO="tanmatra6-wq/Agency-OS"
HERE="$(cd "$(dirname "$0")" && pwd)"

for c in git gh node; do command -v $c >/dev/null || { echo "missing: $c"; exit 1; }; done
gh auth status >/dev/null || { echo "run: gh auth login"; exit 1; }

# 1) repo checkout (fresh or existing)
if [ ! -d Agency-OS ]; then gh repo clone "$REPO"; fi
cd Agency-OS && git checkout main && git pull --ff-only

# 2) guardrails straight to main (protection not on yet — last unguarded push)
mkdir -p .github/workflows
cp "$HERE/AGENTS.md" ./AGENTS.md
cp "$HERE/GEMINI.md" ./GEMINI.md
cp "$HERE/ci.yml" .github/workflows/ci.yml
cp "$HERE/pull_request_template.md" .github/pull_request_template.md
cp "$HERE/copilot-instructions.md" .github/copilot-instructions.md
git add -A
git commit -m "Guardrails: AGENTS.md (binding agent rules), CI invariant checks, PR template" \
  || echo "guardrails already committed"
git push origin main

# 3) protect main: PRs must pass the 'tests' check; no force pushes/deletes
if ! gh api -X PUT "repos/$REPO/branches/main/protection" --input - <<'JSON'
{
  "required_status_checks": { "strict": true, "contexts": ["tests"] },
  "enforce_admins": true,
  "required_pull_request_reviews": null,
  "restrictions": null,
  "allow_force_pushes": false,
  "allow_deletions": false
}
JSON
then
  echo "!! BRANCH PROTECTION UNAVAILABLE: private repos on the GitHub Free plan"
  echo "!! cannot enforce protection. Upgrade to GitHub Pro (~\$4/mo) or every"
  echo "!! agent and human can push straight to main. CI alone cannot block merges."
fi
echo "branch protection attempt finished (verify in Settings -> Branches)"

# 4) Gemini CLI (free tier with a personal Google login on first run)
command -v gemini >/dev/null || npm install -g @google/gemini-cli
echo
echo "DONE. Build order:  ./run-issue.sh 2   then 6, 5, 7, 3, 4 (4 waits on Meta templates)."
