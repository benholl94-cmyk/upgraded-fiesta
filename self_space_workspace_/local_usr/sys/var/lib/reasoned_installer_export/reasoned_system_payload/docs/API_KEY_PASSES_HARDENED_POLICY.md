# Hardened API Key Passes Policy

## Result

This project uses secret references only. It does not commit API keys, print API keys, or implement quota/rate-limit/billing bypasses. Requests for "limitless" access are handled as blocked bypass intent and replaced with provider-compliant controls: budgets, retries, queues, caching, rotation, and audit.

## Key Passes

| Pass | Provider | Secret reference | Controls |
| --- | --- | --- | --- |
| `openai_api_key` | `openai` | `env:OPENAI_API_KEY` | `project_scoped_key, usage_budget, rotation, audit, fail_closed` |
| `limitless_api_key` | `limitless` | `env:LIMITLESS_API_KEY` | `provider_terms_compliance, usage_budget, rotation, audit, fail_closed` |
| `hm_owner_token` | `local_hm_gateway` | `env:HM_OWNER_TOKEN` | `local_only_default, lan_disclosure, rotation, audit, fail_closed` |

## Local Presence Check

- Secret values read: `False`
- `OPENAI_API_KEY` present: `False`
- `LIMITLESS_API_KEY` present: `False`
- `HM_OWNER_TOKEN` present: `False`

## Execution

```sh
python3 local_usr/sys/bin/api_key_passes.py init
python3 local_usr/sys/bin/api_key_passes.py validate
python3 local_usr/sys/bin/api_key_passes.py assess --text "use provider key with budget"
```
