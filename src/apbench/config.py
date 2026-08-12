from __future__ import annotations

import hashlib
import random
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from .models import (
    ExperimentManifest,
    ModelProfile,
    ProcessManifest,
    ResolvedExperiment,
    TaskManifest,
    Trajectory,
)


class ConfigError(ValueError):
    pass


def _yaml(path: Path) -> dict[str, Any]:
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ConfigError(f"Cannot read YAML '{path}': {exc}") from exc
    if not isinstance(value, dict):
        raise ConfigError(f"YAML '{path}' must contain an object")
    return value


def _model(model_type, path: Path, *, root: Path | None = None):
    data = _yaml(path)
    if root is not None:
        data["root"] = root
    try:
        return model_type.model_validate(data)
    except ValidationError as exc:
        raise ConfigError(f"Invalid manifest '{path}':\n{exc}") from exc


def _inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _require_file(path: Path, description: str) -> None:
    if not path.is_file():
        raise ConfigError(f"{description} does not exist: {path}")


def load_experiment(path: Path) -> ResolvedExperiment:
    path = path.resolve()
    _require_file(path, "Experiment manifest")
    root = path.parent.parent
    manifest = _model(ExperimentManifest, path, root=root)

    model_path = root / "profiles" / "models" / f"{manifest.model_profile}.yaml"
    _require_file(model_path, f"Model profile '{manifest.model_profile}'")
    model = _model(ModelProfile, model_path)
    if model.id != manifest.model_profile:
        raise ConfigError(f"Model profile directory key '{manifest.model_profile}' does not match id '{model.id}'")

    agent_path = root / "profiles" / "agents" / manifest.agent_profile / "instructions.md"
    _require_file(agent_path, f"Agent profile '{manifest.agent_profile}'")

    processes: dict[str, ProcessManifest] = {}
    process_text: dict[str, str] = {}
    for process_id in manifest.processes:
        process_root = root / "processes" / process_id
        process_path = process_root / "process.yaml"
        _require_file(process_path, f"Process '{process_id}'")
        process = _model(ProcessManifest, process_path, root=process_root)
        if process.id != process_id:
            raise ConfigError(f"Process directory '{process_id}' does not match id '{process.id}'")
        instruction_path = process_root / process.instructions
        if not _inside(instruction_path, process_root):
            raise ConfigError(f"Process '{process_id}' instructions escape its pack")
        _require_file(instruction_path, f"Process '{process_id}' instructions")
        processes[process_id] = process
        process_text[process_id] = instruction_path.read_text(encoding="utf-8")

    tasks: dict[str, TaskManifest] = {}
    for task_id in manifest.tasks:
        task_root = root / "tasks" / task_id
        task_path = task_root / "task.yaml"
        _require_file(task_path, f"Task '{task_id}'")
        task = _model(TaskManifest, task_path, root=task_root)
        if task.id != task_id:
            raise ConfigError(f"Task directory '{task_id}' does not match id '{task.id}'")
        validate_task(task)
        tasks[task_id] = task

    maintenance_model = None
    maintenance_instructions = None
    if manifest.maintenance:
        maintenance_path = root / "profiles" / "models" / f"{manifest.maintenance.model_profile}.yaml"
        _require_file(maintenance_path, f"Maintenance model '{manifest.maintenance.model_profile}'")
        maintenance_model = _model(ModelProfile, maintenance_path)
        if maintenance_model.id != manifest.maintenance.model_profile:
            raise ConfigError(
                f"Maintenance model profile directory key '{manifest.maintenance.model_profile}' "
                f"does not match id '{maintenance_model.id}'"
            )
        maintenance_agent = root / "profiles" / "agents" / manifest.maintenance.agent_profile / "instructions.md"
        _require_file(maintenance_agent, f"Maintenance agent '{manifest.maintenance.agent_profile}'")
        maintenance_instructions = maintenance_agent.read_text(encoding="utf-8")

    return ResolvedExperiment(
        manifest_path=path,
        root=root,
        manifest=manifest,
        model=model,
        agent_instructions=agent_path.read_text(encoding="utf-8"),
        processes=processes,
        process_instructions=process_text,
        tasks=tasks,
        maintenance_model=maintenance_model,
        maintenance_instructions=maintenance_instructions,
    )


def load_task_manifest(path: Path) -> TaskManifest:
    path = path.resolve()
    _require_file(path, "Task manifest")
    task = _model(TaskManifest, path, root=path.parent)
    validate_task(task)
    return task


