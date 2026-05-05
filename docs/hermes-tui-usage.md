# Hermes TUI Usage

## Install From GitHub Prompt

Paste this full prompt into Hermes TUI:

```text
Install the Hermes Symphony skill from GitHub:
https://github.com/scottiesan/hermes-symphony

Steps:
1. Clone the repo into a temporary directory.
2. Run: python scripts/install_hermes_skill.py --overwrite
3. Verify this file exists: ~/.hermes/skills/hermes-symphony/SKILL.md
4. Verify this runtime exists: ~/.hermes/skills/hermes-symphony/runtime/hermes_symphony.py
5. Report the installed path and tell me to restart Hermes so the skill is loaded.
```

The Hermes agent should clone the repository, run:

```bash
python scripts/install_hermes_skill.py --overwrite
```

and verify:

```text
~/.hermes/skills/hermes-symphony/SKILL.md
```

Restart Hermes after installation so the skill is loaded.

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
