# Hermes Symphony vs OpenAI Symphony

OpenAI Symphony is a language-agnostic SPEC plus an experimental Elixir/OTP reference
implementation. The reference implementation polls Linear, creates workspaces, launches Codex
app-server sessions, and keeps agents working through tracker state transitions.

Hermes Symphony v1 follows the SPEC's architecture but changes the integration surface:

| Area | OpenAI Symphony Elixir | Hermes Symphony v1 |
| --- | --- | --- |
| Source of work | Linear project polling | Local YAML/JSON task queue |
| Runtime | Elixir/OTP service | Python CLI and polling daemon |
| Worker | Codex app-server | Codex CLI command first, plus optional Codex Autoresearch |
| Policy | `WORKFLOW.md` | `WORKFLOW.md` plus `HERMES_WORKFLOW.md` |
| Workspace | Per-issue workspace | Per-task workspace under `.symphony/workspaces/` |
| Handoff | Tracker/PR workflow | `proof_of_work.md` for Hermes review |
| Adapters | Linear built in | Local built in, GitHub/Linear placeholders |

## Why Not Vendor Elixir

The Elixir implementation is explicitly a prototype and recommends hardened implementations based
on `SPEC.md`. Hermes needs first-class local queue artifacts, proof-of-work review, and Codex CLI
dispatch. Porting the SPEC gives Hermes a smaller trusted base and avoids requiring Linear or BEAM
for local orchestration.

## Future Compatibility

Hermes can add:

- Linear polling by implementing `LinearTaskSource`.
- GitHub issue polling by implementing `GitHubIssueTaskSource`.
- Codex app-server streaming by adding a second worker dispatcher.
- Additional optimization strategies by extending worker modes while preserving final Symphony
  validation.
- A richer status surface over the current `.symphony/tasks/` artifacts.
