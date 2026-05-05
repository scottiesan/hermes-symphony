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

Steps:
1. Clone the repo into a temporary directory.
2. Run: python scripts/install_hermes_skill.py --overwrite
3. Verify this file exists: ~/.hermes/skills/hermes-symphony/SKILL.md
4. Verify this runtime exists: ~/.hermes/skills/hermes-symphony/runtime/hermes_symphony.py
5. Report the installed path and tell me to restart Hermes so the skill is loaded.
```

Expected agent behavior:

1. Clone `https://github.com/scottiesan/hermes-symphony`.
2. Run `python scripts/install_hermes_skill.py --overwrite`.
3. Verify `~/.hermes/skills/hermes-symphony/SKILL.md`.
4. Tell you to restart Hermes so the skill is loaded.

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
~/.hermes/skills/hermes-symphony
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
