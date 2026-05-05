#!/usr/bin/env python3
"""Hermes-native Symphony runtime.

This is a local, file-backed orchestration layer inspired by OpenAI Symphony's
SPEC. It intentionally keeps v1 small enough to audit while preserving the
important boundaries: task contracts, isolated workspaces, worker dispatch,
validation, and proof-of-work handoff.
"""

from __future__ import annotations

import argparse
import contextlib
import dataclasses
import fnmatch
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

try:
    import fcntl
except ImportError:  # pragma: no cover - non-POSIX fallback
    fcntl = None

try:
    import yaml  # type: ignore
except Exception:  # pragma: no cover - exercised only when PyYAML is absent
    yaml = None


VERSION = "0.2.0"
TASK_STATES = {"new", "claimed", "running", "needs_review", "done", "failed", "blocked", "retry"}
WORKER_TYPES = {"codex_once", "codex_autoresearch", "codex_review", "shell"}
METRIC_PARSERS = {"failing_tests", "grep_count", "numeric_stdout", "exit_code"}
METRIC_DIRECTIONS = {"lower", "higher"}
QUEUE_DIRS = {
    "new": "inbox",
    "claimed": "active",
    "running": "active",
    "retry": "active",
    "blocked": "blocked",
    "needs_review": "review",
    "done": "done",
    "failed": "failed",
}
REQUIRED_FIELDS = {
    "task_id",
    "title",
    "repo_path",
    "goal",
    "background",
    "acceptance_criteria",
    "allowed_scope",
    "forbidden_paths",
    "forbidden_patterns",
    "verify_command",
    "guard_command",
    "worker_type",
    "worker_command",
    "max_attempts",
    "current_attempt",
    "status",
    "created_at",
    "updated_at",
}
DEFAULT_FORBIDDEN_PATTERNS = [
    "private_key",
    "API_SECRET",
]
DEFAULT_FORBIDDEN_PATHS = [
    ".env",
    ".env.*",
    "*secret*",
    "*secrets*",
    "*wallet*",
    "*private*key*",
    "*.key",
    "*.pem",
]
TRADING_FORBIDDEN_PATTERNS = [
    "EXECUTION_ENABLED=true",
    "LIVE_TRADING=true",
    "place_order(",
    "submit_order(",
    "send_order(",
    "real_money",
    "private_key",
]
TRADING_FORBIDDEN_PATHS = [
    ".env",
    ".env.*",
    "*secret*",
    "*secrets*",
    "*wallet*",
    "*private*key*",
    "*broker*credential*",
    "*credentials*",
]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def safe_task_id(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", value)


def load_structured(path: Path) -> dict[str, Any]:
    text = path.read_text()
    if path.suffix.lower() == ".json":
        data = json.loads(text)
    else:
        if yaml is None:
            raise RuntimeError("PyYAML is required for YAML task files; use JSON or install PyYAML")
        data = yaml.safe_load(text)
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain an object")
    return data


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(text)
    os.replace(tmp, path)


def dump_structured(path: Path, data: dict[str, Any]) -> None:
    if path.suffix.lower() == ".json" or yaml is None:
        atomic_write_text(path, json.dumps(data, indent=2, sort_keys=True) + "\n")
    else:
        atomic_write_text(path, yaml.safe_dump(data, sort_keys=False))


def run_command(command: str, cwd: Path, timeout: int | None = None) -> dict[str, Any]:
    started = time.time()
    try:
        proc = subprocess.run(
            command,
            cwd=str(cwd),
            shell=True,
            text=True,
            capture_output=True,
            timeout=timeout,
        )
        return {
            "command": command,
            "cwd": str(cwd),
            "returncode": proc.returncode,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
            "duration_seconds": round(time.time() - started, 3),
            "timed_out": False,
        }
    except subprocess.TimeoutExpired as error:
        return {
            "command": command,
            "cwd": str(cwd),
            "returncode": 124,
            "stdout": error.stdout or "",
            "stderr": error.stderr or f"command timed out after {timeout} seconds",
            "duration_seconds": round(time.time() - started, 3),
            "timed_out": True,
        }


class QueueLock:
    def __init__(self, path: Path):
        self.path = path
        self.handle = None

    def __enter__(self) -> "QueueLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.handle = self.path.open("a+")
        if fcntl is not None:
            fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX)
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        if self.handle is not None:
            if fcntl is not None:
                fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
            self.handle.close()


