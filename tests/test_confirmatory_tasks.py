from pathlib import Path

import pytest

from apbench.config import load_task_manifest
from apbench.evaluation import correctness, validate_references


ROOT = Path(__file__).parents[1]
MATRIX = {
    "order-pricing-engine": "CRERCE",
    "appointment-scheduler": "CERECR",
    "inventory-reservation": "ECRCRE",
    "subscription-billing": "RECRCE",
    "support-sla-router": "ERCERC",
    "shipping-quote-service": "ECRERC",
    "document-approval-workflow": "CRECER",
    "feature-flag-evaluator": "ERCREC",
    "retry-job-scheduler": "RECERC",
    "expense-reimbursement": "RCECER",
}


@pytest.mark.parametrize(("task_id", "sequence"), MATRIX.items())
def test_confirmatory_task_pack(task_id: str, sequence: str, tmp_path: Path) -> None:
    task = load_task_manifest(ROOT / "tasks" / task_id / "task.yaml")
    assert [item.id for item in task.rounds] == [f"r{index:02}" for index in range(7)]
    assert "".join(item.change_type[0].upper() for item in task.rounds[1:]) == sequence
    validate_references(task)

    starter = correctness(task.root / "starter", task, task.rounds[0], tmp_path / "starter")
    assert not starter["correct"]
    for index, round_spec in enumerate(task.rounds[1:], 1):
        previous = task.root / "reference" / task.rounds[index - 1].id
        assert not correctness(previous, task, round_spec, tmp_path / round_spec.id)["correct"]


def test_change_types_are_balanced_by_depth() -> None:
    expected = {
        1: {"extension": 4, "revision": 3, "conflict": 3},
        2: {"extension": 3, "revision": 4, "conflict": 3},
        3: {"extension": 3, "revision": 3, "conflict": 4},
        4: {"extension": 4, "revision": 3, "conflict": 3},
        5: {"extension": 3, "revision": 4, "conflict": 3},
        6: {"extension": 3, "revision": 3, "conflict": 4},
    }
    tasks = [load_task_manifest(ROOT / "tasks" / task_id / "task.yaml") for task_id in MATRIX]
    for depth, counts in expected.items():
        assert {kind: sum(task.rounds[depth].change_type == kind for task in tasks) for kind in counts} == counts
