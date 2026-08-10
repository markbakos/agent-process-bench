from __future__ import annotations

import hashlib
import json
import logging
import shutil
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

from . import __version__
from .artifacts import (
    atomic_write_json,
    atomic_write_text,
    attempt_complete,
    copy_tree,
    create_checkpoint,
    extract_checkpoint,
    initialize_git,
    maintenance_key,
    next_attempt,
    quarantine_incomplete,
    read_json,
    selected_attempt,
    sha256_file,
    tree_hash,
)
from .config import build_plan, build_prompt, stable_id
from .engines import AgentEngine, EngineInfrastructureError, engine_for
from .models import EngineRunResult, ResolvedExperiment, Trajectory, UsageSummary


LOG = logging.getLogger("apbench")
FORBIDDEN = {"AGENTS.md", "task.yaml", "experiment.yaml"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def experiment_dir(experiment: ResolvedExperiment) -> Path:
    return experiment.root / "runs" / experiment.manifest.id


def trajectory_dir(experiment: ResolvedExperiment, trajectory: Trajectory) -> Path:
    return (
        experiment_dir(experiment)
        / "trajectories"
        / trajectory.task_id
        / trajectory.process_id
        / f"rep-{trajectory.replicate:03d}"
    )


def round_dir(experiment: ResolvedExperiment, trajectory: Trajectory, index: int) -> Path:
    return trajectory_dir(experiment, trajectory) / f"round-{index:02d}"


def _hash_text(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def execution_plan_data(experiment: ResolvedExperiment) -> dict:
    plan = build_plan(experiment)
    return {
        "experiment_id": experiment.manifest.id,
        "randomized": experiment.manifest.execution.randomize_run_order,
        "random_seed": experiment.manifest.execution.random_seed,
        "trajectories": [item.__dict__ for item in plan],
    }


def experiment_lock_data(experiment: ResolvedExperiment) -> dict:
    try:
        commit = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=experiment.root, text=True, stderr=subprocess.DEVNULL
        ).strip()
        dirty = bool(
            subprocess.check_output(
                ["git", "status", "--porcelain"], cwd=experiment.root, text=True, stderr=subprocess.DEVNULL
            ).strip()
        )
    except (OSError, subprocess.SubprocessError):
        commit, dirty = None, True

    task_data = {}
    for task_id, task in experiment.tasks.items():
        task_data[task_id] = {
            "manifest_sha256": sha256_file(task.root / "task.yaml"),
            "evaluator_tree_sha256": tree_hash(task.root / "evaluator"),
            "reference_tree_sha256": tree_hash(task.root / "reference") if (task.root / "reference").is_dir() else None,
            "requirements": {
                item.id: sha256_file(task.root / item.requirement) for item in task.rounds
            },
        }
    return {
        "framework_version": __version__,
        "framework_git_commit": commit,
        "framework_git_dirty": dirty,
        "experiment_manifest_sha256": sha256_file(experiment.manifest_path),
        "experiment": experiment.manifest.model_dump(mode="json"),
        "model": experiment.model.model_dump(mode="json"),
        "agent_instructions_sha256": _hash_text(experiment.agent_instructions),
        "processes": {
            key: {
                "version": value.version,
                "manifest_sha256": sha256_file(value.root / "process.yaml"),
                "instructions_sha256": _hash_text(experiment.process_instructions[key]),
            }
            for key, value in experiment.processes.items()
        },
        "tasks": task_data,
        "evaluator_versions": {
            "correctness": "1.0.0",
            "repository_stats": "1.0.0",
            "structural_erosion": "structural-erosion-python-v1",
        },
    }


def _write_once(path: Path, value: dict) -> None:
    if path.exists():
        if read_json(path) != json.loads(json.dumps(value, default=str)):
            raise RuntimeError(f"Existing immutable artifact does not match current configuration: {path}")
        return
    atomic_write_json(path, value)


def prepare_experiment(experiment: ResolvedExperiment) -> None:
    root = experiment_dir(experiment)
    root.mkdir(parents=True, exist_ok=True)
    (root / "logs").mkdir(exist_ok=True)
    _write_once(root / "experiment-lock.json", experiment_lock_data(experiment))
    _write_once(root / "execution-plan.json", execution_plan_data(experiment))


def save_execution_plan(experiment: ResolvedExperiment) -> Path:
    path = experiment_dir(experiment) / "execution-plan.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    _write_once(path, execution_plan_data(experiment))
    return path


def _selected_checkpoint(round_path: Path) -> Path | None:
    attempt = selected_attempt(round_path)
    if attempt and attempt_complete(attempt):
        return attempt / "checkpoint.tar.gz"
    return None


def _protocol_violations(workspace: Path) -> list[str]:
    violations = []
    for path in workspace.rglob("*"):
        relative = path.relative_to(workspace)
        if path.name in FORBIDDEN or ".codex" in relative.parts:
            violations.append(relative.as_posix())
    return sorted(violations)


def run_experiment(
    experiment: ResolvedExperiment,
    *,
    resume: bool = False,
    force: bool = False,
    engine: AgentEngine | None = None,
) -> None:
    if resume and force:
        raise ValueError("--resume and --force are mutually exclusive")
    root = experiment_dir(experiment)
    if not resume and not force and root.exists() and any(root.glob("trajectories/**/attempt-*")):
        raise RuntimeError(f"Experiment has existing attempts; use --resume or --force: {root}")
    prepare_experiment(experiment)
    selected_engine = engine or engine_for(experiment.model)
    for trajectory in build_plan(experiment):
        run_trajectory(experiment, trajectory, selected_engine, resume=resume, force=force)


def run_trajectory(
    experiment: ResolvedExperiment,
    trajectory: Trajectory,
    engine: AgentEngine,
    *,
    resume: bool,
    force: bool,
) -> None:
    task = experiment.tasks[trajectory.task_id]
    trajectory_path = trajectory_dir(experiment, trajectory)
    trajectory_path.mkdir(parents=True, exist_ok=True)
    atomic_write_json(
        trajectory_path / "trajectory.json",
        {**trajectory.__dict__, "task_rounds": [item.id for item in task.rounds]},
    )
    previous_checkpoint: Path | None = None
    for index, round_spec in enumerate(task.rounds):
        current_round = round_dir(experiment, trajectory, index)
        current_round.mkdir(parents=True, exist_ok=True)
        if resume:
            quarantine_incomplete(current_round)
        selected = selected_attempt(current_round)
        if selected and attempt_complete(selected) and not force:
            if not resume:
                raise RuntimeError(f"Round already completed; use --resume or --force: {current_round}")
            LOG.info(
                "resume skip task=%s process=%s replicate=%s round=%s",
                trajectory.task_id,
                trajectory.process_id,
                trajectory.replicate,
                round_spec.id,
            )
            previous_checkpoint = selected / "checkpoint.tar.gz"
            continue
        attempt = next_attempt(current_round)
        workspace = (
            experiment_dir(experiment)
            / ".workspaces"
            / trajectory.run_key
            / f"{round_spec.id}-{attempt.name}"
        )
        if workspace.exists():
            quarantine = experiment_dir(experiment) / "quarantine" / trajectory.run_key
            quarantine.mkdir(parents=True, exist_ok=True)
            shutil.move(str(workspace), quarantine / workspace.name)
        workspace.parent.mkdir(parents=True, exist_ok=True)

        source = task.root / "starter" if index == 0 else previous_checkpoint
        if source is None:
            raise RuntimeError(f"Round '{round_spec.id}' has no previous completed checkpoint")
        if index == 0:
            copy_tree(source, workspace)
        else:
            extract_checkpoint(source, workspace)
        initialize_git(workspace)

        requirement = (task.root / round_spec.requirement).read_text(encoding="utf-8")
        prompt = build_prompt(
            experiment.agent_instructions,
            experiment.process_instructions[trajectory.process_id],
            requirement,
        )
        attempt.mkdir(parents=True, exist_ok=False)
        started_at = utc_now()
        atomic_write_json(attempt / "status.json", {"state": "running", "started_at": started_at})
        atomic_write_text(attempt / "prompt.txt", prompt)
        atomic_write_text(attempt / "prompt.sha256", _hash_text(prompt) + "\n")
        atomic_write_text(attempt / "requirement.md", requirement)
        round_key = stable_id(trajectory.run_key, round_spec.id)
        atomic_write_json(
            attempt / "round-manifest.json",
            {
                "experiment_id": experiment.manifest.id,
                "run_key": trajectory.run_key,
                "round_key": round_key,
                "task_id": trajectory.task_id,
                "process_id": trajectory.process_id,
                "process_version": experiment.processes[trajectory.process_id].version,
                "replicate": trajectory.replicate,
                "round_id": round_spec.id,
                "round_index": index,
                "change_type": round_spec.change_type,
            },
        )
        atomic_write_json(
            attempt / "resolved-config.json",
            {
                "model": experiment.model.model_dump(mode="json"),
                "timeout_seconds": experiment.manifest.execution.timeout_seconds,
            },
        )

        start = time.monotonic()
        LOG.info(
            "round start task=%s process=%s replicate=%s round=%s attempt=%s",
            trajectory.task_id,
            trajectory.process_id,
            trajectory.replicate,
            round_spec.id,
            attempt.name,
        )
        infrastructure_error = None
        try:
            result = engine.run(workspace, prompt, experiment.model, attempt / "engine")
        except EngineInfrastructureError as exc:
            infrastructure_error = str(exc)
            result = EngineRunResult(
                exit_code=None,
                termination_reason="infrastructure_error",
                wall_time_seconds=time.monotonic() - start,
                usage=UsageSummary(),
                final_status="infrastructure_error",
            )
        wall_time = time.monotonic() - start
        checkpoint_hash = create_checkpoint(workspace, attempt / "checkpoint.tar.gz")
        atomic_write_text(attempt / "checkpoint-tree.sha256", checkpoint_hash + "\n")
        finished_at = utc_now()
        violations = _protocol_violations(workspace)
        execution = {
            **result.model_dump(exclude={"usage"}),
            "wall_time_seconds": wall_time,
            "started_at": started_at,
            "finished_at": finished_at,
            "protocol_violation": bool(violations),
            "protocol_violation_files": violations,
            "infrastructure_error": infrastructure_error,
        }
        atomic_write_json(attempt / "execution.json", execution)
        atomic_write_json(attempt / "usage.json", result.usage.model_dump())
        state = "failed_infrastructure" if infrastructure_error else "completed"
        atomic_write_json(attempt / "status.json", {"state": state, "finished_at": finished_at})
        shutil.rmtree(workspace, ignore_errors=True)

        if infrastructure_error:
            raise RuntimeError(
                f"Infrastructure failure in task={trajectory.task_id} process={trajectory.process_id} "
                f"replicate={trajectory.replicate} round={round_spec.id}: {infrastructure_error}"
            )
        atomic_write_json(current_round / "selected-attempt.json", {"attempt": attempt.name})
        previous_checkpoint = attempt / "checkpoint.tar.gz"
        LOG.info(
            "round complete task=%s process=%s replicate=%s round=%s checkpoint=%s",
            trajectory.task_id,
            trajectory.process_id,
            trajectory.replicate,
            round_spec.id,
            checkpoint_hash,
        )


def status_summary(experiment: ResolvedExperiment) -> dict[str, int]:
    summary = {
        "trajectories": 0,
        "trajectories_complete": 0,
        "rounds_total": 0,
        "rounds_complete": 0,
        "correctness_evaluated": 0,
        "maintenance_eligible": 0,
        "maintenance_complete": 0,
    }
    for trajectory in build_plan(experiment):
        summary["trajectories"] += 1
        task = experiment.tasks[trajectory.task_id]
        complete = True
        for index, _ in enumerate(task.rounds):
            summary["rounds_total"] += 1
            attempt = selected_attempt(round_dir(experiment, trajectory, index))
            if not attempt or not attempt_complete(attempt):
                complete = False
                continue
            summary["rounds_complete"] += 1
            correctness = attempt / "correctness-v1.json"
            if correctness.exists():
                summary["correctness_evaluated"] += 1
                result = read_json(correctness)
                if result.get("correct") and index < len(task.rounds) - 1:
                    summary["maintenance_eligible"] += 1
                    key = maintenance_key(attempt)
                    maintenance = experiment_dir(experiment) / "maintenance" / key / "status.json"
                    if maintenance.exists() and read_json(maintenance).get("state") == "completed":
                        summary["maintenance_complete"] += 1
        if complete:
            summary["trajectories_complete"] += 1
    return summary
