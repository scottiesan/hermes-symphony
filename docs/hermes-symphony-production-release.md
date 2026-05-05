# Hermes Symphony Production Release

## Release

`0.2.0` is the production-oriented local release. It is suitable for single-host Hermes
orchestration where Hermes supervises the review decision and Codex runs in isolated task
workspaces.

## Production Hardening Included

- Atomic writes for queue files and generated artifacts.
- Queue lock for enqueue, claim, run-state, accept, and reject transitions.
- Append-only JSONL event log at `.symphony/logs/events.jsonl`.
- Worker timeout handling that records failed worker logs instead of crashing the runtime.
- Explicit `accept` and `reject` commands for Hermes review.
- PyPI-style project metadata and console script entry point.
- Release checklist in `RELEASE.md`.
- Optional `codex_autoresearch` worker mode with metric gating and final Symphony validation.
- `codex_review` worker mode for review-only tasks.

## Operator Runbook

1. Enqueue a task contract.
2. Run `daemon` under a process supervisor for continuous operation.
3. Review `proof_of_work.md` for tasks in `.symphony/review/`.
4. Run `accept` only after Hermes approves the proof.
5. Run `reject` when validation, safety, or scope is not acceptable.
6. Archive or clean old `.symphony/workspaces/` directories according to local retention policy.

## Recommended Supervisor Command

```bash
python scripts/hermes_symphony.py --queue .symphony daemon --interval 5
```

## Release Verification

```bash
python -m py_compile scripts/hermes_symphony.py
PYTHONDONTWRITEBYTECODE=1 pytest -q -p no:cacheprovider
python scripts/hermes_symphony.py --version
```

## Remaining Production Risks

- The queue lock is local filesystem coordination, not a distributed lock.
- Worker sandboxing depends on Codex configuration and host controls.
- Workspaces are preserved for review and must be cleaned intentionally.
- GitHub/Linear adapters are not implemented in this release.
- Autoresearch background runtime control is delegated to Codex Autoresearch; Symphony captures
  results and performs final validation after worker completion.
