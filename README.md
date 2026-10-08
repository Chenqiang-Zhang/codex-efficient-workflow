# Codex Efficient Workflow

[English](README.md) | [简体中文](README.zh-CN.md)

A configurable planner–executor skill for Codex. Use capable models where judgment matters, lighter models for bounded work, and explicit acceptance checks before calling a task complete.

The goal is to reduce redundant reasoning, context transfer, and unsuccessful retries while maintaining task quality. **MIT licensed. No fixed savings claim.**

Version: **0.1.0** · Authored and runtime documentation checked: **2026-10-08T05:17:59Z**.

## Quick start

After installing the skill, ask Codex:

```text
Use $codex-efficient-workflow to complete this task.
Use gpt-6-astra for planning and gpt-6-luna for execution.
Escalate only when integration work or a failed check reveals a capability gap.
```

You can customize it in natural language:

```text
Use $codex-efficient-workflow to pin the executor to my chosen model.
Keep automatic major-generation upgrades enabled for the planner.
Check every seven days; retain the current model if quality or usage checks fail.
```

The dated defaults use Astra for planning, Luna for bounded execution, and Sol for complex execution and review. They are starting points, not a ranking of the best-value models. Check availability in your actual Codex client and account.

## How it works

| Task | Workflow |
|---|---|
| Simple, clear task | Complete directly in the parent agent |
| Bounded implementation | Use one executor; verify its evidence |
| Ambiguous or architectural task | Obtain a concise plan, then execute it |
| Integration or difficult debugging | Start with the complex executor |
| Subtle or consequential change | Add a targeted review where needed |

Defaults allow at most two concurrent children, six total child dispatches or resumed turns per task, one same-model repair, and one escalation. Handoffs include only the objective, scope, necessary context, constraints, and acceptance checks. Planning and review are used when they add value.

These limits guide orchestration; they are not a hard token cap or billing interceptor. The parent remains the model selected in the Codex UI.

## Installation

Requirements: a Codex client with subagent support and Python 3.9+. The helper uses only the Python standard library. It does not require an API key, call model APIs, or install dependencies.

Copy the complete `skills/codex-efficient-workflow/` directory into the user skill directory supported by your client, for example `~/.codex/skills/codex-efficient-workflow/`. Current official documentation also lists `~/.agents/skills/` for user-level discovery. Follow the documentation for your installed client and install into one supported location to avoid duplicates.

Invoke `$codex-efficient-workflow` on the next turn. If it is not discovered, reopen the session or client. Installation does not change global models, provider credentials, or permissions.

For manual setup, set `SKILL_DIR` to the installed skill directory and `PROJECT_DIR` to your project or projectless working directory:

```sh
python3 "$SKILL_DIR/scripts/workflow.py" init --project "$PROJECT_DIR"
python3 "$SKILL_DIR/scripts/workflow.py" status --project "$PROJECT_DIR"
python3 "$SKILL_DIR/scripts/workflow.py" generate --project "$PROJECT_DIR"
```

The last command generates project-local `.codex/agents/cew-*.toml` files. A new session may be needed to discover them. When the exposed delegation tool supports per-spawn settings, the skill specifies model and reasoning effort directly. Otherwise, it uses custom roles that the runtime has actually discovered and can select. Generated files alone do not prove runtime activation.

## Customize roles and budgets

Configuration lives in `.codex-efficient-workflow/config.json` within your project. It controls role models, reasoning effort, instructions, update policies, concurrency/retry limits, refresh intervals, and quality/usage gates.

```sh
# A manual choice is pinned by default.
python3 "$SKILL_DIR/scripts/workflow.py" set-role --project "$PROJECT_DIR" \
  --role executor --model gpt-6-luna --effort high

# Explicitly allow verified major-generation upgrades for this role.
python3 "$SKILL_DIR/scripts/workflow.py" set-role --project "$PROJECT_DIR" \
  --role executor --update-mode auto_major

# Synchronize owned project agent files after a config change.
python3 "$SKILL_DIR/scripts/workflow.py" generate --project "$PROJECT_DIR"
```

Pinned models are preserved during automatic refresh. Live user instructions take precedence over saved settings. Edit custom instructions and limits in JSON, then run `status` to validate.

Provider changes require explicit provider, family, and generation settings, plus actual runtime support. A model string does not create a cross-provider integration. See the [configuration reference](skills/codex-efficient-workflow/references/configuration.md).

## Timestamped model updates

During active use, the skill checks when the last successful model review occurred. The default interval is seven days, with a 24-hour retry backoff after a failed or offline check. **It is not a background monitor and does not create scheduled jobs.**

For a vendor-confirmed major generation in the same configured provider/family, the skill checks official release evidence, stable status, actual account/runtime availability, supported reasoning settings, and paired quality/usage evaluations.

By default, an upgrade needs at least three paired cases, full candidate acceptance, no acceptance-rate regression, and no increase in measured total usage. Three cases are an initial smoke gate, not a statistical guarantee; use more representative cases for consequential work.

Eligible `auto_major` roles are updated with UTC timestamps, official sources, evaluation evidence, configuration fingerprints, audit records, and backups for rollback. Missing evaluation, unknown usage, unavailable models, preview releases, or unverified announcements leave candidates pending and preserve the current configuration. Apply updates to subsequent dispatches after active work finishes.

API dollars, token counts, and subscription quota are separate metrics. Unknown usage is recorded as unknown, never zero. The helper validates receipt structure, freshness, official source hostnames, configuration consistency, and migration gates. It does not browse, authenticate model availability, or independently establish receipt truthfulness. Codex or the operator must collect real evidence.

See [model refresh and rollback](skills/codex-efficient-workflow/references/model-refresh.md).

## Testing and validation

From the repository root:

```sh
python3 -m unittest discover -s tests -v
```

Tests cover check caching/backoff, pinned models, minor versus major updates, incomplete source coverage, unavailable/preview candidates, quality/usage gates, stale configuration, backups and rollback, generated-file conflicts, and path boundaries.

The initial release passed **27 behavior tests on Python 3.12** and the official Skill Creator format validator. Generated TOML parsing is tested when Python 3.11+ provides `tomllib`; the helper itself supports Python 3.9+. See [validation details](VALIDATION.md).

No paid-model quality/usage benchmark has been run, so no percentage saving is claimed. Automated tests validate helper behavior; they do not prove quality for every future task. Example receipts in `skills/codex-efficient-workflow/assets/examples/` are synthetic and marked `fixture: true`; they cannot qualify for a real migration.

## Contributing and reuse

The repository includes the self-contained skill, helper, examples, tests, MIT license, and GitHub Actions configuration for Python 3.9, 3.11, and 3.13. CI configuration does not mean hosted CI has run.

Include a reproducible case, client/Python versions, and sanitized input in issues or pull requests. Add behavior tests when changing migration or file-writing logic. Keep credentials, private prompts, and project run receipts out of commits; see [.gitignore](.gitignore).

Reuse and modification are permitted under the [MIT License](LICENSE). This is a community skill, not an official OpenAI product.

## Official references

Checked on 2026-10-08:

- [Codex subagents](https://learn.chatgpt.com/docs/agent-configuration/subagents)
- [Build skills](https://learn.chatgpt.com/docs/build-skills)
- [Configuration reference](https://learn.chatgpt.com/docs/config-file/config-reference)

Recheck relevant documentation when upgrading your runtime; configuration and model availability can evolve.
