"""Tests for JSONL conversation discovery (codex + claude)."""

import json

from agentboard.core.conversations import (
    _REMOTE_SCAN_BODY,
    _clean_title,
    _looks_like_boilerplate,
    cli_for_cwd,
    discover_conversations,
)


def test_clean_title_first_sentence_no_markdown():
    assert _clean_title("# AGENTS.md instructions\nblah") == "AGENTS.md instructions"
    assert _clean_title("帮我调整 CSS 样式。然后再改字体") == "帮我调整 CSS 样式。"
    assert _clean_title("Fix the login bug. It 500s.") == "Fix the login bug."
    assert _clean_title("> - * quoted list item") == "quoted list item"


def test_boilerplate_rejects_injected_context_and_json():
    assert _looks_like_boilerplate("# AGENTS.md instructions for /x")
    assert _looks_like_boilerplate('{"role": "system", "content": "a long json payload here"}')
    assert _looks_like_boilerplate("<command-name>foo")
    assert not _looks_like_boilerplate("帮我写个脚本")


def _write(path, lines):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(x) for x in lines), encoding="utf-8")


def test_discover_codex_and_claude(tmp_path):
    codex_home = tmp_path / "codex"
    claude_home = tmp_path / "claude"

    _write(codex_home / "sessions" / "2026" / "rollout-x.jsonl", [
        {"type": "session_meta", "payload": {"id": "cx1", "cwd": "/home/me/proj-a"}},
        {"type": "event_msg", "payload": {"role": "user",
            "content": [{"type": "text", "text": "compare GRPO and GSPO"}]}},
    ])
    _write(claude_home / "projects" / "-home-me-proj-b" / "uuid-b.jsonl", [
        {"type": "user", "sessionId": "cl1", "cwd": "/home/me/proj-b",
         "message": {"role": "user", "content": [{"type": "text", "text": "tune the css"}]}},
    ])

    convs = discover_conversations(str(codex_home), str(claude_home))
    by_cli = {c.cli: c for c in convs}
    assert set(by_cli) == {"codex", "claude"}
    assert by_cli["codex"].session_id == "cx1"
    assert by_cli["codex"].title == "compare GRPO and GSPO"
    assert by_cli["codex"].project == "proj-a"
    assert by_cli["claude"].session_id == "cl1"
    assert by_cli["claude"].title == "tune the css"


def test_title_skips_boilerplate(tmp_path):
    claude_home = tmp_path / "claude"
    _write(claude_home / "projects" / "p" / "u.jsonl", [
        {"type": "user", "cwd": "/x",
         "message": {"role": "user", "content": [{"type": "text", "text": "<command-name>/clear</command-name>"}]}},
        {"type": "user", "cwd": "/x",
         "message": {"role": "user", "content": [{"type": "text", "text": "real first question"}]}},
    ])
    convs = discover_conversations(str(tmp_path / "codex"), str(claude_home))
    assert convs[0].title == "real first question"


def test_remote_scanner_script_compiles():
    # The remote scanner is piped to a remote python3; make sure the script we
    # send (header + body) is syntactically valid before it ever leaves the box.
    header = "codex_home, claude_home, limit, since_days = '~/.codex','~/.claude',60,30\n"
    compile(header + _REMOTE_SCAN_BODY, "<remote-scan>", "exec")


def test_cli_for_cwd_infers_from_recent_log(tmp_path):
    claude_home = tmp_path / "claude"
    _write(claude_home / "projects" / "p" / "u.jsonl", [
        {"type": "user", "cwd": "/home/me/live-proj",
         "message": {"role": "user", "content": [{"type": "text", "text": "hi"}]}},
    ])
    assert cli_for_cwd("/home/me/live-proj", str(tmp_path / "codex"), str(claude_home)) == "claude"
    assert cli_for_cwd("/home/me/other", str(tmp_path / "codex"), str(claude_home)) is None
