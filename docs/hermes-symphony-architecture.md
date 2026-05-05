# Hermes Symphony Architecture

## Evaluation

I evaluated three implementation paths against OpenAI Symphony's `SPEC.md`, README, Elixir README,
Elixir `WORKFLOW.md`, and core Elixir modules for orchestration, workspace creation, prompt
building, config, and path safety.

Option A, wrapping the Elixir implementation, would inherit OTP supervision, Linear polling,
Codex app-server support, and a dashboard. It is a poor v1 fit for Hermes because Hermes needs a
local file-backed task queue, task contracts, proof-of-work artifacts, and operation without Linear.
Wrapping Elixir would also force a BEAM runtime into every Hermes install.

Option B, porting the SPEC into a Hermes-native Python CLI/runtime, is the best practical v1.
It keeps Symphony's architecture source of truth: repo-owned workflow policy, deterministic
workspace isolation, a scheduler/runner boundary, worker prompts, retries, validation, and
operator-visible logs. It also lets Hermes add queue artifacts and review/accept/reject flows as
plain files.

Option C, a hybrid adapter, is useful later if Hermes needs Codex app-server streaming or Phoenix
observability. For v1 it adds complexity before the queue, validator, and proof contract have
settled.

Decision: Hermes Symphony v1 is a native Python/CLI runtime with adapter interfaces for future
GitHub Issues, Linear, and app-server integrations.

## Runtime Shape

```text
Hermes Agent
  -> hermes-symphony skill
  -> scripts/hermes_symphony.py
  -> local task queue
  -> workspace manager
  -> Codex worker dispatcher
  -> validator
  -> proof-of-work reporter
  -> Hermes review/accept/reject/follow-up
```

## Borrowed From OpenAI Symphony

- Long-running orchestrator model.
- Repository-owned `WORKFLOW.md` policy.
- Isolated per-issue/per-task workspace.
- Worker prompt rendered from task context and workflow policy.
- Retry/continuation-friendly workspace preservation.
- Structured logs and operator-visible status.
- Separation between orchestration and tracker writes.

## Changed For Hermes

- Local queue replaces Linear as the required source in v1.
- Task contracts are YAML/JSON files with explicit validation and safety fields.
- Proof-of-work is a first-class artifact for Hermes review.
- Validation includes forbidden path checks, forbidden pattern checks, outside-scope checks, and
  empty-diff rejection.
- Codex CLI is the first worker interface; app-server streaming is deferred.

## Adapter Interfaces

`TaskSource` is the integration boundary.

- `LocalQueueTaskSource`: implemented.
- `GitHubIssueTaskSource`: placeholder for converting labeled GitHub issues into task contracts.
- `LinearTaskSource`: placeholder for querying Linear active states and converting issues into
  task contracts.

GitHub and Linear adapters should normalize external tickets into the same contract fields, then
let the existing runtime handle workspace, worker, validation, and proof.

## Safety Model

The runtime provides local guardrails, not a complete sandbox. It never intentionally runs worker
commands outside the task workspace, captures logs, and validates changed files after execution.

For trading repos, `safety_profile: trading` adds rejections for live execution flags, order
submission calls, real-money terms, private keys, secrets, wallets, credentials, and `.env` edits.

Known limitation: host-level process sandboxing is delegated to Codex and the OS. v2 should add
stronger subprocess containment and app-server sandbox policy enforcement.

## Production Release Notes

The `0.1.0` release adds atomic writes, a local queue lock, append-only JSONL events, worker timeout
handling, and explicit Hermes review transitions. This makes the runtime appropriate for
single-host production use under a process supervisor, with Hermes retaining the final
accept/reject decision.
