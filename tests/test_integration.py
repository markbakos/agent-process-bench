from __future__ import annotations

import shutil
from pathlib import Path

import pandas as pd
import pytest

from apbench.aggregation import aggregate
from apbench.artifacts import extract_checkpoint, initialize_git, maintenance_key, read_json, selected_attempt
from apbench.config import build_plan, build_prompt, load_experiment
from apbench.engines import FakeEngine, FakeScenario
from apbench.evaluation import evaluate_experiment
from apbench.execution import experiment_dir, round_dir, run_experiment, status_summary


ROOT = Path(__file__).parents[1]


def copy_smoke(tmp_path: Path):
    root = tmp_path / "repo"
    root.mkdir(parents=True)
    for name in ("experiments", "profiles", "processes", "tasks"):
        shutil.copytree(ROOT / name, root / name)
    (root / "runs").mkdir()
    shutil.copy(ROOT / ".gitignore", root / ".gitignore")
    profile = root / "profiles" / "models" / "fake.yaml"
    profile.write_text(profile.read_text().replace("timeout_seconds: 30", "timeout_seconds: 99"))
    initialize_git(root)
    return load_experiment(root / "experiments" / "smoke.yaml")


def test_complete_fake_lifecycle_resume_evaluate_aggregate_and_force(tmp_path: Path) -> None:
    experiment = copy_smoke(tmp_path)
    engine = FakeEngine()
    run_experiment(experiment, engine=engine)
    assert engine.calls == 16
    lock = read_json(experiment_dir(experiment) / "experiment-lock.json")
    assert lock["engine_version"] == "deterministic-fake"
    assert lock["maintenance"]["engine_version"] == "deterministic-fake"

    markers: set[str] = set()
    maintenance_sources: dict[str, str] = {}
    for trajectory in build_plan(experiment):
        for index in range(4):
            current = round_dir(experiment, trajectory, index)
            attempt = selected_attempt(current)
            assert attempt is not None
            request = read_json(attempt / "engine" / "fake-request.json")
            assert request["baseline_git_commit_count"] == 1
            assert request["timeout_seconds"] == 30
            markers.add(request["invocation_marker"])
            maintenance_sources[maintenance_key(attempt)] = (attempt / "checkpoint-tree.sha256").read_text().strip()
            workspace = tmp_path / f"extract-{trajectory.run_key}-{index}"
            extract_checkpoint(attempt / "checkpoint.tar.gz", workspace)
            assert len([line for line in (workspace / "fake_output.txt").read_text().splitlines() if line]) == index + 1
            assert not (workspace / ".git").exists()
            assert not (workspace / "evaluator").exists()
            assert not (workspace / "requirements").exists()
            assert not any(marker in (workspace / "fake_output.txt").read_text() for marker in markers)

    first_round = round_dir(experiment, build_plan(experiment)[0], 0)
    stale = first_round / "attempt-999"
    stale.mkdir()
    (stale / "status.json").write_text('{"state":"running"}\n')
    resumed = FakeEngine()
    run_experiment(experiment, resume=True, engine=resumed)
    assert resumed.calls == 0
    assert (first_round / "quarantine" / "attempt-999").is_dir()

    maintenance_engine = FakeEngine()
    evaluate_experiment(experiment, engine=maintenance_engine)
    assert maintenance_engine.calls == 12
    summary = status_summary(experiment)
    assert summary == {
        "trajectories": 4,
        "trajectories_complete": 4,
        "rounds_total": 16,
        "rounds_complete": 16,
        "correctness_evaluated": 16,
        "maintenance_eligible": 12,
        "maintenance_complete": 12,
    }
    for key, expected_hash in maintenance_sources.items():
        maintenance = experiment_dir(experiment) / "maintenance" / key
        if maintenance.exists():
            assert read_json(maintenance / "source-checkpoint.json")["checkpoint_tree_sha256"] == expected_hash

    forced_maintenance = FakeEngine()
    evaluate_experiment(experiment, engine=forced_maintenance, force=True)
    assert forced_maintenance.calls == 12

    csv_path, parquet_path = aggregate(experiment)
    assert len(pd.read_csv(csv_path)) == 16
    assert len(pd.read_parquet(parquet_path)) == 16

    forced = FakeEngine()
    run_experiment(experiment, force=True, engine=forced)
    assert forced.calls == 16
    assert (first_round / "attempt-001").is_dir()
    assert selected_attempt(first_round).name == "attempt-002"


