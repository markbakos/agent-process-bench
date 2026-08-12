# Run the key-value-store task across every process

This runbook has two distinct checks:

1. Run the existing `key-value-store` fixture with `FakeEngine` to prove all four process configurations complete the framework lifecycle.
2. Generate an agent-ready copy of the task and run it with Codex to observe how each development process behaves.

Do not use the existing fixture for the behavioral comparison. Its starter already contains later-round behavior, its evaluator expects `FakeEngine` trace output, and `FakeEngine` does not follow process instructions.

Run every command from the repository root.

## 1. Validate the existing task

```bash
.venv/bin/python -m apbench validate-task tasks/key-value-store --references
```

Expected result: all four reference checkpoints pass and the command reports that the task is valid. A warning about the final conflict round is expected and should remain visible.

## 2. Smoke-test all process configurations

Create `experiments/key-value-store-process-smoke.yaml`:

```yaml
schema_version: 1
id: key-value-store-process-smoke
model_profile: fake
agent_profile: standard
processes:
  - direct
  - tdd
  - iterative
  - plan-driven
tasks:
  - key-value-store
replicates: 1
execution:
  fresh_context_per_round: true
  preserve_git_history: false
  randomize_run_order: true
  random_seed: 20260812
  timeout_seconds: 30
measurements:
  correctness: true
  repository_stats: true
  structural_erosion: true
  maintenance_probe: false
```

Validate and preview the run:

```bash
.venv/bin/python -m apbench validate experiments/key-value-store-process-smoke.yaml
.venv/bin/python -m apbench plan experiments/key-value-store-process-smoke.yaml
```

Run and evaluate it:

```bash
.venv/bin/python -m apbench run experiments/key-value-store-process-smoke.yaml --allow-dirty-framework
.venv/bin/python -m apbench evaluate experiments/key-value-store-process-smoke.yaml
.venv/bin/python -m apbench aggregate experiments/key-value-store-process-smoke.yaml
.venv/bin/python -m apbench status experiments/key-value-store-process-smoke.yaml
```

This pilot should report four trajectories, sixteen completed rounds, and sixteen correctness evaluations. It proves selection, prompt assembly, checkpoint chaining, hidden evaluation, and aggregation for every process. It does **not** compare process behavior: `FakeEngine` performs the same deterministic action for each process.

Use `--allow-dirty-framework` only for this local smoke check. Use a clean committed checkout for a real comparison.

## 3. Generate the agent-ready task with the skill

Keep `tasks/key-value-store` unchanged because the framework integration tests depend on its FakeEngine behavior. Ask an agent to create a separate task with this prompt:

```text
Use $create-apbench-task to create tasks/key-value-store-agent as an agent-process comparison version of tasks/key-value-store.

Reuse the existing four round requirements and change types. The starter must contain only the initial project scaffold and visible offline test tooling; it must not contain behavior requested by any round. Replace the FakeEngine-specific trace assertion with deterministic cumulative behavioral checks. Create a complete passing reference workspace for every round. Do not change the runner, process packs, existing key-value-store task, or smoke experiment.
```

Review the generated task before running it:

- `starter/` does not implement current or future requirements;
- every round has one requirement and one reference directory;
- the hidden evaluator checks all behavior required through the selected round;
- references pass, while a deliberately broken workspace fails;
- no requirement, evaluator, reference, or experiment control file is exposed in `starter/`.

Then validate it:

```bash
.venv/bin/python -m apbench validate-task tasks/key-value-store-agent --references
```

Do not continue until this command passes.

## 4. Configure the real four-process comparison

Create `experiments/key-value-store-processes.yaml`:

```yaml
schema_version: 1
id: key-value-store-processes
model_profile: terra-medium
agent_profile: standard
processes:
  - direct
  - tdd
  - iterative
  - plan-driven
tasks:
  - key-value-store-agent
replicates: 1
execution:
  fresh_context_per_round: true
  preserve_git_history: false
  randomize_run_order: true
  random_seed: 20260812
  timeout_seconds: 1800
measurements:
  correctness: true
  repository_stats: true
  structural_erosion: true
  maintenance_probe: false
```

This is one exploratory replicate: four processes multiplied by four rounds equals sixteen paid Codex rounds. Maintenance is omitted so it does not add unrelated model runs.

Commit the task, experiment manifest, skill, and framework changes before the real run. Confirm that the checkout is clean:

```bash
git status --short
```

The command must print nothing.

Validate and lock the randomized plan:

```bash
.venv/bin/python -m apbench validate experiments/key-value-store-processes.yaml
.venv/bin/python -m apbench plan experiments/key-value-store-processes.yaml
```

Read `runs/key-value-store-processes/execution-plan.json` before continuing. The plan is immutable for this experiment ID.

## 5. Run, resume, and evaluate

Start all four trajectories:

```bash
.venv/bin/python -m apbench run experiments/key-value-store-processes.yaml
```

If execution is interrupted, resume completed work instead of paying to repeat it:

```bash
.venv/bin/python -m apbench run experiments/key-value-store-processes.yaml --resume
```

Do not use `--force` unless a new attempt is intentional; it creates additional paid attempts while preserving the old ones.

Evaluate frozen checkpoints, aggregate the results, and print completion counts:

```bash
.venv/bin/python -m apbench evaluate experiments/key-value-store-processes.yaml
.venv/bin/python -m apbench aggregate experiments/key-value-store-processes.yaml
.venv/bin/python -m apbench status experiments/key-value-store-processes.yaml
```

Expected completed-run counts are four trajectories, sixteen rounds, and sixteen correctness evaluations.

## 6. Inspect how each process worked

The comparable result table is:

```text
runs/key-value-store-processes/results/master.csv
```

Print the main per-round fields:

```bash
.venv/bin/python -c 'import pandas as pd; p="runs/key-value-store-processes/results/master.csv"; print(pd.read_csv(p)[["process_id","round_id","correct","tests_passed","tests_total","production_loc","test_loc","structural_erosion","input_tokens","output_tokens","wall_time_seconds","command_count","file_change_event_count"]].to_string(index=False))'
```

For each process and round, inspect:

```text
runs/key-value-store-processes/trajectories/key-value-store-agent/<process>/rep-001/round-<index>/attempt-001/
├── prompt.txt
├── execution.json
├── usage.json
├── correctness-v1.json
├── repository-stats-v1.json
├── structural-erosion-python-v1.json
├── checkpoint.tar.gz
└── engine/
    ├── codex-events.jsonl
    └── codex-stderr.log
```

Check the evidence against each treatment:

| Process | Expected observable behavior |
| --- | --- |
| `direct` | No prescribed planning or test sequence; the agent chooses its approach. |
| `tdd` | Visible tests are written or changed first, run red, followed by the smallest production change and a green run. |
| `iterative` | Production changes are split into small increments, with a check and review after each increment. |
| `plan-driven` | `DEVELOPMENT_PLAN.md` is written before production changes, implementation occurs as one phase, and verification follows as a distinct phase. |

Use `prompt.txt` to confirm the assigned treatment, `codex-events.jsonl` to check action order, the checkpoint to inspect resulting code and artifacts, and `master.csv` to compare outcomes and cost. Correctness alone does not prove that the assigned process was followed.

With one task and one replicate, treat results as a workflow rehearsal, not evidence that one process is better.
