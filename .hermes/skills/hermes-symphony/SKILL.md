---
name: hermes-symphony
description: "Install and operate the Hermes Symphony orchestration runtime for isolated Codex, Codex Autoresearch, and review workers."
---

# hermes-symphony

Use this skill when Hermes needs to orchestrate app or feature work through isolated Codex workers.

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
