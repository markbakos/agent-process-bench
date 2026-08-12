from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import time

import pytest

from apbench.codex import (
    CodexEngine,
    build_codex_args,
    filtered_environment,
    parse_codex_jsonl,
    validate_codex_profile,
)
from apbench.engines import EngineInfrastructureError
from apbench.models import ModelProfile


def _profile() -> ModelProfile:
    return ModelProfile(
        id="terra-medium",
        engine="codex",
        model="gpt-5.6-terra",
        reasoning_effort="medium",
        timeout_seconds=1800,
    )


def test_codex_args_are_isolated_and_read_prompt_from_stdin(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace with spaces;$(ignored)"
    args = build_codex_args(workspace, _profile(), "/opt/codex")

    assert isinstance(args, list)
    assert args[:2] == ["/opt/codex", "exec"]
    assert args[-1] == "-"
    assert "resume" not in args
    assert args[args.index("--model") + 1] == "gpt-5.6-terra"
    assert args[args.index("--sandbox") + 1] == "workspace-write"
    assert args[args.index("-C") + 1] == str(workspace.resolve())
    for flag in ("--json", "--ephemeral", "--ignore-user-config", "--ignore-rules", "--strict-config"):
        assert args.count(flag) == 1

    overrides = [args[index + 1] for index, value in enumerate(args) if value == "-c"]
    assert not any(value.startswith("projects.") for value in overrides)
    for control in (
        'model_reasoning_effort="medium"',
        'approval_policy="never"',
        'web_search="disabled"',
        "agents.enabled=false",
        "apps._default.enabled=false",
        "features.plugins=false",
        "memories.use_memories=false",
        "memories.generate_memories=false",
        "sandbox_workspace_write.network_access=false",
        "project_doc_max_bytes=0",
        "project_doc_fallback_filenames=[]",
    ):
        assert overrides.count(control) == 1


def test_filtered_environment_removes_secret_names_without_reading_global_state() -> None:
    environment, removed = filtered_environment(
        {
            "PATH": "/usr/bin",
            "LANG": "C.UTF-8",
            "OPENAI_API_KEY": "openai-secret",
            "codex_api_key": "codex-secret",
            "GITHUB_TOKEN": "github-secret",
            "service_secret": "service-secret",
            "DATABASE_URL": "postgres://secret",
        }
    )

    assert environment == {"PATH": "/usr/bin", "LANG": "C.UTF-8"}
    assert removed == [
        "DATABASE_URL",
        "GITHUB_TOKEN",
        "OPENAI_API_KEY",
        "codex_api_key",
        "service_secret",
    ]
    assert filtered_environment({}) == ({}, [])


def test_jsonl_parser_is_tolerant_and_deduplicates_cumulative_events(tmp_path: Path) -> None:
    events = tmp_path / "events.jsonl"
    events.write_bytes(
        b'\nnot-json\n'
        b'{"type":"unknown"}\n'
        b'{"type":"turn.started"}\n'
        b'{"type":"item.started","item":{"id":"cmd-1","type":"command_execution"}}\n'
        b'{"type":"item.completed","item":{"id":"cmd-1","type":"command_execution"}}\n'
        b'{"type":"item.completed","item":{"id":"change-1","type":"file_change"}}\n'
        b'{"type":"turn.completed","usage":{"input_tokens":10,"cached_input_tokens":3,'
        b'"output_tokens":4,"reasoning_output_tokens":2}}\n'
    )

    telemetry = parse_codex_jsonl(events)

    assert telemetry.final_status == "completed"
    assert telemetry.usage.model_dump() == {
        "input_tokens": 10,
        "cached_input_tokens": 3,
        "output_tokens": 4,
        "reasoning_output_tokens": 2,
        "model_calls": 1,
        "command_count": 1,
        "file_change_event_count": 1,
    }
    assert len(telemetry.warnings) == 2


def _fake_codex(tmp_path: Path) -> Path:
    executable = tmp_path / "fake-codex"
    executable.write_text(
        f"""#!{sys.executable}
import json
import os
from pathlib import Path
import signal
import sys
import time

if "--version" in sys.argv[1:]:
    print("codex-test 1.0")
    raise SystemExit
if sys.argv[1:] == ["exec", "--help"]:
    print("--json --ephemeral --ignore-user-config --ignore-rules --strict-config")
    raise SystemExit

prompt = sys.stdin.read()
mode = prompt
Path("received-prompt.txt").write_text(prompt, encoding="utf-8")
sys.stderr.write("stderr evidence\\n")
if mode == "timeout":
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    time.sleep(10)
elif mode == "infrastructure":
    print(json.dumps({{"type": "error", "message": "authentication failed"}}), flush=True)
    raise SystemExit(1)
else:
    print(json.dumps({{"type": "thread.started", "thread_id": "thread-1"}}))
    print(json.dumps({{"type": "turn.started"}}))
    print(json.dumps({{"type": "item.started", "item": {{"id": "cmd-1", "type": "command_execution"}}}}))
    print(json.dumps({{"type": "item.completed", "item": {{"id": "cmd-1", "type": "command_execution"}}}}))
    print(json.dumps({{"type": "item.completed", "item": {{"id": "change-1", "type": "file_change"}}}}))
    terminal = "turn.failed" if mode == "failed" else "turn.completed"
    print(json.dumps({{"type": terminal, "error": {{"message": "task failed"}}, "usage": {{"input_tokens": 8, "output_tokens": 3}}}}), flush=True)
    raise SystemExit(1 if mode == "failed" else 0)
""",
        encoding="utf-8",
    )
    executable.chmod(0o755)
    return executable


def test_codex_profile_preflight_checks_cli_and_safety_controls(tmp_path: Path) -> None:
    executable = str(_fake_codex(tmp_path))
    assert validate_codex_profile(_profile(), executable) == "codex-test 1.0"
    with pytest.raises(ValueError, match="workspace-write"):
        validate_codex_profile(_profile().model_copy(update={"sandbox": "danger-full-access"}), executable)
    with pytest.raises(ValueError, match="network access"):
        validate_codex_profile(_profile().model_copy(update={"network_access": True}), executable)


def test_codex_engine_preserves_raw_output_and_normalizes_results(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    engine = CodexEngine(str(_fake_codex(tmp_path)))

    result = engine.run(workspace, "make the change", _profile(), tmp_path / "engine")

    assert result.termination_reason == "completed"
    assert result.usage.command_count == 1
    assert result.usage.file_change_event_count == 1
    assert (workspace / "received-prompt.txt").read_text() == "make the change"
    assert (tmp_path / "engine" / "codex-stderr.log").read_text() == "stderr evidence\n"
    assert json.loads((tmp_path / "engine" / "codex-command.json").read_text())["args"][-1] == "-"

    failed = engine.run(workspace, "failed", _profile(), tmp_path / "failed")
    assert failed.termination_reason == "engine_error"
    assert failed.final_status == "failed"

    with pytest.raises(EngineInfrastructureError, match="authentication failed"):
        engine.run(workspace, "infrastructure", _profile(), tmp_path / "infrastructure")
    assert (tmp_path / "infrastructure" / "codex-events.jsonl").is_file()


@pytest.mark.skipif(os.name != "posix", reason="process-group timeout behavior is POSIX-specific")
def test_codex_engine_terminates_then_kills_on_timeout(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    engine = CodexEngine(str(_fake_codex(tmp_path)), termination_grace_seconds=0.05)
    profile = _profile().model_copy(update={"timeout_seconds": 1})

    started = time.monotonic()
    result = engine.run(workspace, "timeout", profile, tmp_path / "engine")

    assert result.timed_out
    assert result.termination_reason == "timeout"
    assert time.monotonic() - started < 3
    assert (tmp_path / "engine" / "codex-stderr.log").read_text() == "stderr evidence\n"
