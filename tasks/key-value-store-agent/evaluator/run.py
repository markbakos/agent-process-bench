from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path


def load_store(workspace: Path):
    path = workspace / "src" / "kvstore.py"
    spec = importlib.util.spec_from_file_location("evaluated_kvstore", path)
    if not spec or not spec.loader:
        raise ImportError(f"Cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.Store


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--round", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    checks: list[bool] = []
    try:
        index = int(args.round.removeprefix("r"))
        Store = load_store(args.workspace)

        store = Store()
        store.set("answer", 41)
        store.set("answer", 42)
        checks.extend((store.get("answer") == 42, store.get("missing") is None))

        if index >= 1:
            store.set("nullable", None)
            checks.extend(
                (
                    store.delete("nullable") is True,
                    store.delete("nullable") is False,
                    store.get("nullable") is None,
                )
            )

        if index == 2:
            folded = Store()
            folded.set("Straße", 1)
            strict = Store(case_sensitive=True)
            strict.set("A", 2)
            checks.extend((folded.get("STRASSE") == 1, strict.get("a") is None))

        if index >= 3:
            strict = Store()
            strict.set("A", 1)
            folded = Store(case_sensitive=False)
            folded.set("Straße", 2)
            checks.extend((strict.get("a") is None, folded.get("STRASSE") == 2))

        status = "ok"
        build_status = "passed"
    except Exception as exc:
        checks.append(False)
        status = "error"
        build_status = "failed"
        error = str(exc)

    result = {
        "status": status,
        "tests_passed": sum(checks),
        "tests_total": len(checks),
        "build_status": build_status,
    }
    if status == "error":
        result["error"] = error
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
