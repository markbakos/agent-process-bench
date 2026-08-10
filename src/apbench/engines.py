from __future__ import annotations

import hashlib
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from .artifacts import atomic_write_json
from .models import EngineRunResult, ModelProfile, UsageSummary


class AgentEngine(Protocol):
    def run(
        self,
        workspace: Path,
        prompt: str,
        model: ModelProfile,
        output_dir: Path,
    ) -> EngineRunResult: ...


class EngineInfrastructureError(RuntimeError):
    pass


@dataclass(frozen=True)
class FakeScenario:
    writes: dict[str, str] = field(default_factory=dict)
    deletes: tuple[str, ...] = ()
    outcome: str = "success"


class FakeEngine:
    """Deterministic lifecycle test engine; it intentionally does not mimic Codex."""

    def __init__(self, scenarios: dict[str, FakeScenario] | None = None) -> None:
        self.scenarios = scenarios or {}
        self.calls = 0

    def run(
        self,
        workspace: Path,
        prompt: str,
        model: ModelProfile,
        output_dir: Path,
    ) -> EngineRunResult:
        started = time.monotonic()
        self.calls += 1
        marker = f"fake-{self.calls:06d}-{hashlib.sha256(prompt.encode()).hexdigest()[:12]}"
        scenario = self.scenarios.get(prompt, FakeScenario())
        prompt_hash = hashlib.sha256(prompt.encode()).hexdigest()
        try:
            commit_count = int(
                subprocess.check_output(
                    ["git", "rev-list", "--count", "HEAD"], cwd=workspace, text=True
                ).strip()
            )
        except (OSError, subprocess.SubprocessError, ValueError) as exc:
            raise EngineInfrastructureError(f"FakeEngine did not receive a valid Git workspace: {exc}") from exc

        output_dir.mkdir(parents=True, exist_ok=True)
        atomic_write_json(
            output_dir / "fake-request.json",
            {
                "invocation_marker": marker,
                "model_profile": model.id,
                "prompt_sha256": prompt_hash,
                "baseline_git_commit_count": commit_count,
            },
        )

        if scenario.outcome == "infrastructure_error":
            raise EngineInfrastructureError("Simulated FakeEngine infrastructure failure")

        for relative in scenario.deletes:
            target = self._target(workspace, relative)
            if target.is_dir():
                raise EngineInfrastructureError(f"FakeEngine refuses directory deletion: {relative}")
            target.unlink(missing_ok=True)
        for relative, content in scenario.writes.items():
            target = self._target(workspace, relative)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")

        if scenario.outcome == "forbidden_file":
            (workspace / "AGENTS.md").write_text("fake protocol violation\n", encoding="utf-8")

        if scenario.outcome not in {"timeout", "crash"}:
            with (workspace / "fake_output.txt").open("a", encoding="utf-8") as handle:
                handle.write(prompt_hash + "\n")

        result = EngineRunResult(
            exit_code=1 if scenario.outcome == "crash" else (None if scenario.outcome == "timeout" else 0),
            timed_out=scenario.outcome == "timeout",
            termination_reason=(
                "timeout" if scenario.outcome == "timeout" else "engine_error" if scenario.outcome == "crash" else "completed"
            ),
            wall_time_seconds=time.monotonic() - started,
            usage=UsageSummary(
                input_tokens=len(prompt.split()),
                output_tokens=1,
                model_calls=1,
                file_change_event_count=len(scenario.writes) + len(scenario.deletes) + 1,
            ),
            final_status=scenario.outcome,
        )
        atomic_write_json(
            output_dir / "fake-result.json",
            {"invocation_marker": marker, **result.model_dump()},
        )
        return result

    @staticmethod
    def _target(workspace: Path, relative: str) -> Path:
        target = (workspace / relative).resolve()
        try:
            target.relative_to(workspace.resolve())
        except ValueError as exc:
            raise EngineInfrastructureError(f"FakeEngine action escapes workspace: {relative}") from exc
        return target


def engine_for(profile: ModelProfile) -> AgentEngine:
    if profile.engine == "fake":
        return FakeEngine()
    raise ValueError(f"Unsupported engine '{profile.engine}' in Part 1")
