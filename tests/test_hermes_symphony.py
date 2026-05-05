import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from hermes_symphony import (  # noqa: E402
    HermesSymphonyRuntime,
    LocalQueue,
    Snapshot,
    TaskContract,
    Validator,
    dump_structured,
    main,
    now_iso,
)


def make_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "app.py").write_text("print('hello')\n")
    (repo / "WORKFLOW.md").write_text("# Repo Workflow\n\nRun focused validation.\n")
    return repo


def task_data(repo: Path, **overrides):
    data = {
        "task_id": "task-1",
        "title": "Task 1",
        "repo_path": str(repo),
        "goal": "Make a change.",
        "background": "Test background.",
        "acceptance_criteria": ["Change exists."],
        "allowed_scope": ["."],
        "forbidden_paths": [],
        "forbidden_patterns": [],
        "verify_command": "python -c \"print('verify')\"",
        "guard_command": "python -c \"print('guard')\"",
        "worker_type": "shell",
        "worker_command": "python -c \"from pathlib import Path; Path('changed.txt').write_text('changed')\"",
        "max_attempts": 1,
        "current_attempt": 0,
        "status": "new",
        "created_at": now_iso(),
        "updated_at": now_iso(),
    }
    data.update(overrides)
    return data


def write_task(path: Path, repo: Path, **overrides) -> Path:
    dump_structured(path, task_data(repo, **overrides))
    return path


def test_task_contract_validation_requires_fields(tmp_path: Path):
    path = tmp_path / "bad.yaml"
    dump_structured(path, {"task_id": "x"})

    with pytest.raises(ValueError, match="missing required fields"):
        TaskContract.load(path)


def test_queue_movement_inbox_active_review(tmp_path: Path):
    repo = make_repo(tmp_path)
    queue = LocalQueue(tmp_path / ".symphony")
    task_file = write_task(tmp_path / "task.yaml", repo)

    inbox_path = queue.enqueue(task_file)
    task = TaskContract.load(inbox_path)
    active_path = queue.move(inbox_path, task, "running")
    review_path = queue.move(active_path, task, "needs_review")

    assert not inbox_path.exists()
    assert not active_path.exists()
    assert review_path.exists()
    assert queue.status()["review"] == ["task-1"]


def test_workspace_path_isolation(tmp_path: Path):
    repo = make_repo(tmp_path)
    task = TaskContract(task_data(repo)).validate()
    runtime = HermesSymphonyRuntime(tmp_path / ".symphony")

    workspace = runtime.workspaces.prepare(task)

    assert workspace == (tmp_path / ".symphony" / "workspaces" / "task-1").resolve()
    assert workspace.exists()
    assert str(workspace).startswith(str((tmp_path / ".symphony" / "workspaces").resolve()))


def test_workspace_copy_ignores_in_repo_queue_roots(tmp_path: Path):
    repo = make_repo(tmp_path)
    (repo / ".symphony-smoke" / "workspaces" / "old").mkdir(parents=True)
    (repo / ".symphony-smoke" / "workspaces" / "old" / "nested.txt").write_text("old")
    task = TaskContract(task_data(repo)).validate()
    runtime = HermesSymphonyRuntime(repo / ".symphony-smoke")

    workspace = runtime.workspaces.prepare(task)

    assert not (workspace / ".symphony-smoke").exists()


def test_forbidden_path_detection(tmp_path: Path):
    repo = make_repo(tmp_path)
    task = TaskContract(task_data(repo, forbidden_paths=["secrets/"])).validate()
    runtime = HermesSymphonyRuntime(tmp_path / ".symphony")
    workspace = runtime.workspaces.prepare(task)
    before = Snapshot.collect(workspace)
    (workspace / "secrets").mkdir()
    (workspace / "secrets" / "token.txt").write_text("x")

    result = Validator(runtime.queue).validate(task, workspace, before)

    assert result["status"] == "failed"
    assert result["checks"]["forbidden_paths"]["matches"] == ["secrets/token.txt"]


def test_forbidden_pattern_detection(tmp_path: Path):
    repo = make_repo(tmp_path)
    task = TaskContract(task_data(repo, forbidden_patterns=["LIVE_TRADING=true"])).validate()
    runtime = HermesSymphonyRuntime(tmp_path / ".symphony")
    workspace = runtime.workspaces.prepare(task)
    before = Snapshot.collect(workspace)
    (workspace / "settings.py").write_text("LIVE_TRADING=true\n")

    result = Validator(runtime.queue).validate(task, workspace, before)

    assert result["status"] == "failed"
    assert result["checks"]["forbidden_patterns"]["matches"][0]["file"] == "settings.py"


