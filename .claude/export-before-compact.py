#!/usr/bin/env python3
"""PreCompact hook: renders the session's JSONL transcript as a plain-text
conversation export (like /export) and appends it to compact-transcript-export.log
before Claude Code compacts context."""
import json
import os
import re
import sys
from datetime import datetime, timezone

LOG_FILE = os.path.join(os.path.dirname(__file__), "..", "compact-transcript-export.log")

SKIP_TYPES = {
    "mode",
    "permission-mode",
    "file-history-snapshot",
    "system",
    "ai-title",
    "last-prompt",
    "attachment",
}


def resolve_transcript_path(payload: dict) -> str:
    path = payload.get("transcript_path") or ""
    if path and os.path.exists(path):
        return path

    session_id = payload.get("session_id") or ""
    cwd = payload.get("cwd") or ""
    if not session_id or not cwd:
        return path

    project_dir = re.sub(r"[^A-Za-z0-9]", "-", cwd)
    fallback = os.path.join(
        os.path.expanduser("~"), ".claude", "projects", project_dir, f"{session_id}.jsonl"
    )
    return fallback if os.path.exists(fallback) else path


def truncate(text: str, limit: int = 500) -> str:
    text = text if isinstance(text, str) else json.dumps(text)
    return text if len(text) <= limit else text[:limit] + "... [truncated]"


def render_content_block(block) -> str:
    if not isinstance(block, dict):
        return truncate(str(block))

    block_type = block.get("type")
    if block_type == "text":
        return block.get("text", "")
    if block_type == "thinking":
        thinking_text = block.get("thinking", "")
        return f"[thinking] {thinking_text}" if thinking_text else ""
    if block_type == "tool_use":
        return f"[tool_call] {block.get('name')}({json.dumps(block.get('input', {}), separators=(',', ':'))})"
    if block_type == "tool_result":
        return f"[tool_result for {block.get('tool_use_id')}] {truncate(block.get('content'))}"
    return truncate(block)


def is_skippable_user_text(text: str) -> bool:
    return text.startswith("<local-command-caveat>") or text.startswith("<command-name>")


def render_entry(entry: dict) -> str:
    entry_type = entry.get("type")
    if entry_type not in ("user", "assistant"):
        return ""
    if entry.get("isMeta"):
        return ""

    message = entry.get("message") or {}
    content = message.get("content")
    timestamp = entry.get("timestamp", "")
    role_label = "User" if entry_type == "user" else "Assistant"

    if isinstance(content, str):
        if entry_type == "user" and is_skippable_user_text(content):
            return ""
        return f"### {role_label} [{timestamp}]\n{content}\n"

    if isinstance(content, list):
        rendered_blocks = [render_content_block(b) for b in content]
        rendered_blocks = [b for b in rendered_blocks if b]
        if not rendered_blocks:
            return ""
        return f"### {role_label} [{timestamp}]\n" + "\n".join(rendered_blocks) + "\n"

    return ""


def render_transcript(transcript_path: str) -> str:
    if not transcript_path or not os.path.exists(transcript_path):
        return f"[no transcript found at '{transcript_path}']\n"

    sections = []
    with open(transcript_path, "r") as fp:
        for line in fp:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except Exception:
                continue
            if entry.get("type") in SKIP_TYPES:
                continue
            rendered = render_entry(entry)
            if rendered:
                sections.append(rendered)

    return "\n".join(sections) if sections else "[transcript had no renderable turns]\n"


def main():
    raw = sys.stdin.read()
    try:
        payload = json.loads(raw)
    except Exception as exc:
        print(f"export-before-compact: failed to parse hook input: {exc}", file=sys.stderr)
        sys.exit(0)

    session_id = payload.get("session_id", "unknown")
    trigger = payload.get("trigger", "unknown")
    transcript_path = resolve_transcript_path(payload)
    now = datetime.now(timezone.utc).isoformat()

    header = f"\n===== PreCompact export | session={session_id} | trigger={trigger} | {now} =====\n"
    body = render_transcript(transcript_path)

    with open(LOG_FILE, "a") as fp:
        fp.write(header)
        fp.write(body)
        fp.write("\n")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"export-before-compact: unexpected error: {exc}", file=sys.stderr)
    sys.exit(0)
