from __future__ import annotations

import json
import math
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path, PurePath

from radon.complexity import cc_visit

from .artifacts import (
    atomic_write_json,
    atomic_write_text,
    create_checkpoint,
    extract_checkpoint,
    initialize_git,
    maintenance_key,
    read_json,
    selected_attempt,
    tree_hash,
)
from .config import build_plan, build_prompt
from .engines import AgentEngine, EngineInfrastructureError, engine_for
from .execution import experiment_dir, round_dir
from .models import ResolvedExperiment, RoundSpec, TaskManifest


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _excluded(relative: Path, patterns: list[str]) -> bool:
    return any(PurePath(relative.as_posix()).match(pattern) for pattern in patterns)


def _files(workspace: Path, patterns: list[str], exclude: list[str]) -> set[Path]:
    return {
        path
        for pattern in patterns
        for path in workspace.glob(pattern)
        if path.is_file() and not _excluded(path.relative_to(workspace), exclude)
    }


def _physical_loc(path: Path) -> int:
    return sum(
        1
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    )


def repository_stats(workspace: Path, task: TaskManifest) -> dict:
    spec = task.repository_stats
    production = _files(workspace, spec.production_globs, spec.exclude)
    tests = _files(workspace, spec.test_globs, spec.exclude)
    return {
        "evaluator_id": "repository-stats",
        "evaluator_version": "1.0.0",
        "created_at": now(),
        "production_loc": sum(_physical_loc(path) for path in production),
        "test_loc": sum(_physical_loc(path) for path in tests),
        "production_file_count": len(production),
        "test_file_count": len(tests),
    }


def structural_erosion(workspace: Path, task: TaskManifest) -> dict:
    files = _files(
        workspace,
        [pattern for pattern in task.repository_stats.production_globs if pattern.endswith(".py")],
        task.repository_stats.exclude,
    )
    masses: list[tuple[int, float]] = []
    errors: list[str] = []
    for path in sorted(files):
        source = path.read_text(encoding="utf-8", errors="replace")
        lines = source.splitlines()
        try:
            blocks = [block for block in cc_visit(source) if getattr(block, "letter", "") in {"F", "M"}]
        except (SyntaxError, ValueError) as exc:
            errors.append(f"{path.relative_to(workspace)}: {exc}")
            continue
        for block in blocks:
            segment = lines[max(block.lineno - 1, 0) : block.endline]
            sloc = sum(1 for line in segment if line.strip() and not line.lstrip().startswith("#"))
            masses.append((block.complexity, block.complexity * math.sqrt(max(sloc, 1))))
    total = sum(mass for _, mass in masses)
    return {
        "evaluator_id": "structural-erosion",
        "evaluator_version": "structural-erosion-python-v1",
        "created_at": now(),
        "structural_erosion": (sum(mass for complexity, mass in masses if complexity > 10) / total if total else 0.0),
        "callable_count": len(masses),
        "errors": errors,
    }


def correctness(workspace: Path, task: TaskManifest, round_spec: RoundSpec, output_dir: Path) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    evaluator_output = output_dir / "evaluator-output.json"
    command = [
        value.format(workspace=str(workspace), round_id=round_spec.id, output=str(evaluator_output))
        for value in task.evaluation.command
    ]
    try:
        completed = subprocess.run(command, cwd=task.root, text=True, capture_output=True, check=False)
    except OSError as exc:
        atomic_write_text(output_dir / "evaluator-stdout.log", "")
        atomic_write_text(output_dir / "evaluator-stderr.log", str(exc) + "\n")
        return {
            "evaluator_id": "correctness",
            "evaluator_version": "1.0.0",
            "created_at": now(),
            "status": "error",
            "correct": False,
            "tests_passed": 0,
            "tests_total": 0,
            "build_status": "failed",
            "exit_code": None,
            "raw": {"status": "error", "error": str(exc)},
        }
    atomic_write_text(output_dir / "evaluator-stdout.log", completed.stdout)
    atomic_write_text(output_dir / "evaluator-stderr.log", completed.stderr)
    try:
        raw = read_json(evaluator_output)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raw = {"status": "error", "error": f"Evaluator did not produce valid JSON: {exc}"}
    passed = int(raw.get("tests_passed", 0))
    total = int(raw.get("tests_total", 0))
    build_status = raw.get("build_status", "failed")
    status = raw.get("status", "error")
    return {
        "evaluator_id": "correctness",
        "evaluator_version": "1.0.0",
        "created_at": now(),
        "status": status,
        "correct": completed.returncode == 0 and status == "ok" and build_status == "passed" and passed == total,
        "tests_passed": passed,
        "tests_total": total,
        "build_status": build_status,
        "exit_code": completed.returncode,
        "raw": raw,
    }


