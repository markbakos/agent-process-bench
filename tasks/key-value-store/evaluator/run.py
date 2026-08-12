from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--round", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    index = int(args.round.removeprefix("r"))
    tests: list[bool] = []
    try:
        module_path = args.workspace / "src" / "kvstore.py"
        spec = importlib.util.spec_from_file_location("smoke_kvstore", module_path)
        module = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        spec.loader.exec_module(module)
        store = module.Store()
        store.set("A", 1)
        tests.append(store.get("A") == 1)
        if index >= 1:
            tests.append(store.delete("A") and store.get("A") is None)
        if index >= 2:
            folded = module.Store(case_sensitive=False)
            folded.set("A", 1)
            tests.append(folded.get("a") == 1)
        if index >= 3:
            strict = module.Store()
            strict.set("A", 1)
            tests.append(strict.get("a") is None)
        trace = [
            line
            for line in (args.workspace / "fake_output.txt").read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        tests.append(len(trace) == index + 1)
        build_status = "passed"
        status = "ok"
    except Exception as exc:
        tests.append(False)
        build_status = "failed"
        status = "error"
        error = str(exc)
    result = {
        "status": status,
        "tests_passed": sum(tests),
        "tests_total": len(tests),
        "build_status": build_status,
    }
    if status == "error":
        result["error"] = error
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
