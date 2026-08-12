from __future__ import annotations

import fnmatch
import json
import os
import shutil
import signal
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from .artifacts import atomic_write_json, atomic_write_text
from .engines import EngineInfrastructureError
from .models import EngineRunResult, ModelProfile, UsageSummary


SECRET_PATTERNS = (
    "OPENAI_API_KEY",
    "CODEX_API_KEY",
    "*_TOKEN",
    "*_SECRET",
    "*_PASSWORD",
    "*_PRIVATE_KEY",
    "*_ACCESS_KEY",
)
ENV_ALLOWLIST = {
    "ALL_PROXY",
    "CODEX_HOME",
    "COMSPEC",
    "CURL_CA_BUNDLE",
    "HOME",
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "LANG",
    "LANGUAGE",
    "LD_LIBRARY_PATH",
    "LOGNAME",
    "NO_PROXY",
    "PATH",
    "PATHEXT",
    "REQUESTS_CA_BUNDLE",
    "SHELL",
    "SSL_CERT_DIR",
    "SSL_CERT_FILE",
    "SYSTEMROOT",
    "TEMP",
    "TERM",
    "TMP",
    "TMPDIR",
    "TZ",
    "USER",
    "WINDIR",
    "XDG_CACHE_HOME",
    "XDG_CONFIG_HOME",
}
REQUIRED_EXEC_FLAGS = (
    "--json",
    "--ephemeral",
    "--ignore-user-config",
    "--ignore-rules",
    "--strict-config",
)


@dataclass(frozen=True)
class CodexTelemetry:
    usage: UsageSummary
    final_status: str | None
    warnings: list[str]
    errors: list[str]


def _toml_string(value: str) -> str:
    return json.dumps(value)


def codex_config_overrides(workspace: Path, profile: ModelProfile) -> list[str]:
    return [
        f"model_reasoning_effort={_toml_string(profile.reasoning_effort)}",
        'approval_policy="never"',
        'web_search="disabled"',
        'personality="none"',
        "agents.enabled=false",
        "apps._default.enabled=false",
        "features.plugins=false",
        "memories.use_memories=false",
        "memories.generate_memories=false",
        "allow_login_shell=false",
        "analytics.enabled=false",
        f"sandbox_workspace_write.network_access={str(profile.network_access).lower()}",
        "project_doc_max_bytes=0",
        "project_doc_fallback_filenames=[]",
        'shell_environment_policy.inherit="core"',
        "shell_environment_policy.ignore_default_excludes=false",
        'shell_environment_policy.exclude=["OPENAI_API_KEY","CODEX_API_KEY","*_TOKEN","*_SECRET"]',
    ]


def build_codex_args(workspace: Path, profile: ModelProfile, executable: str = "codex") -> list[str]:
    args = [
        executable,
        "exec",
        "--json",
        "--ephemeral",
        "--ignore-user-config",
        "--ignore-rules",
        "--strict-config",
        "--model",
        profile.model,
        "--sandbox",
        profile.sandbox,
        "--color",
        "never",
        "-C",
        str(workspace.resolve()),
    ]
    for override in codex_config_overrides(workspace, profile):
        args.extend(("-c", override))
    return [*args, "-"]


def filtered_environment(source: Mapping[str, str] | None = None) -> tuple[dict[str, str], list[str]]:
    source = os.environ if source is None else source
    environment: dict[str, str] = {}
    removed: list[str] = []
    for name, value in source.items():
        upper = name.upper()
        if (
            any(fnmatch.fnmatchcase(upper, pattern) for pattern in SECRET_PATTERNS)
            or upper not in ENV_ALLOWLIST
            and not upper.startswith("LC_")
        ):
            removed.append(name)
        else:
            environment[name] = value
    return environment, sorted(removed)


def resolve_codex(executable: str = "codex") -> str:
    resolved = shutil.which(executable)
    if not resolved:
        raise EngineInfrastructureError(f"Codex executable does not exist: {executable}")
    return resolved


