from __future__ import annotations

import os
from pathlib import Path

import pytest

from apbench.artifacts import initialize_git
from apbench.codex import CodexEngine
from apbench.models import ModelProfile


@pytest.mark.codex
@pytest.mark.skipif(
    os.environ.get("APBENCH_RUN_CODEX_SMOKE") != "1",
    reason="set APBENCH_RUN_CODEX_SMOKE=1 to consume one Codex run",
)
def test_real_codex_can_modify_one_fresh_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    initialize_git(workspace)
    profile = ModelProfile(
        id="codex-smoke",
        engine="codex",
        model=os.environ.get("APBENCH_CODEX_MODEL", "gpt-5.6-terra"),
        reasoning_effort="medium",
        timeout_seconds=300,
    )

    result = CodexEngine().run(
        workspace,
        "Create codex-smoke.txt containing exactly ok followed by a newline. Do nothing else.",
        profile,
        tmp_path / "engine",
    )

    assert result.termination_reason == "completed"
    assert result.usage.model_calls == 1
    assert result.usage.file_change_event_count == 1
    assert (workspace / "codex-smoke.txt").read_text(encoding="utf-8") == "ok\n"
    assert (tmp_path / "engine" / "codex-events.jsonl").is_file()
    assert (tmp_path / "engine" / "codex-stderr.log").is_file()
