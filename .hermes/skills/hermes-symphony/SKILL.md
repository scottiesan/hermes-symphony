# hermes-symphony

Use this skill when Hermes needs to orchestrate app or feature work through isolated Codex workers.

## Workflow

1. Create a task contract from `.hermes/skills/hermes-symphony/templates/task.yaml`.
2. Enqueue it:

   ```bash
   python scripts/hermes_symphony.py enqueue path/to/task.yaml
   ```

3. Run one task or start the daemon:

   ```bash
   python scripts/hermes_symphony.py run --task-id TASK_ID
   python scripts/hermes_symphony.py daemon --queue .symphony
   ```

4. Inspect generated artifacts:

   - `.symphony/tasks/TASK_ID/validation.json`
   - `.symphony/tasks/TASK_ID/validation.md`
   - `.symphony/tasks/TASK_ID/proof_of_work.md`

5. Accept, reject, or write a follow-up task based on the proof-of-work recommendation.

   ```bash
   python scripts/hermes_symphony.py accept --task-id TASK_ID
   python scripts/hermes_symphony.py reject --task-id TASK_ID
   ```

## Safety

- The worker prompt tells Codex to work only inside `.symphony/workspaces/TASK_ID/`.
- The runtime rejects empty diffs, forbidden path edits, forbidden patterns, and outside-scope edits.
- For trading tasks, set `safety_profile: trading` to reject live-execution and credential-risk
  changes.

## Commands

```bash
python scripts/hermes_symphony.py status
python scripts/hermes_symphony.py validate --task-id TASK_ID
python scripts/hermes_symphony.py report --task-id TASK_ID
python scripts/hermes_symphony.py daemon --once --mock-worker
```
