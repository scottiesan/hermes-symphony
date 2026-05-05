# Install Hermes Symphony From GitHub

Give a Hermes agent this repository URL:

```text
https://github.com/scottiesan/hermes-symphony
```

Then ask it to install the `hermes-symphony` skill.

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