def test_trading_profile_adds_safety_patterns(tmp_path: Path):
    repo = make_repo(tmp_path)
    task = TaskContract(task_data(repo, safety_profile="trading")).validate()

    assert "place_order(" in task.data["forbidden_patterns"]
    assert ".env" in task.data["forbidden_paths"]


def test_outside_scope_detection(tmp_path: Path):
    repo = make_repo(tmp_path)
    task = TaskContract(task_data(repo, allowed_scope=["src/"])).validate()
    runtime = HermesSymphonyRuntime(tmp_path / ".symphony")
    workspace = runtime.workspaces.prepare(task)
    before = Snapshot.collect(workspace)
    (workspace / "README.md").write_text("outside\n")

    result = Validator(runtime.queue).validate(task, workspace, before)

    assert result["status"] == "failed"
    assert result["checks"]["outside_scope"]["matches"] == ["README.md"]


def test_empty_diff_rejection(tmp_path: Path):
    repo = make_repo(tmp_path)
    task = TaskContract(task_data(repo)).validate()
    runtime = HermesSymphonyRuntime(tmp_path / ".symphony")
    workspace = runtime.workspaces.prepare(task)
    before = Snapshot.collect(workspace)

    result = Validator(runtime.queue).validate(task, workspace, before)

    assert result["status"] == "failed"
    assert result["checks"]["empty_diff"]["passed"] is False


def test_validation_json_shape_and_proof_generation(tmp_path: Path):
    repo = make_repo(tmp_path)
    runtime = HermesSymphonyRuntime(tmp_path / ".symphony")
    task_file = write_task(tmp_path / "task.yaml", repo)
    runtime.queue.enqueue(task_file)

    result = runtime.run_task("task-1")
    artifact_dir = tmp_path / ".symphony" / "tasks" / "task-1"
    validation = json.loads((artifact_dir / "validation.json").read_text())
    proof = (artifact_dir / "proof_of_work.md").read_text()

    assert result["status"] == "needs_review"
    assert validation["task_id"] == "task-1"
    assert validation["status"] == "passed"
    assert "## Hermes Recommendation" in proof
    assert "accept" in proof


def test_accept_and_reject_review_transitions(tmp_path: Path):
    repo = make_repo(tmp_path)
    runtime = HermesSymphonyRuntime(tmp_path / ".symphony")
    first = write_task(tmp_path / "task.yaml", repo)
    second = write_task(tmp_path / "task2.yaml", repo, task_id="task-2")
    runtime.queue.enqueue(first)
    runtime.queue.enqueue(second)
    runtime.run_task("task-1")
    runtime.run_task("task-2")

    runtime.accept("task-1")
    runtime.reject("task-2")

    status = runtime.queue.status()
    assert status["done"] == ["task-1"]
    assert status["failed"] == ["task-2"]


def test_event_log_records_runtime_transitions(tmp_path: Path):
    repo = make_repo(tmp_path)
    runtime = HermesSymphonyRuntime(tmp_path / ".symphony")
    task_file = write_task(tmp_path / "task.yaml", repo)

    runtime.queue.enqueue(task_file)
    runtime.run_task("task-1")

    events_path = tmp_path / ".symphony" / "logs" / "events.jsonl"
    events = [json.loads(line)["event"] for line in events_path.read_text().splitlines()]
    assert "task_enqueued" in events
    assert "worker_started" in events
    assert "validation_finished" in events


def test_worker_timeout_becomes_failed_task(tmp_path: Path):
    repo = make_repo(tmp_path)
    runtime = HermesSymphonyRuntime(tmp_path / ".symphony")
    task_file = write_task(
        tmp_path / "task.yaml",
        repo,
        worker_command="python -c \"import time; time.sleep(2)\"",
        worker_timeout_seconds=1,
        verify_command="",
        guard_command="",
    )
    runtime.queue.enqueue(task_file)

    result = runtime.run_task("task-1")
    worker_log = json.loads((tmp_path / ".symphony" / "tasks" / "task-1" / "worker_log.json").read_text())

    assert result["status"] == "failed"
    assert worker_log["timed_out"] is True


def test_daemon_one_cycle_dry_run_with_mocked_codex(tmp_path: Path):
    repo = make_repo(tmp_path)
    queue_root = tmp_path / ".symphony"
    task_file = write_task(tmp_path / "task.yaml", repo, verify_command="", guard_command="")

    assert main(["--queue", str(queue_root), "enqueue", str(task_file)]) == 0
    assert main(["--queue", str(queue_root), "daemon", "--once", "--mock-worker"]) == 0

    status = LocalQueue(queue_root).status()
    assert status["review"] == ["task-1"]
    assert (queue_root / "tasks" / "task-1" / "proof_of_work.md").exists()
