# Hermes Symphony Quickstart

## Create A Task

Copy `.hermes/skills/hermes-symphony/templates/task.yaml` or use an example:

```bash
python scripts/hermes_symphony.py enqueue examples/build-dashboard-app.yaml
```

## Run One Task

```bash
python scripts/hermes_symphony.py run --task-id build-dashboard-app
```

For tests or dry runs without Codex:

```bash
python scripts/hermes_symphony.py run --task-id build-dashboard-app --mock-worker
```

## Run The Daemon

```bash
python scripts/hermes_symphony.py daemon --queue .symphony
```

One-cycle dry run:

```bash
python scripts/hermes_symphony.py daemon --queue .symphony --once --mock-worker
```

## Inspect Results

```bash
python scripts/hermes_symphony.py status
python scripts/hermes_symphony.py validate --task-id build-dashboard-app
python scripts/hermes_symphony.py report --task-id build-dashboard-app
```

Artifacts are written under:

- `.symphony/tasks/<task_id>/worker_prompt.md`
- `.symphony/tasks/<task_id>/worker.log`
- `.symphony/tasks/<task_id>/validation.json`
- `.symphony/tasks/<task_id>/validation.md`
- `.symphony/tasks/<task_id>/proof_of_work.md`

Accept or reject review tasks:

```bash
python scripts/hermes_symphony.py accept --task-id build-dashboard-app
python scripts/hermes_symphony.py reject --task-id build-dashboard-app
```

Operational events are appended to `.symphony/logs/events.jsonl`.

## Queue Layout

```text
.symphony/
  inbox/
  active/
  blocked/
  review/
  done/
  failed/
  tasks/
  workspaces/
```

## Known Limitations

- v1 is single-process and local-file backed.
- GitHub Issues and Linear adapters are design placeholders.
- Codex app-server streaming is not implemented yet.
- Workspace cleanup is manual.
