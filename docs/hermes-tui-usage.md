# Hermes TUI Usage

## Install From GitHub

Paste this direct slash command into Hermes TUI:

```text
/skills install scottiesan/hermes-symphony/.hermes/skills/hermes-symphony --now
```

To update an existing install:

```text
/skills install scottiesan/hermes-symphony/.hermes/skills/hermes-symphony --force --now
```

Natural-language prompt version:

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

The identifier is the GitHub repo plus the skill directory path. Hermes Agent’s Skills Hub fetches
the bundle, scans it, and installs it under the active Hermes home.

## Create A Normal Codex Task

Paste after restart:

```text
Use hermes-symphony to create and enqueue a task for the current repo.
Worker mode: codex_once.
Goal: add a small local dashboard app.
Allowed scope: .
Forbidden paths: .env, secrets/, *.key, *.pem.
Verify command: pytest -q.
Guard command: python -m compileall .
Show me the task id and queue status.
```

## Run And Review A Task

```text
Use hermes-symphony to run TASK_ID, then read validation.md and proof_of_work.md.
Tell me whether Hermes should accept or reject it and why.
```

If accepted:

```text
Use hermes-symphony to accept TASK_ID.
```

If rejected:

```text
Use hermes-symphony to reject TASK_ID and create a follow-up task with the remaining work.
```

## Create An Autoresearch Task

Use this only for measurable improvement work:

```text
Use hermes-symphony to create and enqueue a codex_autoresearch task.
Goal: reduce failing pytest tests.
Metric name: failing_tests.
Metric command: pytest -q.
Metric parser: failing_tests.
Metric direction: lower.
Metric target: 0.
Autoresearch max iterations: 20.
Autoresearch mode: foreground.
Allowed scope: src/, tests/.
Verify command: pytest -q.
Guard command: python -m compileall .
Forbidden paths: .env, .env.local, secrets/, *.key, *.pem.
Forbidden patterns: private_key, API_SECRET.
```

## Trading Safety Example

```text
Use hermes-symphony to create a codex_autoresearch task for paper-trading reliability.
Set safety_profile: trading.
Goal: reduce paper resolver failures without enabling live execution.
Forbidden patterns: EXECUTION_ENABLED=true, LIVE_TRADING=true, place_order(, submit_order(, send_order(, real_money, private_key.
Forbidden paths: .env, .env.local, secrets/, wallet.dat, *.key, *.pem.
Verify command: pytest -q.
Guard command: python -m compileall . && ! grep -R "EXECUTION_ENABLED=true" .
```

Hermes should always review `proof_of_work.md` before accepting.
