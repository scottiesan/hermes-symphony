# Hermes Symphony 0.2.0 Release Plan

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
- Optional `codex_autoresearch` worker mode for measurable improve-verify loops.
- `codex_review` worker mode for review-only tasks.

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
- `codex_autoresearch` tasks require the `codex-autoresearch` skill to be installed or an explicit
  `autoresearch.skill_path`.
- Hermes skill installation from GitHub is supported with `scripts/install_hermes_skill.py`.

## Operator Notes

- Use `--mock-worker` only for dry runs.
- Keep `.symphony/` out of source control.
- Review proof-of-work before accepting any task.
- Use `safety_profile: trading` for trading repositories.
