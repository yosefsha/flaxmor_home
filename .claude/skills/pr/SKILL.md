---
description: Run security review, then create a PR if no critical/high issues found.
argument-hint: optional PR title
user-invocable: true
---

You are creating a pull request with a mandatory security gate.

## Step 1 — Security review

Invoke the `security-review` skill now using the Skill tool.
Read its full output carefully.

## Step 2 — Gate check

Scan the security-review output for any findings at severity **CRITICAL** or **HIGH**.

- If ANY CRITICAL or HIGH findings exist:
  - Print a clear summary of the blocking findings
  - Tell the user: "PR creation blocked. Fix the issues above and re-run /pr."
  - **Stop here. Do not create a PR.**

- If only MEDIUM / LOW / no findings:
  - Collect any MEDIUM/LOW findings to include in the PR body
  - Continue to Step 3

## Step 3 — Create the PR

Gather context:
- Branch name: `!git branch --show-current`
- Recent commits: `!git log main..HEAD --oneline`

Use `gh pr create` with:
- Title: infer from branch name and recent commits (or use the argument if provided)
- Base branch: main
- Body via HEREDOC:

```
## Summary
<bullet points derived from commits>

## Test plan
<bulleted checklist of what to test>

## Security review
<"No issues found." OR bulleted list of MEDIUM/LOW findings from Step 1>

🤖 Generated with [Claude Code](https://claude.com/claude-code)
```

Return the PR URL to the user.
