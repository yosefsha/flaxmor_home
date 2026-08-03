---
name: security-review
description: Security review of this repo's code. Scope is diff / a specific folder / the whole project, chosen interactively or via invocation args. Runs standard security checks (secrets, injection, auth, logging, deserialization, dependencies). Use on any PR before merge.
context: fork
agent: Explore
allowed-tools: Read, Bash, Glob, Grep
---

# Security Review

## Diff to review
- Changed files: !`git diff --name-only main`
- Full diff: !`git diff main`

## Current branch
- Branch: !`git branch --show-current`
- Commits since main: !`git log main..HEAD --oneline`

## Working tree state
- Uncommitted/untracked changes: !`git status --porcelain`

## All tracked files (for whole-project / folder scope)
- Tracked files: !`git ls-files`

---

## Step 0 — Determine review scope

- **If the invocation args already specify a scope**, use it directly and skip the prompt:
  - A path/folder mentioned → **folder scope**.
  - "whole project" / "entire repo" / "full review" → **whole-project scope**.
  - "diff" / no other signal → **diff scope**.
- **Otherwise, stop and ask the user to choose one**, before reading any files:
  1. **Diff** — review the current diff against `main` (default PR-review mode).
  2. **Specific folder** — review all tracked files under a folder path they provide.
  3. **Whole project** — review every tracked file in the repo.

Once scope is resolved:
- **Diff** — review the diff shown above. If it's empty, check "Working tree state" for untracked/uncommitted files; if any exist, ask whether to review those instead or whether they meant a different branch. If the working tree is also clean, report nothing to review and stop.
- **Specific folder** — run `git ls-files -- <folder>` and review every file returned, excluding lockfiles, binaries, and generated assets (`*.lock`, `*.png`, `*.jpg`, `dist/`, `build/`, `node_modules/`, `__pycache__/`).
- **Whole project** — review every file under "All tracked files" above, with the same exclusions.

---

## Step 1 — Standard security checks (apply to every file in scope)

Check every file for:

- **Secrets / credentials** — hardcoded API keys, passwords, tokens, AWS keys, client secrets. Flag any string that looks like a secret not sourced from `os.environ`.
- **SQL injection** — queries built with f-strings or `%s %` formatting instead of parameterized queries (`$1` in asyncpg, `%s` with separate params in Django). Flag any f-string or `.format()` inside a SQL string.
- **Shell injection** — `subprocess` calls with unsanitized input, `os.system()`.
- **Sensitive data in logs** — `logger.*`, `print()`, `console.log()` emitting tokens, passwords, PII, or financial amounts.
- **Auth gaps** — missing authentication/authorization checks on endpoints, IDOR (resources fetched without ownership/scope checks), trusting client-supplied identity fields (`user_id`, `org_id`, etc.) instead of validating them server-side.
- **Debug/dev backdoors** — `DEBUG=True` committed to non-dev config, `AllowAny` on non-auth endpoints, commented-out auth checks, `verify=False` on HTTPS calls.
- **Insecure deserialization** — `pickle.loads`, `yaml.load()` without `Loader=`, `eval()` on external input.
- **Cloud/IAM least privilege** (for CDK/Terraform/CloudFormation) — wildcard resource ARNs (`"*"`), overly broad managed policies (`s3:*`, `dynamodb:*`), `removal_policy=DESTROY` on stateful resources (databases, user pools, buckets with data) instead of `RETAIN`.
- **New dependencies** — flag new entries in `requirements.txt` or `package.json` that have known CVEs or look suspicious.

---

## Step 2 — Project-specific checks

<!-- Add this project's own security rules here (e.g. tenant/org scoping conventions, auth helper functions that must be called, domain-specific data handling). Empty for now — populate as the codebase grows. -->

---

## Step 3 — Output format

For each finding output:

```
[SEVERITY] Category — file:line
Issue description.
Recommended fix.
```

Severity levels:
- **CRITICAL** — exploitable now (auth bypass, cross-tenant data leak, hardcoded secret in committed code)
- **HIGH** — exploitable with moderate effort (missing scope/ownership check, token logged, weak crypto in prod path)
- **MEDIUM** — defense-in-depth gap (missing input validation, broad IAM, missing ownership check)
- **LOW** — hygiene / best practice (print() instead of logger, overly broad exception swallowing)

End with a summary:

| Severity | Count |
|----------|-------|
| CRITICAL | n |
| HIGH     | n |
| MEDIUM   | n |
| LOW      | n |

If a category has no issues, write: `✅ <Category> — nothing to flag`