def codex_version(executable: str = "codex") -> str:
    resolved = resolve_codex(executable)
    environment, _ = filtered_environment()
    completed = subprocess.run(
        [resolved, "--version"], text=True, capture_output=True, env=environment, check=False
    )
    if completed.returncode or not completed.stdout.strip():
        raise EngineInfrastructureError(
            f"Cannot read Codex version from '{resolved}': {completed.stderr.strip()}"
        )
    return completed.stdout.strip()


def validate_codex_profile(profile: ModelProfile, executable: str = "codex") -> str:
    if profile.sandbox != "workspace-write":
        raise ValueError("Codex model profiles must use sandbox: workspace-write")
    if profile.network_access:
        raise ValueError("Codex model profiles must disable network access")
    resolved = resolve_codex(executable)
    environment, _ = filtered_environment()
    completed = subprocess.run(
        [resolved, "exec", "--help"], text=True, capture_output=True, env=environment, check=False
    )
    if completed.returncode:
        raise EngineInfrastructureError(f"Cannot inspect Codex exec options: {completed.stderr.strip()}")
    missing = [flag for flag in REQUIRED_EXEC_FLAGS if flag not in completed.stdout]
    if missing:
        raise EngineInfrastructureError(
            f"Installed Codex does not support required options: {', '.join(missing)}"
        )
    probe = build_codex_args(Path.cwd(), profile, resolved)
    probe[-1] = "--version"
    rendered = subprocess.run(
        probe,
        text=True,
        capture_output=True,
        env=environment,
        check=False,
    )
    if rendered.returncode:
        raise EngineInfrastructureError(
            f"Codex rejected the configured execution controls: {rendered.stderr.strip()}"
        )
    return codex_version(resolved)


def parse_codex_jsonl(path: Path) -> CodexTelemetry:
    warnings: list[str] = []
    errors: list[str] = []
    usage_values: dict[str, int] = {}
    command_ids: set[str] = set()
    file_change_ids: set[str] = set()
    turn_count = 0
    final_status: str | None = None
    with path.open("rb") as handle:
        for line_number, raw_line in enumerate(handle, 1):
            if not raw_line.strip():
                warnings.append(f"line {line_number}: blank event")
                continue
            try:
                event = json.loads(raw_line)
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                warnings.append(f"line {line_number}: {exc}")
                continue
            if not isinstance(event, dict):
                warnings.append(f"line {line_number}: event is not an object")
                continue
            event_type = event.get("type")
            if event_type == "turn.started":
                turn_count += 1
            if event_type in {"turn.completed", "turn.failed"}:
                final_status = "completed" if event_type == "turn.completed" else "failed"
                raw_usage = event.get("usage")
                if isinstance(raw_usage, dict):
                    for key in (
                        "input_tokens",
                        "cached_input_tokens",
                        "output_tokens",
                        "reasoning_output_tokens",
                    ):
                        value = raw_usage.get(key)
                        if isinstance(value, int) and value >= 0:
                            usage_values[key] = value
            elif event_type == "error":
                final_status = "failed"

            if event_type in {"error", "turn.failed"}:
                raw_error = event.get("error", event.get("message"))
                if isinstance(raw_error, dict):
                    raw_error = raw_error.get("message", raw_error)
                if raw_error is not None:
                    errors.append(str(raw_error))

            item = event.get("item")
            if isinstance(item, dict):
                item_type = item.get("type")
                item_id = str(item.get("id") or f"line-{line_number}")
                if item_type == "command_execution":
                    command_ids.add(item_id)
                elif item_type in {"file_change", "file_changes"}:
                    file_change_ids.add(item_id)

    if turn_count and final_status is None:
        warnings.append("stream ended without a terminal turn event")
    elif not turn_count:
        warnings.append("stream contains no turn.started event")

    usage = UsageSummary(
        **usage_values,
        model_calls=turn_count or None,
        command_count=len(command_ids),
        file_change_event_count=len(file_change_ids),
    )
    return CodexTelemetry(usage=usage, final_status=final_status, warnings=warnings, errors=errors)


