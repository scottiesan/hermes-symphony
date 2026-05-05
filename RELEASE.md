# Hermes Symphony 0.1.0 Release Plan

## Scope

This release packages the Hermes-native Python runtime as a production-ready local orchestrator for
single-host use.

Included:

- File-backed task queue.
- Atomic queue/artifact writes.
- Queue-level lock for task claim and review transitions.
- Isolated per-task workspace management.
- Codex CLI worker dispatch.
- Mock worker mode for dry runs and CI.
- Validation artifacts and proof-of-work reports.
- Hermes skill and examples.
- Trading safety profile.
- Local event log at `.symphony/logs/events.jsonl`.

Deferred:

- Distributed queue coordination.
- Codex app-server streaming.
- GitHub Issues and Linear polling adapters.
- Hosted dashboard.
- Strong OS/container sandbox management.

## Release Checklist

- `python -m py_compile scripts/hermes_symphony.py`
- `pytest -q`
- `python scripts/hermes_symphony.py --version`
- One-cycle daemon dry run with `--mock-worker`
- Inspect generated `proof_of_work.md`

## Compatibility

- Python 3.10+
- Requires PyYAML for YAML task files.
- Does not require Codex for tests or mocked dry runs.

## Operator Notes

- Use `--mock-worker` only for dry runs.
- Keep `.symphony/` out of source control.
- Review proof-of-work before accepting any task.
- Use `safety_profile: trading` for trading repositories.
