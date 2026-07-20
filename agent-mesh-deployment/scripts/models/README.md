# Model Configuration Adjustments (SAM v2)

Scripts for adjusting Solace Agent Mesh (SAM) model
configurations. Rewritten for SAM v2: the platform is accessed
through the sam CLI (`sam api`) using the `sam auth login` token
cache -- no browser tokens, no CSRF handling.

## Files

- `set-max-tokens.sh` -- set the max output tokens on a model
  configuration.

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