class CodexEngine:
    def __init__(self, executable: str = "codex", termination_grace_seconds: float = 5.0) -> None:
        self.executable = resolve_codex(executable)
        self.termination_grace_seconds = termination_grace_seconds

    def run(
        self,
        workspace: Path,
        prompt: str,
        model: ModelProfile,
        output_dir: Path,
    ) -> EngineRunResult:
        output_dir.mkdir(parents=True, exist_ok=True)
        args = build_codex_args(workspace, model, self.executable)
        environment, removed = filtered_environment()
        atomic_write_json(output_dir / "codex-command.json", {"args": args})
        atomic_write_json(
            output_dir / "codex-environment.json",
            {
                "passed_variable_names": sorted(environment),
                "removed_variable_names": removed,
                "child_shell_policy": "core environment with secret-name exclusions",
            },
        )
        atomic_write_text(output_dir / "codex-version.txt", codex_version(self.executable) + "\n")
        events_path = output_dir / "codex-events.jsonl"
        stderr_path = output_dir / "codex-stderr.log"
        started = time.monotonic()
        timed_out = False
        try:
            with events_path.open("wb") as stdout, stderr_path.open("wb") as stderr:
                process = subprocess.Popen(
                    args,
                    stdin=subprocess.PIPE,
                    stdout=stdout,
                    stderr=stderr,
                    cwd=workspace,
                    env=environment,
                    start_new_session=os.name == "posix",
                )
                try:
                    process.communicate(prompt.encode(), timeout=model.timeout_seconds)
                except subprocess.TimeoutExpired:
                    timed_out = True
                    self._signal(process, signal.SIGTERM)
                    try:
                        process.communicate(timeout=self.termination_grace_seconds)
                    except subprocess.TimeoutExpired:
                        self._signal(process, signal.SIGKILL)
                        process.communicate()
        except OSError as exc:
            raise EngineInfrastructureError(f"Cannot launch Codex: {exc}") from exc

        telemetry = parse_codex_jsonl(events_path)
        if telemetry.warnings:
            atomic_write_json(output_dir / "parser-warnings.json", {"warnings": telemetry.warnings})
        if not timed_out and process.returncode:
            stderr_text = stderr_path.read_text(encoding="utf-8", errors="replace").strip()
            failure_text = " ".join([*telemetry.errors, stderr_text]).lower()
            infrastructure_terms = (
                "api key",
                "access token",
                "authentication",
                "unauthorized",
                "forbidden",
                "log in",
                "login",
                "invalid config",
                "configuration error",
                "unknown model",
                "model is not supported",
                "model is not available",
            )
            if telemetry.usage.model_calls is None or any(
                term in failure_text for term in infrastructure_terms
            ):
                detail = "; ".join([*telemetry.errors, stderr_text]).strip("; ") or "no error detail"
                raise EngineInfrastructureError(
                    f"Codex failed before a usable turn (exit {process.returncode}): {detail[-1000:]}"
                )
        termination_reason = (
            "timeout"
            if timed_out
            else "completed"
            if process.returncode == 0 and telemetry.final_status == "completed"
            else "engine_error"
        )
        return EngineRunResult(
            exit_code=process.returncode,
            timed_out=timed_out,
            termination_reason=termination_reason,
            wall_time_seconds=time.monotonic() - started,
            usage=telemetry.usage,
            final_status=telemetry.final_status,
        )

    @staticmethod
    def _signal(process: subprocess.Popen, value: signal.Signals) -> None:
        if process.poll() is not None:
            return
        try:
            if os.name == "posix":
                os.killpg(process.pid, value)
            elif value == signal.SIGTERM:
                process.terminate()
            else:
                process.kill()
        except ProcessLookupError:
            pass
