---
name: hermes-symphony
description: "Install and operate the Hermes Symphony orchestration runtime for isolated Codex, Codex Autoresearch, and review workers."
---

# hermes-symphony

Use this skill when Hermes needs to orchestrate app or feature work through isolated Codex workers.

## Install From GitHub In Hermes TUI

Users should paste this full prompt:

```text
Install the Hermes Symphony skill from GitHub:
https://github.com/scottiesan/hermes-symphony

Use the native Hermes skills installer if available:
hermes skills install scottiesan/hermes-symphony/.hermes/skills/hermes-symphony --yes

If that command is unavailable, clone the repo into a temporary directory and run:
python scripts/install_hermes_skill.py --overwrite

Verify:
- $HERMES_HOME/skills/hermes-symphony/SKILL.md exists, or ~/.hermes/skills/hermes-symphony/SKILL.md if HERMES_HOME is unset.
- The installed skill has runtime/hermes_symphony.py.

Report the installed path and tell me to restart Hermes or run /reload-skills.
```

Expected install flow:

```bash
git clone https://github.com/scottiesan/hermes-symphony
cd hermes-symphony
python scripts/install_hermes_skill.py --overwrite
```

Then verify `~/.hermes/skills/hermes-symphony/SKILL.md` and ask the user to restart Hermes.

## Runtime

When installed from GitHub, this skill includes a bundled runtime at:

```bash
runtime/hermes_symphony.py
```

From inside the skill directory, run:

```bash
python runtime/hermes_symphony.py --help
```

When working from the source repository, `scripts/hermes_symphony.py` is the same runtime.

## Workflow

1. Create a task contract from `.hermes/skills/hermes-symphony/templates/task.yaml`.
2. Enqueue it:

   ```bash
   python runtime/hermes_symphony.py enqueue path/to/task.yaml
   ```

3. Run one task or start the daemon:

   ```bash
   python runtime/hermes_symphony.py run --task-id TASK_ID
   python runtime/hermes_symphony.py daemon --queue .symphony
   ```

4. Inspect generated artifacts:

   - `.symphony/tasks/TASK_ID/validation.json`
   - `.symphony/tasks/TASK_ID/validation.md`
   - `.symphony/tasks/TASK_ID/proof_of_work.md`

5. Accept, reject, or write a follow-up task based on the proof-of-work recommendation.

   ```bash
   python runtime/hermes_symphony.py accept --task-id TASK_ID
   python runtime/hermes_symphony.py reject --task-id TASK_ID
   ```

## Safety

- The worker prompt tells Codex to work only inside `.symphony/workspaces/TASK_ID/`.
- The runtime rejects empty diffs, forbidden path edits, forbidden patterns, and outside-scope edits.
- For trading tasks, set `safety_profile: trading` to reject live-execution and credential-risk
  changes.

## Worker Modes

- `codex_once`: default for normal implementation tasks.
- `codex_autoresearch`: use only when `metric`, `autoresearch`, `verify_command`, and
  `guard_command` are present and deterministic.
- `codex_review`: use for review-only tasks; it should not edit files unless explicitly requested.

## Commands

```bash
python runtime/hermes_symphony.py status
python runtime/hermes_symphony.py validate --task-id TASK_ID
python runtime/hermes_symphony.py report --task-id TASK_ID
python runtime/hermes_symphony.py daemon --once --mock-worker
```

## Sample Hermes Prompts

```text
Use hermes-symphony to create and enqueue a codex_once task for this repo.
Goal: add a small local dashboard app.
Allowed scope: .
Verify command: pytest -q.
Guard command: python -m compileall .
```

```text
Use hermes-symphony to create and enqueue a codex_autoresearch task.
Goal: reduce failing pytest tests.
Metric command: pytest -q.
Metric parser: failing_tests.
Metric direction: lower.
Metric target: 0.
Allowed scope: src/, tests/.
Verify command: pytest -q.
Guard command: python -m compileall .
```
