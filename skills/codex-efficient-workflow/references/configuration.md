# Configuration and runtime support

Config is per project: `.codex-efficient-workflow/config.json`. State, pending candidates and audit receipts live alongside it. Never put credentials in these files. The Python helper needs Python 3.9+ and only the standard library. Paths below are relative to the installed skill, not the current project.

## Quick commands

```sh
python3 <skill>/scripts/workflow.py init --project <project>
python3 <skill>/scripts/workflow.py status --project <project>
python3 <skill>/scripts/workflow.py set-role --project <project> \
  --role executor --model gpt-6-luna --effort high
python3 <skill>/scripts/workflow.py generate --project <project>
```

`set-role` defaults to `pinned`; use `--update-mode auto_major` to opt back into automatic verified generation upgrades. When changing provider/family, supply `--provider`, `--family`, and `--generation`; do not let an old family label describe an unrelated model. Direct editing supports custom role instructions and limits; run status to validate afterward. A live user choice also wins over stored defaults; persist it only when asked to save it.

Default planner is Astra, bounded executor is Luna, integration executor is Sol. They are dated suggestions, not a globally optimal combination or account-access guarantee. Match models and effort to the currently exposed runtime. The coordinator/parent remains the model selected in the Codex UI; users can choose a lighter coordinator, with strong planning delegated only when needed. This skill cannot make already-spent parent reasoning free.

`family` is a user/vendor-confirmed succession line and `generation` is its vendor-confirmed major generation, not semantic version parsing. GPT-6 and GPT-6.1 share generation 6 in these defaults. Renamed successors can be mapped explicitly after official confirmation.

## Runtime application

`generate` creates only `.codex/agents/cew-planner.toml`, `cew-executor.toml`, `cew-executor-complex.toml`, and `cew-reviewer.toml`. It verifies hashes before replacing its own files. If a user edits one, generation stops without overwriting it: move/rename the customized file or put those instructions in workflow config, then retry. It never rewrites `.codex/config.toml`, enables permissions, or changes provider credentials. Config-only changes and runtime-generated changes are separate steps.

In an interface exposing explicit per-spawn model/effort, send both and use fresh minimal context. Some interfaces expose role selection instead. Use discovered `cew_*` roles when selectable; do not fabricate a role or model parameter. A new client/session may be needed to discover newly written TOML. Check a trace/status where possible; when the runtime does not expose actual model identity, mark it unverified rather than claiming a confirmed cost saving.

Different vendors are supported in config and update receipts, but the host must actually support their models. These scripts never create a cross-provider transport. With Codex native OpenAI authentication, a Claude/DeepSeek model string alone is not an integration. Provider changes are manual and follow current official runtime guidance.

## Configuration fields

| Field | Effect |
|---|---|
| `roles.*.model`, `reasoning_effort` | Exact requested model and effort; availability checked at invocation |
| `roles.*.instructions` | Custom role behavior |
| `roles.*.update_mode` | `auto_major` or `pinned` |
| `limits.max_parallel`, `max_dispatches` | Concurrency / total child turns per task; enforced by orchestrator instructions |
| `limits.same_model_repairs`, `max_escalations` | Repair / stronger-model ceilings |
| `limits.packet_target_chars` | Handoff size target; essential requirements must remain intact |
| `updates.check_interval_days` | Successful model-check cache duration |
| `updates.retry_interval_hours` | Backoff after failed/offline check |
| `updates.min_eval_cases` | Minimum paired trials for an upgrade; default 3 is a smoke gate, not a statistical guarantee |
| `updates.max_quality_drop` | Allowed acceptance-rate regression, default zero |
| `updates.min_acceptance_rate` | Candidate acceptance-rate floor, default 1.0 |
| `updates.max_usage_ratio` | Candidate/baseline measured usage, default at most 1 |
| `updates.allowed_source_hosts` | Exact official hosts used for update evidence; extend explicitly for another supplier |

Status prints config and timestamps. Limits are not billing enforcement: the helper has no model-call interception. Keep actual runtime/account spend controls if hard billing caps are needed.

## Sources

Runtime behavior checked on 2026-10-08:
- https://learn.chatgpt.com/docs/agent-configuration/subagents
- https://learn.chatgpt.com/docs/build-skills
- https://learn.chatgpt.com/docs/config-file/config-reference

Recheck docs when the client changes. API model availability/pricing does not establish Codex subscription eligibility or quota.