@dataclasses.dataclass
class TaskContract:
    data: dict[str, Any]

    @classmethod
    def load(cls, path: Path) -> "TaskContract":
        return cls(load_structured(path)).validate()

    def validate(self) -> "TaskContract":
        self._normalize_worker_config()
        missing = sorted(REQUIRED_FIELDS - self.data.keys())
        if missing:
            raise ValueError(f"task contract missing required fields: {', '.join(missing)}")
        if self.status not in TASK_STATES:
            raise ValueError(f"invalid task status {self.status!r}")
        if self.worker_type not in WORKER_TYPES:
            raise ValueError(f"invalid worker.type {self.worker_type!r}")
        if not isinstance(self.data["allowed_scope"], list):
            raise ValueError("allowed_scope must be a list")
        if not isinstance(self.data["forbidden_paths"], list):
            raise ValueError("forbidden_paths must be a list")
        if not isinstance(self.data["forbidden_patterns"], list):
            raise ValueError("forbidden_patterns must be a list")
        self.data["forbidden_paths"] = sorted(set(self.data["forbidden_paths"] + DEFAULT_FORBIDDEN_PATHS))
        self.data["forbidden_patterns"] = sorted(set(self.data["forbidden_patterns"] + DEFAULT_FORBIDDEN_PATTERNS))
        if int(self.data["max_attempts"]) < 1:
            raise ValueError("max_attempts must be >= 1")
        if int(self.data["current_attempt"]) < 0:
            raise ValueError("current_attempt must be >= 0")
        if self.safety_profile == "trading":
            self.data["forbidden_paths"] = sorted(set(self.data["forbidden_paths"] + TRADING_FORBIDDEN_PATHS))
            self.data["forbidden_patterns"] = sorted(
                set(self.data["forbidden_patterns"] + TRADING_FORBIDDEN_PATTERNS)
            )
        if self.worker_type == "codex_autoresearch":
            self._validate_autoresearch_contract()
        return self

    def _normalize_worker_config(self) -> None:
        worker = self.data.get("worker")
        if worker is None:
            legacy_type = str(self.data.get("worker_type", "codex_once"))
            if legacy_type == "codex":
                legacy_type = "codex_once"
            worker = {
                "type": legacy_type,
                "command": self.data.get("worker_command", "codex"),
                "timeout_seconds": self.data.get("worker_timeout_seconds", 900),
            }
            self.data["worker"] = worker
        if not isinstance(worker, dict):
            raise ValueError("worker must be an object")
        worker.setdefault("type", "codex_once")
        worker.setdefault("command", "codex")
        worker.setdefault("timeout_seconds", 900)
        if worker["type"] == "codex":
            worker["type"] = "codex_once"
        self.data["worker_type"] = str(worker["type"])
        self.data["worker_command"] = str(worker["command"])
        self.data["worker_timeout_seconds"] = int(worker["timeout_seconds"])

    def _validate_autoresearch_contract(self) -> None:
        metric = self.data.get("metric")
        autoresearch = self.data.get("autoresearch")
        if not isinstance(metric, dict):
            raise ValueError("codex_autoresearch worker requires metric object")
        if not isinstance(autoresearch, dict):
            raise ValueError("codex_autoresearch worker requires autoresearch object")
        for field in ["name", "command", "parser", "direction"]:
            if not metric.get(field):
                raise ValueError(f"metric.{field} is required for codex_autoresearch")
        if metric["parser"] not in METRIC_PARSERS:
            raise ValueError(f"metric.parser must be one of {sorted(METRIC_PARSERS)}")
        if metric["direction"] not in METRIC_DIRECTIONS:
            raise ValueError("metric.direction must be lower or higher")
        if not self.data.get("verify_command"):
            raise ValueError("verify_command is required for codex_autoresearch")
        if not self.data.get("guard_command"):
            raise ValueError("guard_command is required for codex_autoresearch")
        autoresearch.setdefault("max_iterations", 20)
        autoresearch.setdefault("mode", "foreground")
        autoresearch.setdefault("retain_policy", "improve_only")
        autoresearch.setdefault("results_dir", "autoresearch-results")
        if int(autoresearch["max_iterations"]) < 1:
            raise ValueError("autoresearch.max_iterations must be >= 1")
        if autoresearch["mode"] not in {"foreground", "background"}:
            raise ValueError("autoresearch.mode must be foreground or background")
        if autoresearch["retain_policy"] not in {"improve_only", "pass_guard"}:
            raise ValueError("autoresearch.retain_policy must be improve_only or pass_guard")

    @property
    def task_id(self) -> str:
        return str(self.data["task_id"])

    @property
    def status(self) -> str:
        return str(self.data["status"])

    @property
    def repo_path(self) -> Path:
        return Path(str(self.data["repo_path"])).expanduser().resolve()

    @property
    def safety_profile(self) -> str:
        return str(self.data.get("safety_profile", "")).lower()

    @property
    def workspace_mode(self) -> str:
        return str(self.data.get("workspace_mode", self.data.get("mode", "worktree"))).lower()

    @property
    def worker(self) -> dict[str, Any]:
        return self.data["worker"]

    @property
    def worker_type(self) -> str:
        return str(self.worker["type"])

    @property
    def worker_command(self) -> str:
        return str(self.worker["command"])

    @property
    def worker_timeout_seconds(self) -> int:
        return int(self.worker["timeout_seconds"])

    def mark(self, status: str) -> None:
        if status not in TASK_STATES:
            raise ValueError(f"invalid task status {status!r}")
        self.data["status"] = status
        self.data["updated_at"] = now_iso()


