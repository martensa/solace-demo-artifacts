# Model Configuration Adjustments

Note: written against the SAM v1 platform API (enterprise
1.543.0); unverified on v2. In v2 the `llmService.*` Helm values
seed the model configurations at startup, and models can also be
managed declaratively via `sam config apply` (model kind).

Scripts for adjusting Solace Agent Mesh (SAM) model configurations through the
SAM Platform REST API. Add further model and runtime tuning scripts of this
kind to this directory.

## Files

- `set-max-tokens.sh` -- set the max output tokens on a model configuration.

## Background: max output tokens

`max_tokens` is the **maximum output length** of a single model response, not
the context window. In SAM it lives on the model configuration as
`modelParams.max_tokens` and applies to every agent that uses that model.

### Why it matters

When `modelParams` is empty, the model uses a low provider default (around
2,000 output tokens). An agent that returns a large result -- for example a SQL
agent inlining a big dataset into a tool call -- can exceed that default. The
tool-call JSON is then truncated mid-string, the agent retries the failed
artifact operation, and it keeps retrying until it hits the per-task LLM-call
limit (20). The user sees this as a generic "temporary service issue".

Raising `max_tokens` gives the model room to emit the full tool call and
removes that failure mode. The more robust fix for very large results is to
bound the query itself (LIMIT, aggregation, fewer columns) so the agent does
not try to inline a huge payload at all.

### Choosing a value

`max_tokens` is a ceiling, not a reservation: you are billed only for the
tokens actually generated, so a higher value does not cost more on a normal
response. Its two jobs are portability across providers and acting as a safety
limit against runaway or oversized outputs.

Maximum output caps differ by provider. The Anthropic values are from the
official reference; verify OpenAI and Google against their current docs, or the
LiteLLM model metadata, which exposes `max_output_tokens` per model:

- Anthropic: Opus 4.8 / 4.7 / 4.6 and Fable 5 = 128K; Sonnet 4.6 and
  Haiku 4.5 = 64K.
- OpenAI: GPT-5 and o-series around 128K; GPT-4.1 = 32K; GPT-4o and
  4o-mini = 16,384; GPT-4 Turbo = 4,096.
- Google: Gemini 2.5 Pro and Flash = 64K; Gemini 2.0 and 1.5 = 8,192.

A portable value must be at most the smallest output cap of any model you route
to. Practical choices:

- `8192` -- safe on every current model, including GPT-4o and Gemini 1.5.
- `16384` -- the default here. Clears the truncation with headroom and stays
  within all current frontier models plus GPT-4o.
- `32768` -- only if you never route to GPT-4o (whose cap is 16,384).
- `65536` -- frontier and reasoning models only.

`16384` is the default because it removes the truncation failure mode while
keeping a useful safety ceiling and staying portable across Anthropic, OpenAI
and Google models. Larger values do not help tool-calling agents, and a single
response rarely needs more than 16K legitimate output tokens.

### Applying the change

Agents read the model configuration once, at startup, through the model
bootstrap flow. A REST update alone does not affect running agents -- the agent
pods must restart to re-read the configuration. `set-max-tokens.sh` restarts
them automatically unless `--no-restart` is passed.

## Prerequisites

- `curl` and `jq` on the PATH.
- `kubectl` (only for the automatic pod restart).
- A logged-in SAM session in Chrome (for automatic token detection), or a
  token passed explicitly.

## CLI usage

Run from this directory:

```bash
# Set max_tokens to the default (16384) and restart the agents
./set-max-tokens.sh

# Set a specific value
./set-max-tokens.sh 32768

# Pass the token explicitly (also: --token)
./set-max-tokens.sh -t '<sam_access_token>' 16384

# Provide the token through the environment
SAM_TOKEN='<sam_access_token>' ./set-max-tokens.sh 16384

# Resolve and report only; change nothing
./set-max-tokens.sh --dry-run 16384

# Patch the model but do not restart the agents
./set-max-tokens.sh --no-restart 16384

# Target a different model alias (default: general)
./set-max-tokens.sh --model-alias planning 16384
```

Token resolution order: `-t/--token`, then `SAM_TOKEN`, then Chrome
localStorage.

### Environment variables

- `SAM_BASE` -- API base URL (default `https://sam.solace.lab`).
- `MODEL_ALIAS` -- model alias to update (default `general`).
- `SAM_NAMESPACE` -- Kubernetes namespace for the restart (default
  `sam-solace-lab`).

## Getting the token

The script reads the token automatically from Chrome. To pass it manually,
open the DevTools console on a logged-in SAM tab and run:

```js
copy(localStorage.getItem('sam_access_token'))
```

The token is short-lived (about one hour).

## Notes

- The update merges `max_tokens` into the existing `modelParams`, preserving
  any other parameters already set on the model.
- The model's credentials (`authConfig`) are not touched.
- The change applies to every agent that uses the target model alias.
