# Model Configuration (SAM v2)

Scripts and declarative configs for Solace Agent Mesh (SAM)
model configurations. The platform is accessed through the sam
CLI using the `sam auth login` token cache -- no browser tokens,
no CSRF handling.

## Files

- `set-max-tokens.sh` -- set the max output tokens on a
  (chart-seeded) model configuration.
- `manifest.yaml` + `models/*.yaml` -- declarative definitions of
  the five additional model aliases (`workflow`, `reasoning`,
  `coding`, `expert`, `fast`).
- `apply-models.sh` -- applies the declarative package
  (idempotent create-or-update) and probes every model upstream
  with a 1-token call. Called automatically by `start.sh` after
  the pods are ready; `--probe-only` runs just the health probes
  (pre-flight check).

## Additional models

Five aliases extend the chart-seeded set for per-task model
selection. All run through the same LiteLLM proxy and API key
(`LLM_SERVICE_API_KEY` from `.env`, substituted at apply time):

- `workflow` -- Claude Sonnet 5, `max_tokens` 32768. Fast,
  reliable tool use and merge steps in event-triggered
  pipelines; 1M input context makes it the long-context option.
  The Order Incident Reporter agent runs on it (multi-model
  demo beat).
- `reasoning` -- DeepSeek V3.2, `max_tokens` 8192,
  `temperature` 1.0 (DeepSeek's official recommendation for
  data analysis in non-thinking mode; 8192 is the V3.2 output
  ceiling).
- `coding` -- Qwen3 Coder Next, `max_tokens` 8192,
  `temperature` 0.7, `top_p` 0.8 (Qwen's official Qwen3-Coder
  sampling; 8192 is the proxy's published output ceiling).
- `expert` -- Claude Opus 5, `max_tokens` 32768. Escalation
  tier; adaptive thinking counts inside `max_tokens`, so 16384
  would truncate.
- `fast` -- Claude Haiku 4.5, `max_tokens` 16384. Low-cost tier
  for high-volume routine tasks.

Parameter rules discovered while building this set (all verified
live against the proxy on 2026-07-31):

- The platform **normalizes model aliases to lowercase** on
  create -- declarative names must be lowercase or every apply
  re-plans a create.
- The Claude 5 family (Sonnet 5, Opus 5) **rejects**
  `temperature`, `top_p` and `top_k` with HTTP 400
  ("deprecated for this model") -- omit them entirely.
- `modelParams` is a free-form pass-through object; which
  parameters actually work depends on the model behind the
  proxy, so the params differ per model by design.
- The proxy's `azure-*` and `gemini-*` routes have broken
  backend credentials (Azure subscription key, Google service
  account -- final state). That is why the set is
  Claude / DeepSeek / Qwen; `deepseek-v4-pro` also runs over
  the broken Azure route.

## Background: max output tokens

`max_tokens` is the **maximum output length** of a single model
response, not the context window. In SAM it lives on the model
configuration as `modelParams.max_tokens` and applies to every
agent that uses that model.

### Why it matters (v2 status)

The v2 Helm chart seeds the model configurations (`general`,
`planning`, `report_gen`, `image_gen`) with **empty
`modelParams`**, so the low LiteLLM-proxy default output limit
applies -- the same state that caused the v1 incident: an agent
inlining a large SQL result into a tool call exceeded the default,
the tool-call JSON was truncated mid-string, the agent retried
until the per-task LLM-call limit and the user saw a generic
"temporary service issue". Setting `max_tokens` removes that
failure mode.

### Choosing a value

`max_tokens` is a ceiling, not a reservation: you are billed only
for tokens actually generated. Maximum output caps differ by
provider (verify against current provider docs or the LiteLLM
model metadata):

- Anthropic: Opus 4.8 / 4.7 / 4.6 and Fable 5 = 128K; Sonnet 4.6
  and Haiku 4.5 = 64K.
- OpenAI: GPT-5 and o-series around 128K; GPT-4.1 = 32K; GPT-4o
  and 4o-mini = 16,384; GPT-4 Turbo = 4,096.
- Google: Gemini 2.5 Pro and Flash = 64K; Gemini 2.0 and
  1.5 = 8,192.

Practical choices:

- `8192` -- safe on every current model.
- `16384` -- the default here: clears the truncation with
  headroom and stays portable across Anthropic, OpenAI (incl.
  GPT-4o) and Google frontier models.
- `32768` -- only if you never route to GPT-4o.

### Applying the change

Agents and workflows run in the Agent-Workflow Executor (awe) and
read the model configuration at startup via the model bootstrap
queues. A model update alone does not affect running agents --
`set-max-tokens.sh` restarts the awe deployment automatically
unless `--no-restart` is passed.

## Prerequisites

- The sam CLI (resolved by `../lib/common.sh`: `SAM_CLI_PATH`,
  then PATH, then auto-extract from `SAM_CLI_TAR`) and a login as
  an admin user:

  ```bash
  sam auth login solace-lab --url https://sam.solace.lab
  ```

- `python3`, and `kubectl` for the automatic restart.

## CLI usage

Run from this directory:

```bash
# Set max_tokens to the default (16384) and restart the agents
./set-max-tokens.sh

# Set a specific value
./set-max-tokens.sh 32768

# Show current + intended values, change nothing
./set-max-tokens.sh --dry-run

# Patch the model but do not restart the agents
./set-max-tokens.sh --no-restart 16384

# Target a different model alias (default: general)
./set-max-tokens.sh --model-alias planning 16384
```

### Environment variables

- `MODEL_ALIAS` -- model alias to update (default `general`).
- `SAM_NAMESPACE` -- Kubernetes namespace for the restart
  (default `sam-solace-lab`).

## Declarative alternative

Models are also a `sam config` kind. Instead of this script, a
`models/general.yaml` (`kind: model` with
`spec.modelParams.max_tokens`) can be managed in a config repo and
applied via `sam config apply`. Note that the model carries
`authConfig.api_key`, so the API-key env var must be provided at
every apply -- for a one-time tuning knob the script is simpler,
which is why this directory keeps the script approach.

## Notes

- The update merges `max_tokens` into the existing `modelParams`,
  preserving other parameters; `authConfig` is not touched.
- The change applies to every agent using the target model alias.
- Helm re-seeding is create-if-missing and does not overwrite an
  existing model configuration, so the value survives restarts
  and upgrades.