class LocalQueue:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.ensure()

    def ensure(self) -> None:
        for dirname in set(QUEUE_DIRS.values()) | {"tasks", "workspaces", "logs"}:
            (self.root / dirname).mkdir(parents=True, exist_ok=True)

    @contextlib.contextmanager
    def locked(self) -> Iterable[None]:
        with QueueLock(self.root / ".queue.lock"):
            yield

    def event(self, event: str, task_id: str | None = None, **fields: Any) -> None:
        payload = {"event": event, "task_id": task_id, "created_at": now_iso(), **fields}
        with (self.root / "logs" / "events.jsonl").open("a") as handle:
            handle.write(json.dumps(payload, sort_keys=True) + "\n")

    def task_artifact_dir(self, task_id: str) -> Path:
        path = self.root / "tasks" / safe_task_id(task_id)
        path.mkdir(parents=True, exist_ok=True)
        return path

    def queue_path(self, task: TaskContract) -> Path:
        return self.root / QUEUE_DIRS[task.status] / f"{safe_task_id(task.task_id)}.yaml"

    def enqueue(self, source: Path) -> Path:
        task = TaskContract.load(source)
        task.mark("new")
        target = self.queue_path(task)
        dump_structured(target, task.data)
        self.event("task_enqueued", task.task_id, path=str(target))
        return target

    def find_path(self, task_id: str) -> Path:
        name = f"{safe_task_id(task_id)}.yaml"
        for dirname in QUEUE_DIRS.values():
            candidate = self.root / dirname / name
            if candidate.exists():
                return candidate
        raise FileNotFoundError(f"task {task_id!r} not found in {self.root}")

    def load(self, task_id: str) -> tuple[TaskContract, Path]:
        path = self.find_path(task_id)
        return TaskContract.load(path), path

    def move(self, old_path: Path, task: TaskContract, status: str) -> Path:
        old_status = task.status
        task.mark(status)
        new_path = self.queue_path(task)
        if old_path.resolve() != new_path.resolve() and old_path.exists():
            old_path.unlink()
        dump_structured(new_path, task.data)
        self.event("task_moved", task.task_id, old_status=old_status, new_status=status, path=str(new_path))
        return new_path

    def next_inbox(self) -> tuple[TaskContract, Path] | None:
        for path in sorted((self.root / "inbox").glob("*.y*ml")) + sorted((self.root / "inbox").glob("*.json")):
            return TaskContract.load(path), path
        return None

    def status(self) -> dict[str, list[str]]:
        result: dict[str, list[str]] = {}
        for dirname in ["inbox", "active", "blocked", "review", "done", "failed"]:
            result[dirname] = sorted(path.stem for path in (self.root / dirname).glob("*.*"))
        return result


class WorkspaceManager:
    def __init__(self, queue: LocalQueue):
        self.queue = queue

    def workspace_for(self, task: TaskContract) -> Path:
        return (self.queue.root / "workspaces" / safe_task_id(task.task_id)).resolve()

    def prepare(self, task: TaskContract) -> Path:
        repo = task.repo_path
        workspace = self.workspace_for(task)
        if not repo.exists():
            raise FileNotFoundError(f"repo_path does not exist: {repo}")
        if workspace.exists():
            return workspace
        workspace.parent.mkdir(parents=True, exist_ok=True)
        mode = task.workspace_mode
        if self._is_git_repo(repo) and mode == "worktree":
            branch = safe_task_id(f"symphony/{task.task_id}")
            subprocess.run(["git", "worktree", "add", "-B", branch, str(workspace), "HEAD"], cwd=repo, check=True)
        elif self._is_git_repo(repo) and mode in {"isolated_clone", "clone", "branch"}:
            subprocess.run(["git", "clone", str(repo), str(workspace)], check=True)
            if mode == "branch":
                subprocess.run(["git", "checkout", "-B", safe_task_id(f"symphony/{task.task_id}")], cwd=workspace, check=True)
        else:
            ignore = shutil.ignore_patterns(".symphony*", ".git", "__pycache__", ".pytest_cache")
            shutil.copytree(repo, workspace, ignore=ignore)
        return workspace.resolve()

    @staticmethod
    def _is_git_repo(path: Path) -> bool:
        return subprocess.run(["git", "rev-parse", "--is-inside-work-tree"], cwd=path, capture_output=True).returncode == 0


class Snapshot:
    @staticmethod
    def collect(root: Path) -> dict[str, str]:
        result: dict[str, str] = {}
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            rel = path.relative_to(root).as_posix()
            if rel.startswith(".git/") or rel.startswith(".symphony/"):
                continue
            result[rel] = hashlib.sha256(path.read_bytes()).hexdigest()
        return result

    @staticmethod
    def changed(before: dict[str, str], after: dict[str, str]) -> list[str]:
        keys = set(before) | set(after)
        return sorted(path for path in keys if before.get(path) != after.get(path))


class MetricEvaluator:
    def __init__(self, task: TaskContract, workspace: Path):
        self.task = task
        self.workspace = workspace

    def configured(self) -> bool:
        return isinstance(self.task.data.get("metric"), dict)

    def measure(self, label: str) -> dict[str, Any] | None:
        if not self.configured():
            return None
        metric = self.task.data["metric"]
        command_result = run_command(str(metric["command"]), self.workspace)
        value = self.parse(command_result, str(metric["parser"]))
        return {
            "label": label,
            "name": metric["name"],
            "command": metric["command"],
            "parser": metric["parser"],
            "direction": metric["direction"],
            "target": metric.get("target"),
            "value": value,
            "command_result": command_result,
        }

    @staticmethod
    def parse(command_result: dict[str, Any], parser: str) -> float:
        stdout = str(command_result.get("stdout") or "")
        stderr = str(command_result.get("stderr") or "")
        combined = f"{stdout}\n{stderr}"
        if parser == "exit_code":
            return float(command_result["returncode"])
        if parser == "numeric_stdout":
            match = re.search(r"[-+]?(?:\d*\.\d+|\d+)", stdout.strip())
            if not match:
                raise ValueError("numeric_stdout parser could not find a number")
            return float(match.group(0))
        if parser == "grep_count":
            match = re.search(r"\d+", stdout.strip())
            if match:
                return float(match.group(0))
            return float(len([line for line in stdout.splitlines() if line.strip()]))
        if parser == "failing_tests":
            failed = re.findall(r"(\d+)\s+failed", combined)
            errors = re.findall(r"(\d+)\s+errors?", combined)
            if failed or errors:
                return float(sum(int(value) for value in failed + errors))
            if command_result["returncode"] == 0:
                return 0.0
            return 1.0
        raise ValueError(f"unsupported metric parser {parser!r}")

    @staticmethod
    def improved(baseline: dict[str, Any] | None, final: dict[str, Any] | None) -> bool | None:
        if baseline is None or final is None:
            return None
        if final["direction"] == "lower":
            return float(final["value"]) < float(baseline["value"])
        return float(final["value"]) > float(baseline["value"])

    @staticmethod
    def target_met(final: dict[str, Any] | None) -> bool | None:
        if final is None or final.get("target") is None:
            return None
        if final["direction"] == "lower":
            return float(final["value"]) <= float(final["target"])
        return float(final["value"]) >= float(final["target"])


