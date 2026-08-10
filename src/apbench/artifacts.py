from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tarfile
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any, Iterable


EXCLUDED_PARTS = {".git", "__pycache__", ".pytest_cache"}
REQUIRED_ATTEMPT_FILES = {
    "round-manifest.json",
    "status.json",
    "prompt.txt",
    "prompt.sha256",
    "requirement.md",
    "resolved-config.json",
    "execution.json",
    "usage.json",
    "checkpoint.tar.gz",
    "checkpoint-tree.sha256",
}


def atomic_write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def atomic_write_json(path: Path, value: Any) -> None:
    atomic_write_text(path, json.dumps(value, indent=2, sort_keys=True, default=str) + "\n")


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected JSON object in {path}")
    return value


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def included_files(root: Path) -> Iterable[Path]:
    for path in sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix()):
        relative = path.relative_to(root)
        if any(part in EXCLUDED_PARTS for part in relative.parts):
            continue
        if path.is_file() and not path.is_symlink():
            yield path


def tree_hash(root: Path) -> str:
    digest = hashlib.sha256()
    for path in included_files(root):
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def copy_tree(source: Path, destination: Path) -> None:
    def ignored(_directory: str, names: list[str]) -> set[str]:
        return set(names) & EXCLUDED_PARTS

    shutil.copytree(source, destination, ignore=ignored, symlinks=False)


def create_checkpoint(workspace: Path, destination: Path) -> str:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.tmp")
    temporary.unlink(missing_ok=True)
    try:
        with tarfile.open(temporary, "w:gz") as archive:
            for path in included_files(workspace):
                info = archive.gettarinfo(str(path), path.relative_to(workspace).as_posix())
                info.uid = info.gid = 0
                info.uname = info.gname = ""
                info.mtime = 0
                with path.open("rb") as handle:
                    archive.addfile(info, handle)
        os.replace(temporary, destination)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    return tree_hash(workspace)


def extract_checkpoint(archive_path: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=False)
    try:
        with tarfile.open(archive_path, "r:gz") as archive:
            for member in archive.getmembers():
                name = PurePosixPath(member.name)
                if name.is_absolute() or ".." in name.parts or member.issym() or member.islnk():
                    raise ValueError(f"Unsafe checkpoint member: {member.name}")
            archive.extractall(destination, filter="data")
    except BaseException:
        shutil.rmtree(destination, ignore_errors=True)
        raise


def initialize_git(workspace: Path) -> None:
    commands = [
        ["git", "init", "-q"],
        ["git", "config", "user.name", "apbench"],
        ["git", "config", "user.email", "apbench@invalid.local"],
        ["git", "add", "."],
        ["git", "commit", "-q", "--allow-empty", "-m", "baseline"],
    ]
    for command in commands:
        result = subprocess.run(command, cwd=workspace, text=True, capture_output=True, check=False)
        if result.returncode:
            raise RuntimeError(f"Git command failed ({' '.join(command)}): {result.stderr.strip()}")


def selected_attempt(round_dir: Path) -> Path | None:
    pointer = round_dir / "selected-attempt.json"
    if not pointer.is_file():
        return None
    name = read_json(pointer).get("attempt")
    attempt = round_dir / str(name)
    return attempt if attempt.is_dir() else None


def attempt_complete(attempt: Path) -> bool:
    try:
        return (
            read_json(attempt / "status.json").get("state") == "completed"
            and all((attempt / name).is_file() for name in REQUIRED_ATTEMPT_FILES)
        )
    except (OSError, ValueError, json.JSONDecodeError):
        return False


def next_attempt(round_dir: Path) -> Path:
    numbers = []
    for path in round_dir.glob("attempt-*"):
        try:
            numbers.append(int(path.name.removeprefix("attempt-")))
        except ValueError:
            continue
    return round_dir / f"attempt-{max(numbers, default=0) + 1:03d}"


def quarantine_incomplete(round_dir: Path) -> list[Path]:
    moved: list[Path] = []
    quarantine = round_dir / "quarantine"
    for attempt in sorted(round_dir.glob("attempt-*")):
        if not attempt_complete(attempt):
            quarantine.mkdir(parents=True, exist_ok=True)
            destination = quarantine / attempt.name
            suffix = 1
            while destination.exists():
                destination = quarantine / f"{attempt.name}-{suffix}"
                suffix += 1
            shutil.move(str(attempt), destination)
            moved.append(destination)
    pointer = round_dir / "selected-attempt.json"
    selected = selected_attempt(round_dir)
    if pointer.exists() and (selected is None or not attempt_complete(selected)):
        pointer.unlink()
    return moved


def maintenance_key(attempt: Path) -> str:
    round_key = read_json(attempt / "round-manifest.json")["round_key"]
    checkpoint_hash = (attempt / "checkpoint-tree.sha256").read_text(encoding="utf-8").strip()
    return f"{round_key}__{checkpoint_hash[:16]}"
