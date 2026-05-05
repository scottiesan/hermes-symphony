# Hermes Symphony Skill Workflow

Hermes is the supervisor. Codex is the implementation worker. The local runtime owns queue state,
workspace isolation, validation, and proof-of-work.

Task lifecycle:

1. `new`: task file is in `.symphony/inbox/`.
2. `claimed`: runtime reserved the task.
3. `running`: workspace is ready and worker command is executing.
4. `needs_review`: worker and validation passed; Hermes reviews proof.
5. `done`: Hermes accepted the result.
6. `failed`: worker, validation, or safety checks failed.
7. `blocked`: external prerequisite is missing.
8. `retry`: retryable worker failure before `max_attempts`.

Hermes review policy:

- Accept only when validation passed and the proof matches the task acceptance criteria.
- Reject any proof that touched forbidden paths, introduced forbidden patterns, changed outside
  allowed scope, or produced no diff.
- Create follow-up tasks for useful out-of-scope work instead of expanding the current task.