class WorkerDispatcher:
    AUTORESEARCH_SKILL_PATHS = [
        Path.home() / ".codex" / "skills" / "codex-autoresearch" / "SKILL.md",
        Path.cwd() / ".agents" / "skills" / "codex-autoresearch" / "SKILL.md",
    ]

    def __init__(self, queue: LocalQueue):
        self.queue = queue

    def build_prompt(self, task: TaskContract, workspace: Path, mode: str | None = None) -> str:
        mode = mode or task.worker_type
        workflow = self._read_optional(workspace / "WORKFLOW.md")
        hermes_workflow = self._read_optional(workspace / "HERMES_WORKFLOW.md")
        if not hermes_workflow:
            hermes_workflow = self._read_optional(Path.cwd() / "HERMES_WORKFLOW.md")
        sections = [
            f"# Hermes Symphony {mode} Worker Prompt",
            "",
            "Work only inside this isolated workspace:",
            str(workspace),
            "",
            "Never read, write, or execute commands outside the task workspace.",
            "Respect allowed_scope, forbidden_paths, forbidden_patterns, and final Symphony validation.",
            "",
            "## Task Contract",
            json.dumps(task.data, indent=2, sort_keys=True),
            "",
        ]
        if mode == "codex_autoresearch":
            sections.extend(self._autoresearch_sections(task))
        elif mode == "codex_review":
            sections.extend(self._review_sections())
        else:
            sections.extend(self._once_sections())
        sections.extend(
            [
                "## Repository WORKFLOW.md",
                workflow or "No repository WORKFLOW.md found.",
                "",
                "## HERMES_WORKFLOW.md",
                hermes_workflow or "No HERMES_WORKFLOW.md found.",
            ]
        )
        return "\n".join(sections)

    def run(self, task: TaskContract, workspace: Path, mock: bool = False) -> dict[str, Any]:
        if task.worker_type == "codex_autoresearch":
            return self.run_autoresearch(task, workspace, mock=mock)
        if task.worker_type == "codex_review":
            return self.run_review(task, workspace, mock=mock)
        return self.run_once(task, workspace, mock=mock)

    def run_once(self, task: TaskContract, workspace: Path, mock: bool = False) -> dict[str, Any]:
        artifact_dir = self.queue.task_artifact_dir(task.task_id)
        prompt = self.build_prompt(task, workspace, "codex_once")
        atomic_write_text(artifact_dir / "worker_prompt.md", prompt)
        command = self._codex_exec_command(task.worker_command, artifact_dir / "worker_prompt.md", task.worker_type)
        if mock:
            command = "python -c \"from pathlib import Path; Path('MOCK_WORKER_RAN.txt').write_text('ok\\n')\""
        log = run_command(command, workspace, timeout=task.worker_timeout_seconds)
        log["mocked"] = mock
        log["worker_type"] = task.worker_type
        atomic_write_text(artifact_dir / "worker_log.json", json.dumps(log, indent=2, sort_keys=True) + "\n")
        atomic_write_text(artifact_dir / "worker.log", log["stdout"] + "\n" + log["stderr"])
        return log

    def run_review(self, task: TaskContract, workspace: Path, mock: bool = False) -> dict[str, Any]:
        artifact_dir = self.queue.task_artifact_dir(task.task_id)
        prompt = self.build_prompt(task, workspace, "codex_review")
        atomic_write_text(artifact_dir / "worker_prompt.md", prompt)
        command = self._codex_exec_command(task.worker_command, artifact_dir / "worker_prompt.md", task.worker_type)
        if mock:
            command = "python -c \"from pathlib import Path; Path('review-summary.md').write_text('review complete\\n')\""
        log = run_command(command, workspace, timeout=task.worker_timeout_seconds)
        log["mocked"] = mock
        log["worker_type"] = "codex_review"
        atomic_write_text(artifact_dir / "worker_log.json", json.dumps(log, indent=2, sort_keys=True) + "\n")
        atomic_write_text(artifact_dir / "worker.log", log["stdout"] + "\n" + log["stderr"])
        return log

    def run_autoresearch(self, task: TaskContract, workspace: Path, mock: bool = False) -> dict[str, Any]:
        artifact_dir = self.queue.task_artifact_dir(task.task_id)
        prompt = self.build_prompt(task, workspace, "codex_autoresearch")
        atomic_write_text(artifact_dir / "autoresearch_prompt.md", prompt)
        skill = self.find_autoresearch_skill(task)
        if skill is None and not mock:
            log = {
                "command": task.worker_command,
                "cwd": str(workspace),
                "returncode": 2,
                "stdout": "",
                "stderr": self.autoresearch_install_instructions(),
                "duration_seconds": 0,
                "timed_out": False,
                "mocked": False,
                "worker_type": "codex_autoresearch",
            }
        else:
            command = self._codex_exec_command(task.worker_command, artifact_dir / "autoresearch_prompt.md", "codex_autoresearch")
            if mock:
                results_dir = workspace / str(task.data["autoresearch"]["results_dir"])
                command = (
                    "python -c \"from pathlib import Path; "
                    f"p=Path({str(results_dir)!r}); p.mkdir(parents=True, exist_ok=True); "
                    "(p/'summary.md').write_text('mock autoresearch improved metric\\\\n'); "
                    "Path('optimized.txt').write_text('improved\\\\n')\""
                )
            log = run_command(command, workspace, timeout=task.worker_timeout_seconds)
            log["mocked"] = mock
            log["worker_type"] = "codex_autoresearch"
            log["autoresearch_skill"] = str(skill) if skill else None
        results_summary = self.collect_autoresearch_results(task, workspace, artifact_dir)
        log["autoresearch_results"] = results_summary
        atomic_write_text(artifact_dir / "autoresearch_log.json", json.dumps(log, indent=2, sort_keys=True) + "\n")
        atomic_write_text(artifact_dir / "worker_log.json", json.dumps(log, indent=2, sort_keys=True) + "\n")
        atomic_write_text(artifact_dir / "autoresearch.log", log["stdout"] + "\n" + log["stderr"])
        atomic_write_text(artifact_dir / "worker.log", log["stdout"] + "\n" + log["stderr"])
        return log

    @staticmethod
    def _once_sections() -> list[str]:
        return [
            "## Worker Mode",
            "codex_once",
            "",
            "Implement the task once, then stop. The Symphony runtime will run verify, guard, safety checks, and proof-of-work generation after you exit.",
            "",
        ]

    @staticmethod
    def _review_sections() -> list[str]:
        return [
            "## Worker Mode",
            "codex_review",
            "",
            "Review-only task. Inspect the diff or target branch, run requested verification and guard commands if useful, summarize risks, and do not edit files unless the task explicitly requests edits.",
            "",
        ]

    @staticmethod
    def _autoresearch_sections(task: TaskContract) -> list[str]:
        metric = task.data["metric"]
        autoresearch = task.data["autoresearch"]
        return [
            "$codex-autoresearch",
            "Mode: exec",
            "",
            "## Autoresearch Contract",
            f"Goal: {task.data['goal']}",
            f"Scope: {', '.join(task.data['allowed_scope'])}",
            f"Metric: {metric['name']}",
            f"Metric command: {metric['command']}",
            f"Metric parser: {metric['parser']}",
            f"Direction: {metric['direction']}",
            f"Target: {metric.get('target', 'not set')}",
            f"Verify: {task.data['verify_command']}",
            f"Guard: {task.data['guard_command']}",
            f"Iterations: {autoresearch['max_iterations']}",
            f"Run mode: {autoresearch['mode']}",
            f"Retain policy: {autoresearch['retain_policy']}",
            f"Results directory: {autoresearch['results_dir']}",
            "",
            "Run an unattended improve-verify loop. Establish a baseline, make one focused change per iteration, keep only improvements that satisfy the guard policy, log results under the configured results directory, and stop at the target, iteration cap, or a true blocker.",
            "Never bypass Symphony validation. Final output must summarize baseline metric, best metric, iterations, kept/discarded changes, guard status, and remaining risks.",
            "",
        ]

    @staticmethod
    def _codex_exec_command(command: str, prompt_file: Path, worker_type: str) -> str:
        if worker_type == "shell":
            return command.format(prompt_file=str(prompt_file))
        if "{prompt_file}" in command:
            return command.format(prompt_file=str(prompt_file))
        if Path(command).name == "codex" or command.strip().endswith("codex"):
            return f"{command} exec --ask-for-approval never --sandbox workspace-write {prompt_file}"
        return f"{command} < {prompt_file}"

    def find_autoresearch_skill(self, task: TaskContract) -> Path | None:
        configured = task.data.get("autoresearch", {}).get("skill_path")
        candidates = [Path(configured).expanduser()] if configured else []
        candidates.extend(self.AUTORESEARCH_SKILL_PATHS)
        for path in candidates:
            if path.exists():
                return path
        return None

    @staticmethod
    def autoresearch_install_instructions() -> str:
        return (
            "codex-autoresearch skill is not installed. Install it into ~/.codex/skills/codex-autoresearch "
            "or set autoresearch.skill_path to the skill's SKILL.md before running codex_autoresearch tasks."
        )

    @staticmethod
    def collect_autoresearch_results(task: TaskContract, workspace: Path, artifact_dir: Path) -> dict[str, Any]:
        results_dir = workspace / str(task.data.get("autoresearch", {}).get("results_dir", "autoresearch-results"))
        summary: dict[str, Any] = {"path": str(results_dir), "exists": results_dir.exists(), "files": []}
        if not results_dir.exists():
            return summary
        files = sorted(path.relative_to(results_dir).as_posix() for path in results_dir.rglob("*") if path.is_file())
        summary["files"] = files
        archive_dir = artifact_dir / "autoresearch-results"
        if archive_dir.exists():
            shutil.rmtree(archive_dir)
        shutil.copytree(results_dir, archive_dir)
        summary["artifact_path"] = str(archive_dir)
        return summary

    @staticmethod
    def _read_optional(path: Path) -> str:
        try:
            return path.read_text()
        except OSError:
            return ""


