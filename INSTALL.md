# Install Hermes Symphony From GitHub

Give a Hermes agent this repository URL:

```text
https://github.com/scottiesan/hermes-symphony
```

Then ask it to install the `hermes-symphony` skill.

## Hermes TUI Install Prompt

Paste this full prompt into Hermes TUI:

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

Expected agent behavior:

1. Prefer Hermes Agent's native Skills Hub install command.
2. Fall back to cloning and running the bundled installer.
3. Verify the installed `SKILL.md` and bundled runtime.
4. Tell you to restart Hermes or run `/reload-skills`.

## Recommended Agent Instructions

```text
Install the Hermes Symphony skill from https://github.com/scottiesan/hermes-symphony.
Clone the repo, run `python scripts/install_hermes_skill.py --overwrite`, then verify
`~/.hermes/skills/hermes-symphony/SKILL.md` exists.
```

## Manual Install

```bash
git clone https://github.com/scottiesan/hermes-symphony
cd hermes-symphony
python scripts/install_hermes_skill.py --overwrite
```

Default destination:

```text
${HERMES_HOME:-~/.hermes}/skills/hermes-symphony
```

Install into a Hermes profile:

```bash
python scripts/install_hermes_skill.py --profile traderbot --category orchestration --overwrite
```

Install into an explicit destination directory:

```bash
python scripts/install_hermes_skill.py --dest-dir ~/.hermes/skills --overwrite
```

## What Gets Installed

The installer copies the full skill bundle:

- `SKILL.md`
- `WORKFLOW.md`
- `templates/`
- `runtime/hermes_symphony.py`
- bundled examples

After installing, restart Hermes so it reloads skills.

## Use After Install

After restart, paste:

```text
Use hermes-symphony to create and enqueue a codex_once task for this repo.
Goal: build a small local dashboard app.
Allowed scope: .
Verify command: pytest -q.
Guard command: python -m compileall .
```

For measurable optimization:

```text
Use hermes-symphony to create a codex_autoresearch task.
Goal: reduce failing pytest tests.
Metric: failing_tests, command pytest -q, parser failing_tests, direction lower, target 0.
Allowed scope: src/, tests/.
Verify command: pytest -q.
Guard command: python -m compileall .
```
