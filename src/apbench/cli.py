from __future__ import annotations

import argparse
import logging
import re
import sys
from pathlib import Path

from .aggregation import aggregate
from .artifacts import atomic_write_text
from .config import ConfigError, build_plan, load_experiment, load_task_manifest, validate_task
from .evaluation import evaluate_experiment, validate_references
from .execution import experiment_dir, run_experiment, save_execution_plan, status_summary


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="apbench")
    commands = root.add_subparsers(dest="command", required=True)
    for name in ("validate", "plan", "evaluate", "aggregate", "status"):
        command = commands.add_parser(name)
        command.add_argument("experiment", type=Path)
    run = commands.add_parser("run")
    run.add_argument("experiment", type=Path)
    choice = run.add_mutually_exclusive_group()
    choice.add_argument("--resume", action="store_true")
    choice.add_argument("--force", action="store_true")
    task = commands.add_parser("validate-task")
    task.add_argument("task", type=Path)
    task.add_argument("--references", action="store_true")
    new_task = commands.add_parser("new-task")
    new_task.add_argument("name")
    new_task.add_argument("--root", type=Path, default=Path.cwd())
    new_process = commands.add_parser("new-process")
    new_process.add_argument("name")
    new_process.add_argument("--root", type=Path, default=Path.cwd())
    return root


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    if not slug:
        raise ValueError("Name must contain a letter or digit")
    return slug


def _write_new(path: Path, value: str) -> None:
    if path.exists():
        raise FileExistsError(f"Refusing to overwrite: {path}")
    atomic_write_text(path, value)


def new_task(root: Path, name: str) -> Path:
    slug = _slug(name)
    target = root.resolve() / "tasks" / slug
    if target.exists():
        raise FileExistsError(f"Task already exists: {target}")
    (target / "starter").mkdir(parents=True)
    (target / "requirements").mkdir()
    (target / "evaluator").mkdir()
    (target / "reference" / "r00").mkdir(parents=True)
    _write_new(target / "starter" / "README.md", f"# {name}\n")
    _write_new(target / "requirements" / "r00.md", "Describe the initial requirement.\n")
    _write_new(
        target / "evaluator" / "run.py",
        "# Write the evaluator contract JSON to the --output path.\n",
    )
    _write_new(
        target / "task.yaml",
        f'''schema_version: 1
id: {slug}
name: {name}
language: python
rounds:
  - id: r00
    requirement: requirements/r00.md
    change_type: initial
evaluation:
  command: [python, evaluator/run.py, --workspace, "{{workspace}}", --round, "{{round_id}}", --output, "{{output}}"]
repository_stats:
  production_globs: ["src/**/*.py"]
  test_globs: ["tests/**/*.py"]
  exclude: [".git/**", "__pycache__/**", ".pytest_cache/**"]
''',
    )
    return target


def new_process(root: Path, name: str) -> Path:
    slug = _slug(name)
    target = root.resolve() / "processes" / slug
    if target.exists():
        raise FileExistsError(f"Process already exists: {target}")
    target.mkdir(parents=True)
    _write_new(target / "instructions.md", "Describe only the required development behavior.\n")
    _write_new(
        target / "process.yaml",
        f'''schema_version: 1
id: {slug}
name: {name}
version: "1"
controller: single-agent
instructions: instructions.md
''',
    )
    return target


def _configure_logging(experiment) -> None:
    log_path = experiment_dir(experiment) / "logs" / "runner.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.FileHandler(log_path), logging.StreamHandler()],
        force=True,
    )


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "new-task":
            print(new_task(args.root, args.name))
            return 0
        if args.command == "new-process":
            print(new_process(args.root, args.name))
            return 0
        if args.command == "validate-task":
            path = args.task if args.task.name == "task.yaml" else args.task / "task.yaml"
            task = load_task_manifest(path)
            if args.references:
                validate_references(task)
            for warning in validate_task(task):
                print(f"WARNING: {warning}")
            print(f"Task '{task.id}' is valid")
            return 0

        experiment = load_experiment(args.experiment)
        if args.command == "validate":
            warnings = [warning for task in experiment.tasks.values() for warning in validate_task(task)]
            for warning in warnings:
                print(f"WARNING: {warning}")
            print(f"Experiment '{experiment.manifest.id}' is valid")
        elif args.command == "plan":
            plan = build_plan(experiment)
            save_execution_plan(experiment)
            rounds = sum(len(experiment.tasks[item.task_id].rounds) for item in plan)
            print(f"Experiment:   {experiment.manifest.id}")
            print(f"Model:        {experiment.model.model} / {experiment.model.reasoning_effort}")
            print(f"Tasks:        {len(experiment.manifest.tasks)}")
            print(f"Processes:    {len(experiment.manifest.processes)}")
            print(f"Replicates:   {experiment.manifest.replicates}")
            print(f"Trajectories: {len(plan)}")
            print(f"Rounds:       {rounds}")
            print(f"Max seconds:  {rounds * experiment.manifest.execution.timeout_seconds}")
        elif args.command == "run":
            _configure_logging(experiment)
            run_experiment(experiment, resume=args.resume, force=args.force)
            print(f"Completed experiment execution: {experiment.manifest.id}")
        elif args.command == "evaluate":
            evaluate_experiment(experiment)
            print(f"Completed evaluation: {experiment.manifest.id}")
        elif args.command == "aggregate":
            csv_path, parquet_path = aggregate(experiment)
            print(csv_path)
            print(parquet_path)
        elif args.command == "status":
            summary = status_summary(experiment)
            for key, value in summary.items():
                print(f"{key}: {value}")
        return 0
    except (ConfigError, FileExistsError, RuntimeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