class Validator:
    def __init__(self, queue: LocalQueue):
        self.queue = queue

    def validate(self, task: TaskContract, workspace: Path, before: dict[str, str] | None = None) -> dict[str, Any]:
        artifact_dir = self.queue.task_artifact_dir(task.task_id)
        if before is None:
            before_path = artifact_dir / "snapshot_before.json"
            before = json.loads(before_path.read_text()) if before_path.exists() else {}
        after = Snapshot.collect(workspace)
        changed = Snapshot.changed(before, after)
        verify = self._maybe_run(str(task.data.get("verify_command") or ""), workspace)
        guard = self._maybe_run(str(task.data.get("guard_command") or ""), workspace)
        result = {
            "task_id": task.task_id,
            "workspace": str(workspace),
            "status": "passed",
            "changed_files": changed,
            "verify_command": verify,
            "guard_command": guard,
            "checks": {
                "workspace_isolation": self._workspace_isolated(workspace),
                "empty_diff": self._empty_diff_check(task, changed),
                "forbidden_paths": self._forbidden_paths(task, changed),
                "forbidden_patterns": self._forbidden_patterns(task, workspace, changed),
                "outside_scope": self._outside_scope(task, changed),
            },
            "created_at": now_iso(),
        }
        command_failed = any(
            item is not None and item.get("returncode") != 0 for item in [verify, guard]
        )
        checks_failed = [name for name, check in result["checks"].items() if not check["passed"]]
        if command_failed or checks_failed:
            result["status"] = "failed"
        atomic_write_text(artifact_dir / "validation.json", json.dumps(result, indent=2, sort_keys=True) + "\n")
        atomic_write_text(artifact_dir / "validation.md", self._markdown(result))
        return result

    @staticmethod
    def _maybe_run(command: str, workspace: Path) -> dict[str, Any] | None:
        if not command:
            return None
        return run_command(command, workspace)

    @staticmethod
    def _workspace_isolated(workspace: Path) -> dict[str, Any]:
        real = workspace.resolve()
        return {"passed": real.exists() and real.is_dir(), "message": str(real)}

    @staticmethod
    def _empty_diff_check(task: TaskContract, changed: list[str]) -> dict[str, Any]:
        if task.worker_type == "codex_review" or bool(task.data.get("allow_empty_diff")):
            return {"passed": True, "message": "empty diff allowed for review-only task"}
        return {"passed": len(changed) > 0, "message": "changed files detected" if changed else "empty diff"}

    @staticmethod
    def _matches_path(path: str, pattern: str) -> bool:
        normalized = path.strip("/")
        normalized_pattern = pattern.strip("/")
        return (
            normalized == normalized_pattern
            or normalized.startswith(normalized_pattern + "/")
            or fnmatch.fnmatch(normalized, normalized_pattern)
        )

    def _forbidden_paths(self, task: TaskContract, changed: list[str]) -> dict[str, Any]:
        hits = [
            path
            for path in changed
            for pattern in task.data["forbidden_paths"]
            if self._matches_path(path, str(pattern))
        ]
        return {"passed": not hits, "matches": sorted(set(hits))}

    def _outside_scope(self, task: TaskContract, changed: list[str]) -> dict[str, Any]:
        allowed = [str(item).strip("/") for item in task.data["allowed_scope"]]
        if not allowed or allowed == ["."]:
            return {"passed": True, "matches": []}
        hits = [path for path in changed if not any(self._matches_path(path, pattern) for pattern in allowed)]
        return {"passed": not hits, "matches": hits}

    def _forbidden_patterns(self, task: TaskContract, workspace: Path, changed: list[str]) -> dict[str, Any]:
        hits: list[dict[str, str]] = []
        patterns = [str(pattern) for pattern in task.data["forbidden_patterns"]]
        for rel in changed:
            path = workspace / rel
            if not path.exists() or not path.is_file():
                continue
            try:
                text = path.read_text(errors="ignore")
            except OSError:
                continue
            for pattern in patterns:
                if pattern and pattern in text:
                    hits.append({"file": rel, "pattern": pattern})
        return {"passed": not hits, "matches": hits}

    @staticmethod
    def _markdown(result: dict[str, Any]) -> str:
        lines = [f"# Validation: {result['task_id']}", "", f"Status: **{result['status']}**", ""]
        lines.append("## Changed Files")
        lines.extend(f"- `{path}`" for path in result["changed_files"] or ["<none>"])
        lines.append("")
        lines.append("## Checks")
        for name, check in result["checks"].items():
            marker = "PASS" if check["passed"] else "FAIL"
            lines.append(f"- {marker} `{name}`")
        return "\n".join(lines) + "\n"


