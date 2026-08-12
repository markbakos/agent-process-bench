from __future__ import annotations

import csv
from pathlib import Path

import pandas as pd

from .artifacts import atomic_write_text, maintenance_key, read_json, selected_attempt
from .execution import experiment_dir, round_dir, saved_execution_plan
from .models import ResolvedExperiment


COLUMNS = [
    "experiment_id", "run_id", "round_id", "task_id", "process_id", "process_version",
    "model", "reasoning_effort", "replicate", "round_index", "change_type",
    "evolution_depth", "normalized_depth", "checkpoint_tree_sha256", "correct",
    "tests_passed", "tests_total", "build_status", "evaluation_status", "production_loc",
    "test_loc", "production_file_count", "test_file_count", "structural_erosion",
    "maintenance_probe_eligible", "maintenance_probe_success", "input_tokens",
    "cached_input_tokens", "uncached_input_tokens", "output_tokens",
    "reasoning_output_tokens", "wall_time_seconds", "command_count",
    "file_change_event_count", "timed_out", "termination_reason", "protocol_violation",
    "engine", "framework_version",
]


def rows(experiment: ResolvedExperiment) -> list[dict]:
    result: list[dict] = []
    for trajectory in saved_execution_plan(experiment):
        task = experiment.tasks[trajectory.task_id]
        final_index = len(task.rounds) - 1
        for index, round_spec in enumerate(task.rounds):
            attempt = selected_attempt(round_dir(experiment, trajectory, index))
            if not attempt:
                continue
            manifest = read_json(attempt / "round-manifest.json")
            execution = read_json(attempt / "execution.json")
            usage = read_json(attempt / "usage.json")
            correctness = read_json(attempt / "correctness-v1.json") if (attempt / "correctness-v1.json").exists() else {}
            stats = read_json(attempt / "repository-stats-v1.json") if (attempt / "repository-stats-v1.json").exists() else {}
            erosion = read_json(attempt / "structural-erosion-python-v1.json") if (attempt / "structural-erosion-python-v1.json").exists() else {}
            eligible = bool(correctness.get("correct")) and index < final_index
            checkpoint_hash = (attempt / "checkpoint-tree.sha256").read_text().strip()
            maintenance_path = experiment_dir(experiment) / "maintenance" / maintenance_key(attempt) / "status.json"
            maintenance = read_json(maintenance_path) if maintenance_path.exists() else {}
            input_tokens = usage.get("input_tokens", 0)
            cached = usage.get("cached_input_tokens", 0)
            result.append({
                "experiment_id": experiment.manifest.id,
                "run_id": trajectory.run_key,
                "round_id": round_spec.id,
                "task_id": trajectory.task_id,
                "process_id": trajectory.process_id,
                "process_version": experiment.processes[trajectory.process_id].version,
                "model": experiment.model.model,
                "reasoning_effort": experiment.model.reasoning_effort,
                "replicate": trajectory.replicate,
                "round_index": index,
                "change_type": round_spec.change_type,
                "evolution_depth": index,
                "normalized_depth": index / final_index if final_index else 0.0,
                "checkpoint_tree_sha256": checkpoint_hash,
                "correct": correctness.get("correct"),
                "tests_passed": correctness.get("tests_passed"),
                "tests_total": correctness.get("tests_total"),
                "build_status": correctness.get("build_status"),
                "evaluation_status": correctness.get("status"),
                "production_loc": stats.get("production_loc"),
                "test_loc": stats.get("test_loc"),
                "production_file_count": stats.get("production_file_count"),
                "test_file_count": stats.get("test_file_count"),
                "structural_erosion": erosion.get("structural_erosion"),
                "maintenance_probe_eligible": eligible,
                "maintenance_probe_success": maintenance.get("maintenance_success") if eligible else None,
                "input_tokens": input_tokens,
                "cached_input_tokens": cached,
                "uncached_input_tokens": input_tokens - cached,
                "output_tokens": usage.get("output_tokens", 0),
                "reasoning_output_tokens": usage.get("reasoning_output_tokens", 0),
                "wall_time_seconds": execution.get("wall_time_seconds"),
                "command_count": usage.get("command_count", 0),
                "file_change_event_count": usage.get("file_change_event_count", 0),
                "timed_out": execution.get("timed_out"),
                "termination_reason": execution.get("termination_reason"),
                "protocol_violation": execution.get("protocol_violation"),
                "engine": experiment.model.engine,
                "framework_version": read_json(experiment_dir(experiment) / "experiment-lock.json")["framework_version"],
            })
    return sorted(result, key=lambda row: (row["task_id"], row["process_id"], row["replicate"], row["round_index"]))


def aggregate(experiment: ResolvedExperiment) -> tuple[Path, Path]:
    data = rows(experiment)
    destination = experiment_dir(experiment) / "results"
    destination.mkdir(parents=True, exist_ok=True)
    csv_path = destination / "master.csv"
    lines: list[str] = []
    from io import StringIO
    buffer = StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=COLUMNS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(data)
    atomic_write_text(csv_path, buffer.getvalue())
    parquet_path = destination / "master.parquet"
    temporary = parquet_path.with_name(f".{parquet_path.name}.tmp")
    pd.DataFrame(data, columns=COLUMNS).to_parquet(temporary, index=False)
    temporary.replace(parquet_path)
    return csv_path, parquet_path
