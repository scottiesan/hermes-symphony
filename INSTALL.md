# Install Hermes Symphony From GitHub

Give a Hermes agent this repository URL:

```text
https://github.com/scottiesan/hermes-symphony
```

Then ask it to install the `hermes-symphony` skill.

## Hermes TUI Install Command

Paste this command into Hermes TUI:

```text
/skills install scottiesan/hermes-symphony/.hermes/skills/hermes-symphony --now
```

If it is already installed and you want to update it:

```text
/skills install scottiesan/hermes-symphony/.hermes/skills/hermes-symphony --force --now
```

## Hermes TUI Natural-Language Prompt

```text
Install the Hermes Symphony skill using Hermes Skills Hub.
Run:
/skills install scottiesan/hermes-symphony/.hermes/skills/hermes-symphony --now

If it is already installed, run:
/skills install scottiesan/hermes-symphony/.hermes/skills/hermes-symphony --force --now

Then verify the skill appears in /skills list and tell me whether I need to restart Hermes or run /reload-skills.
```

## CLI Equivalent

Outside TUI:

```bash
hermes skills install scottiesan/hermes-symphony/.hermes/skills/hermes-symphony --yes
```

## Fallback Manual Install

Use this only if Hermes Skills Hub is unavailable:

```bash
git clone https://github.com/scottiesan/hermes-symphony
cd hermes-symphony
python scripts/install_hermes_skill.py --overwrite
```

Fallback installer default destination:

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