class Reporter:
    def __init__(self, queue: LocalQueue):
        self.queue = queue

    def report(self, task: TaskContract) -> Path:
        artifact_dir = self.queue.task_artifact_dir(task.task_id)
        validation_path = artifact_dir / "validation.json"
        worker_path = artifact_dir / "worker_log.json"
        metric_path = artifact_dir / "metric_summary.json"
        validation = json.loads(validation_path.read_text()) if validation_path.exists() else {}
        worker = json.loads(worker_path.read_text()) if worker_path.exists() else {}
        metric = json.loads(metric_path.read_text()) if metric_path.exists() else {}
        changed = validation.get("changed_files", [])
        accept = validation.get("status") == "passed" and worker.get("returncode", 1) == 0
        if worker.get("worker_type") == "codex_autoresearch":
            accept = accept and bool(metric.get("improved") or metric.get("target_met"))
        lines = [
            f"# Proof of Work: {task.task_id}",
            "",
            "## Summary",
            task.data["goal"],
            "",
            "## Files Changed",
            *(f"- `{path}`" for path in changed),
            *(["- `<none>`"] if not changed else []),
            "",
            "## Diff Summary",
            f"{len(changed)} changed file(s).",
            "",
            "## Commands Run",
            f"- worker: `{worker.get('command', '<not run>')}` -> {worker.get('returncode', '<unknown>')}",
            f"- verify: `{self._command_label(validation.get('verify_command'))}` -> {self._returncode(validation.get('verify_command'))}",
            f"- guard: `{self._command_label(validation.get('guard_command'))}` -> {self._returncode(validation.get('guard_command'))}",
            "",
            "## Worker Mode",
            task.worker_type,
            "",
            *self._autoresearch_lines(worker, metric),
            "## Test Results",
            validation.get("status", "not run"),
            "",
            "## Safety Result",
            self._safety_summary(validation),
            "",
            "## Remaining Risks",
            "- Human review still required before accepting or merging worker changes.",
            "",
            "## Follow-up Task Suggestions",
            "- Promote frequently repeated validation commands into repository harness scripts.",
            "",
            "## Hermes Recommendation",
            "accept" if accept else "reject",
            "",
        ]
        target = artifact_dir / "proof_of_work.md"
        atomic_write_text(target, "\n".join(lines))
        return target

    @staticmethod
    def _autoresearch_lines(worker: dict[str, Any], metric: dict[str, Any]) -> list[str]:
        if worker.get("worker_type") != "codex_autoresearch":
            return []
        results = worker.get("autoresearch_results", {})
        lines = [
            "## Autoresearch Summary",
            f"- results_dir: `{results.get('path', '<missing>')}`",
            f"- archived: `{results.get('artifact_path', '<not archived>')}`",
            f"- files: {len(results.get('files', []))}",
        ]
        if metric:
            baseline = metric.get("baseline") or {}
            final = metric.get("final") or {}
            lines.extend(
                [
                    f"- metric: `{metric.get('name', '<unknown>')}`",
                    f"- baseline: {baseline.get('value', '<unknown>')}",
                    f"- final: {final.get('value', '<unknown>')}",
                    f"- improved: {metric.get('improved')}",
                    f"- target_met: {metric.get('target_met')}",
                ]
            )
        lines.append("")
        return lines

    @staticmethod
    def _command_label(item: dict[str, Any] | None) -> str:
        return item.get("command", "<not configured>") if item else "<not configured>"

    @staticmethod
    def _returncode(item: dict[str, Any] | None) -> str:
        return str(item.get("returncode", "<not run>")) if item else "<not run>"

    @staticmethod
    def _safety_summary(validation: dict[str, Any]) -> str:
        checks = validation.get("checks", {})
        failed = [name for name, check in checks.items() if not check.get("passed")]
        return "passed" if not failed else "failed: " + ", ".join(failed)


