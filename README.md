# Hermes Symphony

Hermes Symphony is a Hermes-native orchestration runtime inspired by OpenAI Symphony. It lets Hermes
supervise app-building and feature work while Codex performs implementation in isolated task
workspaces.

Production release target: `0.2.0`.

## Install For Development

```bash
python -m pip install -e ".[dev]"
```

## Install The Hermes Skill In Hermes TUI

Use this direct Hermes TUI slash command:

```text
/skills install scottiesan/hermes-symphony/.hermes/skills/hermes-symphony --now
```

If you want to give Hermes Agent a natural-language prompt instead of a slash command, use:

```text
Install the Hermes Symphony skill using Hermes Skills Hub.
Run:
/skills install scottiesan/hermes-symphony/.hermes/skills/hermes-symphony --now

If it is already installed, run:
/skills install scottiesan/hermes-symphony/.hermes/skills/hermes-symphony --force --now

Then verify the skill appears in /skills list and tell me whether I need to restart Hermes or run /reload-skills.
```

CLI equivalent outside TUI:

```bash
hermes skills install scottiesan/hermes-symphony/.hermes/skills/hermes-symphony --yes
```

This installs the full skill bundle through Hermes Agent’s native Skills Hub. See
[INSTALL.md](INSTALL.md) and [docs/hermes-tui-usage.md](docs/hermes-tui-usage.md).

## Sample Hermes TUI Usage

After restarting Hermes, try:

```text
Use hermes-symphony to create a task for this repo that runs in codex_once mode.
Goal: add a small health check endpoint.
Allowed scope: src/, tests/.
Verify command: pytest -q.
Guard command: python -m compileall .
Enqueue it and show me the task id.
```

Then:

```text
Use hermes-symphony to run TASK_ID, validate it, and summarize proof_of_work.md.
```

## Quickstart

```bash
python scripts/hermes_symphony.py enqueue examples/build-dashboard-app.yaml
python scripts/hermes_symphony.py daemon --once --mock-worker
python scripts/hermes_symphony.py status
```

Use real Codex by omitting `--mock-worker` and setting each task's `worker.command`.

## Worker Modes

Hermes Symphony supports three worker strategies:

- `codex_once`: default mode for normal app and feature implementation.
- `codex_autoresearch`: optional mode for measurable optimization tasks with a deterministic
  metric, verify command, and guard command.
- `codex_review`: review-only mode for inspecting diffs or branches without editing files unless
  explicitly requested.

Use `codex_autoresearch` only when the task has a mechanical metric such as failing test count,
latency, throughput, coverage, or numeric command output. Autoresearch never bypasses Symphony
validation; Hermes should still review `proof_of_work.md` before accepting.

## Review Flow

Successful validated worker runs move to `.symphony/review/`. Hermes should inspect:

- `.symphony/tasks/<task_id>/validation.json`
- `.symphony/tasks/<task_id>/validation.md`
- `.symphony/tasks/<task_id>/proof_of_work.md`

Then accept or reject:

```bash
python scripts/hermes_symphony.py accept --task-id TASK_ID
python scripts/hermes_symphony.py reject --task-id TASK_ID
```

## Safety

The runtime enforces local validation checks for forbidden paths, forbidden patterns,
outside-scope changes, empty diffs, worker command failures, verify command failures, and guard
command failures. Trading tasks can opt into `safety_profile: trading`.

See [docs/hermes-symphony-quickstart.md](docs/hermes-symphony-quickstart.md) and
[docs/hermes-symphony-architecture.md](docs/hermes-symphony-architecture.md).