def validate_task(task: TaskManifest) -> list[str]:
    starter = task.root / "starter"
    if not starter.is_dir():
        raise ConfigError(f"Task '{task.id}' starter directory does not exist: {starter}")

    for round_spec in task.rounds:
        requirement = task.root / round_spec.requirement
        if not _inside(requirement, task.root):
            raise ConfigError(f"Task '{task.id}' requirement '{round_spec.requirement}' escapes its pack")
        _require_file(requirement, f"Task '{task.id}' requirement '{round_spec.requirement}'")

    forbidden_names = {"AGENTS.md", "task.yaml", "experiment.yaml"}
    forbidden_dirs = {".codex", "evaluator", "reference", "requirements"}
    requirement_hashes = {
        hashlib.sha256((task.root / item.requirement).read_bytes()).hexdigest()
        for item in task.rounds
    }
    for item in starter.rglob("*"):
        relative = item.relative_to(starter)
        if item.name in forbidden_names or any(part in forbidden_dirs for part in relative.parts):
            raise ConfigError(f"Task '{task.id}' starter exposes forbidden experiment file: {relative}")
        if item.is_symlink() and not _inside(item, starter):
            raise ConfigError(f"Task '{task.id}' starter symlink escapes the starter: {relative}")
        if item.is_file() and not item.is_symlink() and hashlib.sha256(item.read_bytes()).hexdigest() in requirement_hashes:
            raise ConfigError(f"Task '{task.id}' starter contains a requirement file: {relative}")

    for arg in task.evaluation.command:
        if arg.endswith(".py") and "{" not in arg:
            _require_file(task.root / arg, f"Task '{task.id}' evaluator script")

    warnings: list[str] = []
    conflicts = [index for index, item in enumerate(task.rounds) if item.change_type == "conflict"]
    if conflicts and conflicts == [len(task.rounds) - 1]:
        warnings.append(f"Task '{task.id}': all conflict changes occur at final depth")
    return warnings


def stable_id(*parts: object) -> str:
    value = "\0".join(str(part) for part in parts).encode()
    return hashlib.sha256(value).hexdigest()


def build_plan(
    experiment: ResolvedExperiment,
    *,
    task_ids: list[str] | None = None,
    process_ids: list[str] | None = None,
    replicates: list[int] | None = None,
) -> list[Trajectory]:
    manifest = experiment.manifest
    selected_tasks = set(task_ids or manifest.tasks)
    selected_processes = set(process_ids or manifest.processes)
    selected_replicates = set(replicates or range(1, manifest.replicates + 1))
    unknown_tasks = selected_tasks.difference(manifest.tasks)
    unknown_processes = selected_processes.difference(manifest.processes)
    unknown_replicates = selected_replicates.difference(range(1, manifest.replicates + 1))
    if unknown_tasks:
        raise ConfigError(f"Unknown selected tasks: {', '.join(sorted(unknown_tasks))}")
    if unknown_processes:
        raise ConfigError(f"Unknown selected processes: {', '.join(sorted(unknown_processes))}")
    if unknown_replicates:
        raise ConfigError(
            f"Selected replicates are outside 1..{manifest.replicates}: "
            f"{', '.join(str(item) for item in sorted(unknown_replicates))}"
        )
    items = [
        Trajectory(
            task_id=task_id,
            process_id=process_id,
            replicate=replicate,
            run_key=stable_id(manifest.id, task_id, process_id, manifest.model_profile, replicate),
        )
        for task_id in manifest.tasks
        for process_id in manifest.processes
        for replicate in range(1, manifest.replicates + 1)
    ]
    if manifest.execution.randomize_run_order:
        random.Random(manifest.execution.random_seed).shuffle(items)
    return [
        item
        for item in items
        if item.task_id in selected_tasks
        and item.process_id in selected_processes
        and item.replicate in selected_replicates
    ]


def build_prompt(agent_instructions: str, process_instructions: str, requirement: str) -> str:
    return (
        "# Experimental development instructions\n\n"
        f"{agent_instructions.strip()}\n\n"
        "# Development process\n\n"
        f"{process_instructions.strip()}\n\n"
        "# Current requirement\n\n"
        f"{requirement.strip()}\n\n"
        "# Completion\n\n"
        "Work autonomously until you believe the current requirement is complete.\n"
    )