class HermesSymphonyRuntime:
    def __init__(self, queue_root: Path):
        self.queue = LocalQueue(queue_root)
        self.workspaces = WorkspaceManager(self.queue)
        self.dispatcher = WorkerDispatcher(self.queue)
        self.validator = Validator(self.queue)
        self.reporter = Reporter(self.queue)

    def run_task(self, task_id: str, mock_worker: bool = False) -> dict[str, Any]:
        with self.queue.locked():
            task, path = self.queue.load(task_id)
            path = self.queue.move(path, task, "claimed")
        workspace = self.workspaces.prepare(task)
        metric_evaluator = MetricEvaluator(task, workspace)
        metric_baseline = self._measure_metric(metric_evaluator, "baseline")
        before = Snapshot.collect(workspace)
        artifact_dir = self.queue.task_artifact_dir(task.task_id)
        atomic_write_text(artifact_dir / "snapshot_before.json", json.dumps(before, indent=2, sort_keys=True) + "\n")
        task.data["current_attempt"] = int(task.data["current_attempt"]) + 1
        with self.queue.locked():
            path = self.queue.find_path(task.task_id)
            path = self.queue.move(path, task, "running")
        self.queue.event("worker_started", task.task_id, workspace=str(workspace), mock_worker=mock_worker)
        worker = self.dispatcher.run(task, workspace, mock=mock_worker)
        self.queue.event("worker_finished", task.task_id, returncode=worker["returncode"])
        metric_final = self._measure_metric(metric_evaluator, "final")
        metric_summary = self._write_metric_summary(task, artifact_dir, metric_baseline, metric_final)
        validation = self.validator.validate(task, workspace, before)
        self.queue.event("validation_finished", task.task_id, status=validation["status"])
        self.reporter.report(task)
        if worker["returncode"] != 0:
            final = "retry" if int(task.data["current_attempt"]) < int(task.data["max_attempts"]) else "failed"
        elif task.worker_type == "codex_autoresearch" and not self._autoresearch_metric_acceptable(metric_summary):
            final = "failed"
        elif validation["status"] == "passed":
            final = "needs_review"
        else:
            final = "failed"
        with self.queue.locked():
            path = self.queue.find_path(task.task_id)
            self.queue.move(path, task, final)
        return {"task_id": task.task_id, "status": final, "validation": validation["status"], "workspace": str(workspace)}

    @staticmethod
    def _measure_metric(evaluator: MetricEvaluator, label: str) -> dict[str, Any] | None:
        if not evaluator.configured():
            return None
        try:
            return evaluator.measure(label)
        except Exception as error:
            return {"label": label, "error": str(error)}

    @staticmethod
    def _write_metric_summary(
        task: TaskContract,
        artifact_dir: Path,
        baseline: dict[str, Any] | None,
        final: dict[str, Any] | None,
    ) -> dict[str, Any]:
        if baseline is None and final is None:
            return {}
        summary = {
            "name": task.data.get("metric", {}).get("name"),
            "baseline": baseline,
            "final": final,
            "improved": MetricEvaluator.improved(baseline, final)
            if baseline and final and "error" not in baseline and "error" not in final
            else False,
            "target_met": MetricEvaluator.target_met(final) if final and "error" not in final else False,
        }
        atomic_write_text(artifact_dir / "metric_summary.json", json.dumps(summary, indent=2, sort_keys=True) + "\n")
        return summary

    @staticmethod
    def _autoresearch_metric_acceptable(metric_summary: dict[str, Any]) -> bool:
        return bool(metric_summary.get("improved") or metric_summary.get("target_met"))

    def daemon(self, interval: float, once: bool, mock_worker: bool) -> None:
        while True:
            with self.queue.locked():
                item = self.queue.next_inbox()
            if item is not None:
                task, _path = item
                self.run_task(task.task_id, mock_worker=mock_worker)
            if once:
                return
            time.sleep(interval)

    def accept(self, task_id: str) -> Path:
        with self.queue.locked():
            task, path = self.queue.load(task_id)
            if task.status != "needs_review":
                raise ValueError(f"task {task_id!r} must be in needs_review before accept; got {task.status}")
            return self.queue.move(path, task, "done")

    def reject(self, task_id: str) -> Path:
        with self.queue.locked():
            task, path = self.queue.load(task_id)
            if task.status != "needs_review":
                raise ValueError(f"task {task_id!r} must be in needs_review before reject; got {task.status}")
            return self.queue.move(path, task, "failed")