def evaluate_experiment(experiment: ResolvedExperiment, engine: AgentEngine | None = None) -> None:
    maintenance_engine = engine or (engine_for(experiment.maintenance_model) if experiment.maintenance_model else None)
    for trajectory in build_plan(experiment):
        task = experiment.tasks[trajectory.task_id]
        for index, round_spec in enumerate(task.rounds):
            attempt = selected_attempt(round_dir(experiment, trajectory, index))
            if not attempt:
                continue
            with tempfile.TemporaryDirectory(prefix="apbench-evaluate-") as temporary:
                workspace = Path(temporary) / "workspace"
                extract_checkpoint(attempt / "checkpoint.tar.gz", workspace)
                correctness_path = attempt / "correctness-v1.json"
                if not correctness_path.exists() and experiment.manifest.measurements.correctness:
                    result = correctness(workspace, task, round_spec, attempt / "evaluator" / "correctness-v1")
                    atomic_write_json(correctness_path, result)
                elif correctness_path.exists():
                    result = read_json(correctness_path)
                else:
                    result = {"correct": False}

                stats_path = attempt / "repository-stats-v1.json"
                if not stats_path.exists() and experiment.manifest.measurements.repository_stats:
                    atomic_write_json(stats_path, repository_stats(workspace, task))

                erosion_path = attempt / "structural-erosion-python-v1.json"
                if not erosion_path.exists() and experiment.manifest.measurements.structural_erosion:
                    atomic_write_json(erosion_path, structural_erosion(workspace, task))

            if (
                result.get("correct")
                and index < len(task.rounds) - 1
                and experiment.manifest.measurements.maintenance_probe
                and experiment.manifest.maintenance
                and maintenance_engine
            ):
                run_maintenance_probe(
                    experiment,
                    task,
                    attempt,
                    task.rounds[index + 1],
                    maintenance_engine,
                )


def run_maintenance_probe(
    experiment: ResolvedExperiment,
    task: TaskManifest,
    source_attempt: Path,
    next_round: RoundSpec,
    engine: AgentEngine,
) -> None:
    manifest = read_json(source_attempt / "round-manifest.json")
    source_hash = (source_attempt / "checkpoint-tree.sha256").read_text(encoding="utf-8").strip()
    maintenance_root = experiment_dir(experiment) / "maintenance"
    key = maintenance_key(source_attempt)
    destination = maintenance_root / key
    status_path = destination / "status.json"
    if status_path.exists() and read_json(status_path).get("state") == "completed":
        return
    if destination.exists():
        quarantine = maintenance_root / "quarantine"
        quarantine.mkdir(parents=True, exist_ok=True)
        archived = quarantine / key
        suffix = 1
        while archived.exists():
            archived = quarantine / f"{key}-{suffix}"
            suffix += 1
        shutil.move(destination, archived)
    destination.mkdir(parents=True, exist_ok=True)
    atomic_write_json(
        destination / "source-checkpoint.json",
        {"round_key": manifest["round_key"], "checkpoint_tree_sha256": source_hash},
    )
    atomic_write_json(status_path, {"state": "running", "started_at": now()})
    with tempfile.TemporaryDirectory(prefix="apbench-maintenance-") as temporary:
        workspace = Path(temporary) / "workspace"
        extract_checkpoint(source_attempt / "checkpoint.tar.gz", workspace)
        initialize_git(workspace)
        requirement = (task.root / next_round.requirement).read_text(encoding="utf-8")
        prompt = build_prompt(
            experiment.maintenance_instructions or "",
            "Choose the simplest correct implementation approach.",
            requirement,
        )
        atomic_write_text(destination / "prompt.txt", prompt)
        try:
            result = engine.run(workspace, prompt, experiment.maintenance_model, destination / "engine")
        except EngineInfrastructureError as exc:
            atomic_write_json(status_path, {"state": "failed_infrastructure", "error": str(exc), "finished_at": now()})
            raise
        atomic_write_json(destination / "execution.json", result.model_dump(exclude={"usage"}))
        atomic_write_json(destination / "usage.json", result.usage.model_dump())
        result_hash = create_checkpoint(workspace, destination / "result-checkpoint.tar.gz")
        atomic_write_text(destination / "result-checkpoint-tree.sha256", result_hash + "\n")
        check = correctness(workspace, task, next_round, destination / "evaluator" / "correctness-v1")
        atomic_write_json(destination / "correctness-v1.json", check)
    if (source_attempt / "checkpoint-tree.sha256").read_text(encoding="utf-8").strip() != source_hash:
        raise RuntimeError(f"Maintenance probe mutated source checkpoint: {source_attempt}")
    atomic_write_json(
        status_path,
        {"state": "completed", "finished_at": now(), "maintenance_success": check["correct"]},
    )


def validate_references(task: TaskManifest) -> None:
    for round_spec in task.rounds:
        reference = task.root / "reference" / round_spec.id
        if not reference.is_dir():
            raise ValueError(f"Task '{task.id}' reference does not exist: {reference}")
        with tempfile.TemporaryDirectory(prefix="apbench-reference-") as temporary:
            output = Path(temporary) / "evaluation"
            result = correctness(reference, task, round_spec, output)
            if not result["correct"]:
                raise ValueError(f"Task '{task.id}' reference '{round_spec.id}' failed evaluation: {result}")