def _prompt(experiment, trajectory, index: int) -> str:
    task = experiment.tasks[trajectory.task_id]
    requirement = (task.root / task.rounds[index].requirement).read_text()
    return build_prompt(
        experiment.agent_instructions,
        experiment.process_instructions[trajectory.process_id],
        requirement,
    )


def test_failures_are_archived_and_infrastructure_can_resume(tmp_path: Path) -> None:
    interrupted = copy_smoke(tmp_path / "interrupted")
    first = build_plan(interrupted)[0]
    engine = FakeEngine({_prompt(interrupted, first, 0): FakeScenario(outcome="infrastructure_error")})
    with pytest.raises(RuntimeError, match="Infrastructure failure"):
        run_experiment(interrupted, engine=engine)
    failed_round = round_dir(interrupted, first, 0)
    assert read_json(failed_round / "attempt-001" / "status.json")["state"] == "failed_infrastructure"
    with pytest.raises(RuntimeError, match="use --resume or --force"):
        run_experiment(interrupted, engine=FakeEngine())
    run_experiment(interrupted, resume=True, engine=FakeEngine())
    assert (failed_round / "quarantine" / "attempt-001").is_dir()
    assert selected_attempt(failed_round) is not None

    outcomes = copy_smoke(tmp_path / "outcomes")
    first = build_plan(outcomes)[0]
    scenarios = {
        _prompt(outcomes, first, 0): FakeScenario(outcome="timeout"),
        _prompt(outcomes, first, 1): FakeScenario(outcome="crash"),
        _prompt(outcomes, first, 2): FakeScenario(outcome="forbidden_file"),
    }
    run_experiment(outcomes, engine=FakeEngine(scenarios))
    timeout = selected_attempt(round_dir(outcomes, first, 0))
    crash = selected_attempt(round_dir(outcomes, first, 1))
    forbidden = selected_attempt(round_dir(outcomes, first, 2))
    assert timeout and read_json(timeout / "execution.json")["timed_out"]
    assert crash and read_json(crash / "execution.json")["termination_reason"] == "engine_error"
    assert forbidden and read_json(forbidden / "execution.json")["protocol_violation"]
    extracted = tmp_path / "forbidden-checkpoint"
    extract_checkpoint(forbidden / "checkpoint.tar.gz", extracted)
    assert (extracted / "AGENTS.md").is_file()


def test_selected_run_is_saved_and_resume_uses_the_same_plan(tmp_path: Path) -> None:
    experiment = copy_smoke(tmp_path)
    engine = FakeEngine()
    run_experiment(experiment, engine=engine, process_ids=["direct"], replicates=[1])
    assert engine.calls == 4
    assert status_summary(experiment)["trajectories"] == 1

    resumed = FakeEngine()
    run_experiment(experiment, engine=resumed, resume=True)
    assert resumed.calls == 0


def test_real_runs_require_a_clean_framework_checkout(tmp_path: Path) -> None:
    experiment = copy_smoke(tmp_path)
    (experiment.root / "dirty.txt").write_text("dirty\n")
    with pytest.raises(RuntimeError, match="clean Git checkout"):
        run_experiment(experiment, engine=FakeEngine())

    run_experiment(
        experiment,
        engine=FakeEngine(),
        process_ids=["direct"],
        replicates=[1],
        allow_dirty_framework=True,
    )
    assert read_json(experiment_dir(experiment) / "experiment-lock.json")["framework_git_dirty"]
