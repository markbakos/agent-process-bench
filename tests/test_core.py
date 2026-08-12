from __future__ import annotations

import io
import json
import sys
import tarfile
from pathlib import Path

import pytest

from apbench.artifacts import (
    atomic_write_json,
    create_checkpoint,
    extract_checkpoint,
    initialize_git,
    read_json,
    tree_hash,
)
from apbench.config import ConfigError, build_plan, build_prompt, load_experiment, stable_id
from apbench.engines import FakeEngine, FakeScenario
from apbench.evaluation import correctness, repository_stats, structural_erosion
from apbench.models import ModelProfile, RepositoryStatsSpec, TaskManifest, EvaluationSpec, RoundSpec


ROOT = Path(__file__).parents[1]


def test_configuration_prompt_and_plan_are_deterministic() -> None:
    experiment = load_experiment(ROOT / "experiments" / "smoke.yaml")
    first = build_plan(experiment)
    second = build_plan(experiment)
    assert first == second
    assert len(first) == 4
    assert len({item.run_key for item in first}) == 4
    assert stable_id("a", 1) == stable_id("a", 1)
    prompt = build_prompt("agent", "process", "requirement body")
    assert "# Current requirement\n\nrequirement body\n" in prompt
    with pytest.raises(ConfigError, match="Unknown selected processes"):
        build_plan(experiment, process_ids=["missing"])


def test_checkpoint_hash_excludes_git_and_rejects_unsafe_archive(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "a.txt").write_text("a", encoding="utf-8")
    initialize_git(workspace)
    checkpoint = tmp_path / "checkpoint.tar.gz"
    expected = tree_hash(workspace)
    assert create_checkpoint(workspace, checkpoint) == expected
    extracted = tmp_path / "extracted"
    extract_checkpoint(checkpoint, extracted)
    assert tree_hash(extracted) == expected
    assert not (extracted / ".git").exists()

    malicious = tmp_path / "malicious.tar.gz"
    with tarfile.open(malicious, "w:gz") as archive:
        info = tarfile.TarInfo("../escape")
        info.size = 1
        archive.addfile(info, io.BytesIO(b"x"))
    with pytest.raises(ValueError, match="Unsafe checkpoint"):
        extract_checkpoint(malicious, tmp_path / "unsafe")


def test_atomic_json_and_fake_engine_scenarios(tmp_path: Path) -> None:
    target = tmp_path / "result.json"
    atomic_write_json(target, {"b": 2, "a": 1})
    assert read_json(target) == {"a": 1, "b": 2}

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    initialize_git(workspace)
    prompt = "timeout prompt"
    engine = FakeEngine({prompt: FakeScenario(outcome="timeout")})
    profile = ModelProfile(
        id="fake", engine="fake", model="fake", reasoning_effort="none", timeout_seconds=1
    )
    result = engine.run(workspace, prompt, profile, tmp_path / "engine")
    assert result.timed_out
    assert result.termination_reason == "timeout"
    assert (tmp_path / "engine" / "fake-request.json").is_file()
    assert not (workspace / "fake_output.txt").exists()


def test_stats_and_erosion_have_known_baselines(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "src" / "simple.py").write_text("# comment\n\ndef f():\n    return 1\n")
    (tmp_path / "tests" / "test_simple.py").write_text("assert True\n")
    task = TaskManifest(
        id="fixture",
        name="Fixture",
        language="python",
        rounds=[RoundSpec(id="r00", requirement=Path("r00.md"), change_type="initial")],
        evaluation=EvaluationSpec(command=["true"]),
        repository_stats=RepositoryStatsSpec(
            production_globs=["src/**/*.py"], test_globs=["tests/**/*.py"]
        ),
        root=tmp_path,
    )
    stats = repository_stats(tmp_path, task)
    assert stats["production_loc"] == 2
    assert stats["test_loc"] == 1
    assert structural_erosion(tmp_path, task)["structural_erosion"] == 0


def test_evaluator_timeout_is_bounded_and_recorded(tmp_path: Path) -> None:
    task = TaskManifest(
        id="timeout",
        name="Timeout",
        language="python",
        rounds=[RoundSpec(id="r00", requirement=Path("r00.md"), change_type="initial")],
        evaluation=EvaluationSpec(
            command=[sys.executable, "-c", "import time; time.sleep(10)"],
            timeout_seconds=1,
        ),
        repository_stats=RepositoryStatsSpec(production_globs=[], test_globs=[]),
        root=tmp_path,
    )

    result = correctness(tmp_path, task, task.rounds[0], tmp_path / "evaluation")

    assert result["status"] == "timeout"
    assert not result["correct"]
