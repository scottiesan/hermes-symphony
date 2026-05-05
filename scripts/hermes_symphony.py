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


VERSION = "0.1.0"
TASK_STATES = {"new", "claimed", "running", "needs_review", "done", "failed", "blocked", "retry"}
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
        missing = sorted(REQUIRED_FIELDS - self.data.keys())
        if missing:
            raise ValueError(f"task contract missing required fields: {', '.join(missing)}")
        if self.status not in TASK_STATES:
            raise ValueError(f"invalid task status {self.status!r}")
        if not isinstance(self.data["allowed_scope"], list):
            raise ValueError("allowed_scope must be a list")
        if not isinstance(self.data["forbidden_paths"], list):
            raise ValueError("forbidden_paths must be a list")
        if not isinstance(self.data["forbidden_patterns"], list):
            raise ValueError("forbidden_patterns must be a list")
        if int(self.data["max_attempts"]) < 1:
            raise ValueError("max_attempts must be >= 1")
        if int(self.data["current_attempt"]) < 0:
            raise ValueError("current_attempt must be >= 0")
        if self.safety_profile == "trading":
            self.data["forbidden_paths"] = sorted(set(self.data["forbidden_paths"] + TRADING_FORBIDDEN_PATHS))
            self.data["forbidden_patterns"] = sorted(
                set(self.data["forbidden_patterns"] + TRADING_FORBIDDEN_PATTERNS)
            )
        return self

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
        return str(self.data.get("workspace_mode", "worktree")).lower()

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


class WorkerDispatcher:
    def __init__(self, queue: LocalQueue):
        self.queue = queue

    def build_prompt(self, task: TaskContract, workspace: Path) -> str:
        workflow = self._read_optional(workspace / "WORKFLOW.md")
        hermes_workflow = self._read_optional(workspace / "HERMES_WORKFLOW.md")
        if not hermes_workflow:
            hermes_workflow = self._read_optional(Path.cwd() / "HERMES_WORKFLOW.md")
        return "\n".join(
            [
                "# Hermes Symphony Worker Prompt",
                "",
                "Work only inside this isolated workspace:",
                str(workspace),
                "",
                "Never read, write, or execute commands outside the task workspace.",
                "",
                "## Task Contract",
                json.dumps(task.data, indent=2, sort_keys=True),
                "",
                "## Repository WORKFLOW.md",
                workflow or "No repository WORKFLOW.md found.",
                "",
                "## HERMES_WORKFLOW.md",
                hermes_workflow or "No HERMES_WORKFLOW.md found.",
            ]
        )

    def run(self, task: TaskContract, workspace: Path, mock: bool = False) -> dict[str, Any]:
        artifact_dir = self.queue.task_artifact_dir(task.task_id)
        prompt = self.build_prompt(task, workspace)
        atomic_write_text(artifact_dir / "worker_prompt.md", prompt)
        command = str(task.data["worker_command"])
        if mock:
            command = "python -c \"from pathlib import Path; Path('MOCK_WORKER_RAN.txt').write_text('ok\\n')\""
        if task.data.get("worker_type") == "codex" and "{prompt_file}" not in command and not mock:
            command = f"{command} < {artifact_dir / 'worker_prompt.md'}"
        command = command.format(prompt_file=str(artifact_dir / "worker_prompt.md"))
        log = run_command(command, workspace, timeout=int(task.data.get("worker_timeout_seconds", 3600)))
        log["mocked"] = mock
        atomic_write_text(artifact_dir / "worker_log.json", json.dumps(log, indent=2, sort_keys=True) + "\n")
        atomic_write_text(artifact_dir / "worker.log", log["stdout"] + "\n" + log["stderr"])
        return log

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
                "empty_diff": {"passed": len(changed) > 0, "message": "changed files detected" if changed else "empty diff"},
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
        validation = json.loads(validation_path.read_text()) if validation_path.exists() else {}
        worker = json.loads(worker_path.read_text()) if worker_path.exists() else {}
        changed = validation.get("changed_files", [])
        accept = validation.get("status") == "passed" and worker.get("returncode", 1) == 0
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
        validation = self.validator.validate(task, workspace, before)
        self.queue.event("validation_finished", task.task_id, status=validation["status"])
        self.reporter.report(task)
        if worker["returncode"] != 0:
            final = "retry" if int(task.data["current_attempt"]) < int(task.data["max_attempts"]) else "failed"
        elif validation["status"] == "passed":
            final = "needs_review"
        else:
            final = "failed"
        with self.queue.locked():
            path = self.queue.find_path(task.task_id)
            self.queue.move(path, task, final)
        return {"task_id": task.task_id, "status": final, "validation": validation["status"], "workspace": str(workspace)}

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
