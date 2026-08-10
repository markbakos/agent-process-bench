from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ModelProfile(StrictModel):
    id: str
    engine: str
    model: str
    reasoning_effort: str
    timeout_seconds: int = Field(gt=0)
    sandbox: str = "workspace-write"
    network_access: bool = False


class RoundSpec(StrictModel):
    id: str
    requirement: Path
    change_type: Literal["initial", "extension", "revision", "conflict"]


class EvaluationSpec(StrictModel):
    command: list[str] = Field(min_length=1)


class RepositoryStatsSpec(StrictModel):
    production_globs: list[str]
    test_globs: list[str]
    exclude: list[str] = Field(default_factory=list)


class TaskManifest(StrictModel):
    schema_version: Literal[1] = 1
    id: str
    name: str
    language: str
    rounds: list[RoundSpec] = Field(min_length=1)
    evaluation: EvaluationSpec
    repository_stats: RepositoryStatsSpec
    root: Path = Field(exclude=True)

    @model_validator(mode="after")
    def validate_rounds(self) -> "TaskManifest":
        ids = [item.id for item in self.rounds]
        if len(ids) != len(set(ids)):
            raise ValueError(f"Task '{self.id}' contains duplicate round IDs")
        if self.rounds[0].change_type != "initial":
            raise ValueError(f"Task '{self.id}' first round must be initial")
        if any(item.change_type == "initial" for item in self.rounds[1:]):
            raise ValueError(f"Task '{self.id}' later rounds cannot be initial")
        return self


class ProcessManifest(StrictModel):
    schema_version: Literal[1] = 1
    id: str
    name: str
    version: str
    controller: Literal["single-agent"] = "single-agent"
    instructions: Path
    expected_behaviors: list[str] = Field(default_factory=list)
    root: Path = Field(exclude=True)


class ExecutionConfig(StrictModel):
    fresh_context_per_round: Literal[True] = True
    preserve_git_history: Literal[False] = False
    randomize_run_order: bool = True
    random_seed: int = 0
    timeout_seconds: int = Field(gt=0)


class MeasurementConfig(StrictModel):
    correctness: bool = True
    repository_stats: bool = True
    structural_erosion: bool = True
    maintenance_probe: bool = True


class MaintenanceConfig(StrictModel):
    model_profile: str
    agent_profile: str = "neutral-maintainer"
    timeout_seconds: int = Field(gt=0)


class ExperimentManifest(StrictModel):
    schema_version: Literal[1] = 1
    id: str
    model_profile: str
    agent_profile: str
    processes: list[str] = Field(min_length=1)
    tasks: list[str] = Field(min_length=1)
    replicates: int = Field(gt=0)
    execution: ExecutionConfig
    measurements: MeasurementConfig
    maintenance: MaintenanceConfig | None = None
    root: Path = Field(exclude=True)


@dataclass(frozen=True)
class ResolvedExperiment:
    manifest_path: Path
    root: Path
    manifest: ExperimentManifest
    model: ModelProfile
    agent_instructions: str
    processes: dict[str, ProcessManifest]
    process_instructions: dict[str, str]
    tasks: dict[str, TaskManifest]
    maintenance_model: ModelProfile | None
    maintenance_instructions: str | None


@dataclass(frozen=True)
class Trajectory:
    task_id: str
    process_id: str
    replicate: int
    run_key: str


class UsageSummary(StrictModel):
    input_tokens: int = 0
    cached_input_tokens: int = 0
    output_tokens: int = 0
    reasoning_output_tokens: int = 0
    model_calls: int | None = None
    command_count: int = 0
    file_change_event_count: int = 0


class EngineRunResult(StrictModel):
    exit_code: int | None
    timed_out: bool = False
    termination_reason: Literal[
        "completed", "timeout", "engine_error", "infrastructure_error"
    ] = "completed"
    wall_time_seconds: float = Field(ge=0)
    usage: UsageSummary = Field(default_factory=UsageSummary)
    final_status: str | None = None