class TaskSource:
    def poll(self) -> Iterable[TaskContract]:
        raise NotImplementedError


class LocalQueueTaskSource(TaskSource):
    def __init__(self, queue: LocalQueue):
        self.queue = queue

    def poll(self) -> Iterable[TaskContract]:
        item = self.queue.next_inbox()
        return [] if item is None else [item[0]]


class GitHubIssueTaskSource(TaskSource):
    def poll(self) -> Iterable[TaskContract]:  # pragma: no cover - design placeholder
        raise NotImplementedError("GitHub Issues adapter is a v2 integration point")


class LinearTaskSource(TaskSource):
    def poll(self) -> Iterable[TaskContract]:  # pragma: no cover - design placeholder
        raise NotImplementedError("Linear adapter is a v2 integration point")


def init_task(path: Path, title: str, repo_path: Path, goal: str) -> Path:
    task_id = safe_task_id(title.lower().replace(" ", "-")) + "-" + uuid.uuid4().hex[:8]
    data = {
        "task_id": task_id,
        "title": title,
        "repo_path": str(repo_path.resolve()),
        "goal": goal,
        "background": "",
        "acceptance_criteria": [],
        "allowed_scope": ["."],
        "forbidden_paths": [],
        "forbidden_patterns": [],
        "verify_command": "",
        "guard_command": "",
        "worker_type": "codex",
        "worker_command": "codex exec --ask-for-approval never --sandbox workspace-write {prompt_file}",
        "worker": {
            "type": "codex_once",
            "command": "codex",
            "timeout_seconds": 900,
        },
        "max_attempts": 1,
        "current_attempt": 0,
        "status": "new",
        "created_at": now_iso(),
        "updated_at": now_iso(),
    }
    dump_structured(path, data)
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Hermes Symphony local orchestration runtime")
    parser.add_argument("--version", action="version", version=f"hermes-symphony {VERSION}")
    parser.add_argument("--queue", default=".symphony", help="queue root")
    sub = parser.add_subparsers(dest="command", required=True)
    enqueue = sub.add_parser("enqueue")
    enqueue.add_argument("task_file")
    run = sub.add_parser("run")
    run.add_argument("--task-id", required=True)
    run.add_argument("--mock-worker", action="store_true")
    validate = sub.add_parser("validate")
    validate.add_argument("--task-id", required=True)
    report = sub.add_parser("report")
    report.add_argument("--task-id", required=True)
    accept = sub.add_parser("accept")
    accept.add_argument("--task-id", required=True)
    reject = sub.add_parser("reject")
    reject.add_argument("--task-id", required=True)
    sub.add_parser("status")
    daemon = sub.add_parser("daemon")
    daemon.add_argument("--interval", type=float, default=5.0)
    daemon.add_argument("--once", action="store_true")
    daemon.add_argument("--mock-worker", action="store_true")
    init = sub.add_parser("init-task")
    init.add_argument("task_file")
    init.add_argument("--title", required=True)
    init.add_argument("--repo-path", default=".")
    init.add_argument("--goal", required=True)
    args = parser.parse_args(argv)

    runtime = HermesSymphonyRuntime(Path(args.queue))
    if args.command == "enqueue":
        with runtime.queue.locked():
            print(runtime.queue.enqueue(Path(args.task_file)))
    elif args.command == "run":
        print(json.dumps(runtime.run_task(args.task_id, mock_worker=args.mock_worker), indent=2, sort_keys=True))
    elif args.command == "validate":
        task, _ = runtime.queue.load(args.task_id)
        workspace = runtime.workspaces.workspace_for(task)
        print(json.dumps(runtime.validator.validate(task, workspace), indent=2, sort_keys=True))
    elif args.command == "report":
        task, _ = runtime.queue.load(args.task_id)
        print(runtime.reporter.report(task))
    elif args.command == "accept":
        print(runtime.accept(args.task_id))
    elif args.command == "reject":
        print(runtime.reject(args.task_id))
    elif args.command == "status":
        print(json.dumps(runtime.queue.status(), indent=2, sort_keys=True))
    elif args.command == "daemon":
        runtime.daemon(args.interval, args.once, args.mock_worker)
    elif args.command == "init-task":
        print(init_task(Path(args.task_file), args.title, Path(args.repo_path), args.goal))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
