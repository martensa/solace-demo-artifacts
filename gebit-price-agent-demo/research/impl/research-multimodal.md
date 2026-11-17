# Multimodal capabilities for the GEBIT price agent demo (SAM 2.542.1 + LiteLLM)

Track report, written 2026-11-10. Scope: what SAM 2.542.1 offers for
images, audio and documents, what works today through the LiteLLM proxy,
and which 3-4 multimodal features fit the EuroCIS "Preis- und Aktionsagent
mit Freigabe" (MHD dropped, price changes with several triggers).

Nothing on the lab was changed: kubectl get/exec read-only (`cat`, `env`
key names, `grep` on the awe binary, one `SELECT` on
`model_configurations` without the auth column), no `sam config apply`,
no broker or DB writes. Probes against the LiteLLM proxy were small
inference calls with synthetic, brand-free test images (about 15 vision
calls, 2 image generations, 1 transcription; well under 0.20 USD).

Legend: **[V]** verified (source or probe given), **[A]** assumption /
expert estimate, **[S]** must be proven in a lab spike before it is relied
on.

Abbreviations: `DOCS` = scratchpad `samdocs/` (2.542.1 CLI docs),
`SKILL` = scratchpad `review-sam/skills2542/`, `CLI` = strings embedded in
`~/.local/bin/sam` 2.542.1 (excerpts in `impl/mm/cli-doc-*.txt`, local),
`AWE` = strings in `/usr/local/bin/sam-awe` inside the awe pod,
`MM` = `impl/mm/` (probe scripts and results).

---

## 0. Summary

- **Vision works today, end to end at the model level [V].** Claude Haiku
  4.5 (`fast`), Sonnet 5 (`workflow`) and Haiku 5.5 read images through
  the LiteLLM proxy in OpenAI chat format (`image_url` data URI): 1.5-2.1 s
  (Haiku 4.5), about 2.0 s (Haiku 5.5), 2.7-3.2 s (Sonnet 5) per call with
  one 1280x720 image (about 1.3k prompt tokens). Competitor tag, product
  identification and shelf-label check were all read correctly
  (`MM/vision_results.jsonl`).
- **Image generation, speech-to-text and Gemini via the proxy answer
  today [V]**, contrary to the memory/README note "gemini-* and azure-*
  routes permanently broken": `imagen-3` (Vertex gemini-2.5-flash-image)
  7.7 s, `gpt-image-2.5-flare` (Azure) 17.5 s for 1024x1024, `whisper`
  (Azure) 1.7 s for a 5 s German clip, `gemini-3.6-flash` chat 2.1 s.
  These routes have broken before, so every feature needs an offline
  fallback. **No TTS route** (`tts-1` -> HTTP 403), and the native-Gemini
  tools (`generate_image_with_gemini`, `edit_image_with_gemini`,
  `text_to_speech`) are dead in the lab (`GEMINI_API_KEY` unset, AI Studio
  credits depleted).
- **How an image reaches a model inside SAM:** an image is always an
  artifact first. A workflow `agent` node has **no image input field**
  (only `decision` nodes have `images:`, and those only talk to
  TypeSafe/OpenAI/OpenRouter decision models, not to LiteLLM). An agent
  node gets the artifact *filename* in its `input` and sees the pixels via
  `load_artifact` (visual block) or via the `describe_image` tool. The
  fastest deterministic path is a `tool` node running `describe_image`
  (one vision call, no agent loop) [S].
- **Image transport into SAM from the booth apps:** the Event Mesh
  entrypoint has an advanced `artifactProcessing` block that extracts
  base64 content from the event JSON into artifacts of the dispatched
  task [V docs, S for workflow targets]. Fallbacks: route the photo event
  to an agent target, or let the Marktleitung tablet (which runs the SAM
  WebUI for native HITL anyway) upload the photo in chat with
  `enable_inline_vision`.
- **Recommendation (build order):**
  1. **"Wettbewerbspreis per Foto"** - a photographed competitor price tag
     becomes a new price-change TRIGGER (multimodal + trigger in one
     feature, highest value per effort).
  2. **"Regal-Check"** - a fixed camera verifies the e-paper label after
     the approved change and SAM sends a notification (closes the loop,
     fully automatic, uses Notifications).
  3. **"KI-Aktionsplakat"** - generated promo visual for the monitor and
     customer display after approval, price text overlaid in HTML,
     cached per article (high wow, run asynchronously).
  4. **"Foto-Scan an der Kasse"** - optional; too slow for the checkout
     path, only as an "article without barcode" moment.
- Six G0 spikes (section 5) decide the transport path; none needs more
  than a scratch agent/workflow on the lab.

---

## 1. What SAM 2.542.1 supports

### 1.1 Ways a file or image gets into SAM

| Path | What happens | Status |
|---|---|---|
| WebUI chat upload | Attach button or drag/paste; files become session artifacts; upload limit per project file 50 MB (`DOCS/using-agent-mesh__chatting.md:54-67`, `managing-projects.md:62`). With agent setting `enable_inline_vision` (`additionalConfigurations.enableInlineVision`, default **false**) uploaded images go straight into the model call, max 5 images / 20 MiB per message; `enable_inline_pdf` likewise for scanned PDFs (CLI agent doc, `MM/cli-doc-agent-limits.txt`). | [V docs], [S] with LiteLLM |
| Event Mesh entrypoint, `artifactProcessing` | Rule-level "[advanced] Extract artifacts from the incoming message and attach them to the dispatched task" (`review-sam/schema/ep_event_mesh.md:46`). Runtime keys: `artifact_processing.extract_artifacts_expression` (sacexpr, single item or list, e.g. `input.payload:attachments`), `artifact_definition.{filename, content, mime_type, content_encoding}` with `content_encoding` one of `base64`, `base64url`, `base64raw`, `base64rawurl`, `utf-8`; list items addressed as `list_item:<field>` (`MM/cli-doc-artifact-processing.txt`; error string "route %q: artifact_processing.extract_artifacts_expression is required"). The declarative camelCase spelling (`artifactProcessing.artifactDefinition...`) is only typed as `object` in the schema. | [V docs], [S] keys + workflow target |
| Event Mesh entrypoint, `messageFormat` | `json`, `text`, `xml`, `raw_bytes`, `protobuf`, `structured` (`DOCS/building__entrypoints__event-mesh.md:106-112`). `raw_bytes` alone does not make an image visible to a model. | [V] |
| Webhook entrypoint | No file or artifact handling documented (`DOCS/building__entrypoints__webhook.md`). | [V] (absent) |
| MCP tool result | "Image, audio, and resource content is always saved" as an artifact; any result over 2048 bytes saved (`mcp_tool_response_save_threshold_bytes`), over 4096 bytes replaced by a reference (`mcp_tool_llm_return_max_bytes`) (CLI agent doc). | [V docs] |
| `web_request` built-in | Binary bodies stored as-is as an artifact; SSRF check blocks loopback and **non-public** addresses unless `allow_loopback: true`; `max_response_size_bytes` default 10 MB, oversize is **truncated, not rejected** (`DOCS/reference__built-in-tools.md:333-347`, `SKILL/sam-author-agent/references/builtin-tools.md:28-32`). In-cluster service IPs are private, so fetching a photo from our own app is blocked by default. | [V], not recommended |
| `user:` filename prefix | Artifact stored per user instead of per session, so a booth app with a SAM token could upload once and a run of the same identity reads it (`SKILL/.../artifact-naming.md`). Needs a SAM token in the booth app. | [V docs], not recommended |
| Decision node `images:` | Up to 5 images, 20 MiB, PNG/JPEG/WebP, artifact name or `{{node.output.created_artifact}}`; **only** TypeSafe Jev, OpenAI decision or GPT-6 Luna Decisions models (`DOCS/building__workflows__decision-nodes.md:195-268`). LiteLLM's `microsoft-decision-1` is not one of them. | [V], not usable here |

### 1.2 How a model actually sees the pixels

- `load_artifact`: "Supported image types (PNG, JPEG, WEBP, GIF) up to
  20 MiB are attached as a visual block so a vision-capable model can see
  them directly" (`DOCS/reference__built-in-tools.md:62-76`). Costs one
  extra LLM turn (the tool call) [V docs].
- `artifact_handling_mode: embed` on the agent inlines tool-produced
  artifacts into history (`DOCS/concepts__artifacts.md:62-73`); with an MCP
  tool that returns an image this would save the `load_artifact` turn
  [S].
- `enable_inline_vision`: uploaded images in the incoming message go into
  the first model call (see 1.1) [V docs, S whether it also applies to
  artifacts attached by `artifactProcessing`].
- `describe_image` tool: one call to "an OpenAI-compatible vision API"
  (AWE string), result `description` (string), `image_filename`,
  `image_version` (`SKILL/.../builtin-tools.md:58`). The docs say "using
  the agent's configured multimodal LLM"; the binary also carries the
  generic errors "'model'/'api_key'/'api_base' configuration is missing in
  tool_config". Plan for an explicit `tool_config` pointing at LiteLLM
  [S].

All lab chat models are `provider: custom`, `modelName: openai/<name>`,
`apiBase: https://lite-llm.mymaas.net` (platform DB, read 2026-11-10), so
SAM speaks OpenAI chat format to LiteLLM, which maps to Bedrock Claude.
The probe proves LiteLLM accepts `image_url` data URIs for these models;
that SAM's visual block is emitted in that form is [S] (spike S2).

### 1.3 Built-in multimodal tools in the lab

| Tool (group) | Backend and config | Works in the lab? |
|---|---|---|
| `describe_image` (`builtin_image_tools`) | OpenAI-compatible vision; PNG, JPEG, WEBP, GIF (`DOCS/reference__built-in-tools.md:248-259`) | Model side yes [V probe]; SAM side [S] |
| `describe_audio` (`builtin_image_tools`) | multimodal audio model; WAV, MP3 (`:261-272`) | Claude has no audio input; `gemini-3.6-flash` on the proxy lists `supports_audio_input` and answered a text call [V]; audio itself [S]. Not needed. |
| `transcribe_audio` (YAML-only, by name) | `tool_config` `model`, `api_key`, `api_base`, OpenAI `/v1/audio/transcriptions`; WAV, MP3 (`:315-327`) | Proxy `whisper` OK, 1.7 s, perfect German transcript [V probe]; tool [S] |
| `create_image_from_description` (`builtin_image_tools`) | OpenAI-compatible `/v1/images/generations`, `tool_config` `model`, `api_key`, `api_base`, optional `extra_params`; PNG artifact (`:235-246`) | Proxy `imagen-3` 7.7 s, `gpt-image-2.5-flare` 17.5 s, both b64 PNG 1024x1024 [V probe]. Platform already seeds alias `image_gen` = `openai/imagen-3` on LiteLLM; awe env has `IMAGE_MODEL_NAME`, `IMAGE_SERVICE_ENDPOINT`, `IMAGE_SERVICE_API_KEY` set [V]. Whether the tool strips the `openai/` prefix [S]. |
| `generate_image_with_gemini`, `edit_image_with_gemini` | native Gemini API, `gemini_api_key` (`:274-301`) | **No**: `GEMINI_API_KEY` unset in awe/gwe [V], AI Studio credits depleted (CLAUDE.md). |
| `text_to_speech`, `multi_speaker_text_to_speech`, `select_voice` | Gemini TTS (`gemini-2.5-flash-preview-tts`, CLI strings); `select_voice` only picks a name (`:303-313`) | **No** (Gemini key); proxy has no TTS (`tts-1` -> 403) [V]. |
| WebUI voice (STT/TTS) | gwe `speech:` block; dormant unless `SAM_FEATURE_VOICE_INTERACTION=true`; STT openai `whisper-1` needs `OPENAI_API_KEY`; TTS gemini/azure/polly (gwe `/etc/sam/configs/gwe/gwe.yaml:212-250`) | **No** (flag off, no keys) [V]. |
| `render_document_to_images` (`builtin_document_tools`, STR) | LibreOffice/poppler, one PNG per page, then `load_artifact` (`:524-538`) | Yes on K8s per docs [V docs]; useful for PDF flyers/price lists. |
| `image_magick`, `ffmpeg`, `ffprobe` (`builtin_media_tools`, STR) | crop/resize/convert; webm -> wav (`:570-612`) | Yes per docs [V docs]. |
| `create_chart_from_plotly_config`, `mermaid_diagram_generator` | image output | Yes per docs; not multimodal input. |
| `notify_user` (`notification_tools`) | `message`, `title`, `recipient_user_id`, `channels` - **text only**, no attachment (`:834-847`) | Text only [V docs]. |

### 1.4 LiteLLM proxy, probe results (2026-11-10, 16:19-16:27)

From `GET /v1/models` (69 models) and `GET /v1/model/info` plus small
calls (`MM/run_vision.sh`, `MM/vision_results.jsonl`):

| Model (proxy name) | Route | Vision | Probe |
|---|---|---|---|
| `claude-haiku-4-5-20251001` (= SAM `fast`, `planning`) | Bedrock | yes | 1.48-2.07 s, 795-1360 prompt tokens, 69-99 out; JSON wrapped in ```json fences 7/7 |
| `claude-sonnet-5` (= SAM `workflow`) | Bedrock | yes | 2.74-3.16 s; fenced 3/5 |
| `claude-haiku-5-5` (no SAM alias) | Bedrock | yes | 1.97-2.08 s; bare JSON; list price 0.1/0.5 USD per M tokens |
| `claude-opus-5` (= `expert`) | Bedrock | yes | not probed |
| `imagen-3` | Vertex gemini-2.5-flash-image | gen | 7.7 s, 768 KB PNG, 0.039 USD/image (model info) |
| `gpt-image-2.5-flare` | Azure (separate resource) | gen | 17.5 s, 445 KB PNG |
| `whisper` | Azure | STT | 1.7 s, "Preisvorschlag für Kaffee-Crema freigeben, neuer Preis 12,99 Euro." |
| `gemini-3.6-flash` | Vertex | yes + audio | 2.1 s text answer |
| `tts-1` | - | - | HTTP 403 (not available) |

Accuracy notes (synthetic images, `MM/img/`): competitor tag read
correctly 6/6 across three models; coffee pack identified as article 4711
with 0.97-0.99 confidence 5/5; ESL "12,99" verified 2/2. Two negative
cases with Haiku 4.5: a heavily blurred tag gave `lesbar: false` **but
still a price 1.19**; an abstract yellow blob was classified as
"Apfelsaft" with **confidence 0.75** (closed-set hallucination). Gates on
`lesbar` and on a high confidence threshold are mandatory.

### 1.5 Can a workflow agent node receive an image?

- **Not as an image parameter.** The agent node schema has `input`,
  `instruction`, `input_schema_override`, `output_schema_override` and no
  `images`/`artifacts` field (`review-sam/schema/wf_agent.md`) [V].
- **Yes, as an artifact reference.** Pass the filename (from
  `{{workflow.input.<field>}}` or a tool node's
  `{{<node>.output.created_artifact}}`, which is version-pinned
  `name:version`) in `input`, instruct the agent to call `load_artifact`
  on it, and use a vision model (`fast`/`workflow`). The artifact must be
  in the run's session: workflow nodes share one artifact session per run
  (map iterations explicitly do; `SKILL/.../artifact-naming.md`) [V docs],
  agent node in the same session [S].
- **From an event:** only via `artifactProcessing` on the rule, then the
  filename the event itself chose (the POS app sets it, e.g.
  `cp-<scan_id>.jpg`), read in the workflow as
  `{{workflow.input.photo_name}}` [S].
- **From a tool node:** a built-in that saves exactly one artifact exposes
  `created_artifact` / `created_artifact_name` / `created_artifact_version`
  (`SKILL/.../artifact-naming.md`) [V docs]; for MCP tools inside a
  workflow `tool` node, whether the auto-saved image content shows up as
  `created_artifact` is [S].
- **Cheapest deterministic route:** `tool` node `describe_image`
  (`input_image: "{{workflow.input.photo_name}}"`, `prompt: <extraction
  prompt asking for JSON>`) -> `tool` node on our MCP connector that
  parses the JSON string (strip ``` fences), matches the catalog in
  Postgres and returns a Pydantic model -> `switch` on its fields. No agent
  loop, one vision call [S].

---

## 2. Proposed multimodal features

Common building blocks (all four features):

- Own topics under `gpos/v1/vision/...` (DESIGN 5.4); photos are not part
  of the GEBIT Purchase API, so the GEBIT topics stay pure. A recognised
  article still ends as a normal GEBIT event raised by the POS simulator.
- Capture in the browser (`getUserMedia`), downscale to 1024 px long edge,
  JPEG quality 0.8 (60-150 KB, about 100-200 KB base64), crop to the
  frame guide so no faces end up in artifacts.
- The booth app shows the photo on the monitor immediately from its own
  copy; SAM only returns the structured result. Photos and results are
  stored in Postgres `gpos` (requirement 6), SAM keeps its own artifact
  copy in SeaweedFS (reset/teardown must clean both, see section 4).
- One shared MCP tool on `gpos-booth-tools` per feature that parses the
  vision JSON, applies the gates and writes the observation row, so the
  workflow never branches on free text.

### 2.1 Feature A - "Wettbewerbspreis per Foto" (new price-change trigger)

**What the visitor sees:** "Sie sind Marktleitung. Ein Mitarbeiter hat
beim Wettbewerber fotografiert." The visitor holds a laminated, matte
competitor tag (fictitious chain, e.g. "FRISCHMARKT - GEBIT Ente 6,99 EUR")
into the frame of the tablet camera and taps once. About 3-4 s later the
monitor shows photo, extracted values and the gap ("Wettbewerb 6,99 EUR,
wir 8,67 EUR, -19 %"); a few seconds later the pricing agent's proposal
appears and goes into the SAM-native approval.

**Flow (target path):**

1. Tablet/POS app captures and publishes
   `gpos/v1/vision/competitor-photo/<store>/<device>` with
   `{scan_id, device, ts, meta:{...}, photo:{name:"cp-<scan_id>.jpg",
   mime:"image/jpeg", data:"<base64>"}}`.
2. Entrypoint rule `competitor_photo` -> `targetWorkflowName:
   gpos-competitor-price`, `inputExpression` selecting **only** `meta` and
   `photo.name` (not the base64, see 4.6), `artifactProcessing` extracting
   `input.payload:photo` with `filename`, `content`, `mime_type`,
   `content_encoding: base64`.
3. Workflow `gpos-competitor-price`:
   - `read` - tool `describe_image` (Haiku via `tool_config`) with a fixed
     extraction prompt (JSON: retailer, article text, price, unit price,
     readable).
   - `match` - MCP tool `match_competitor_price(scan_id, raw)` -> Pydantic
     `{readable, matched, article_id, competitor_price, our_price,
     gap_pct, confidence}`; fuzzy match only against the booth catalog;
     writes `competitor_observation`; publishes the monitor event.
   - `gate` - switch: `readable && matched && gap_pct <= -5` -> pricing;
     else -> monitor hint "Bitte nochmal fotografieren" (no LLM).
   - `price` - the common pricing path that every trigger uses (rules ->
     pricing agent `fast` -> SAM HITL -> apply), with `trigger:
     competitor_photo` and the photo filename passed along so the
     proposal text can cite it.
4. `notify_user` text: "Wettbewerbspreis erkannt: ... Vorschlag wartet
   auf Freigabe" (Notifications capability).

**SAM components:** Event Mesh entrypoint with `artifactProcessing`,
workflow (tool + switch + agent/HITL), built-in `describe_image`, MCP
connector tool, agent `fast`, Notifications, HITL. Covers the mandatory
"Multi-modal" item with a business reason, not as decoration.

**Latency [A]:** capture + publish 0.3-0.6 s; entrypoint 0.02 s;
`describe_image` 2-3.5 s (direct Haiku call measured 1.5-2.1 s plus tool
overhead); MCP match 0.1-0.8 s; result on the monitor after about 3-5 s;
pricing agent 4.5-6 s; proposal visible after about 8-11 s. Fallback path
via an agent with `load_artifact` instead of `describe_image`: +4-6 s.

**Risks and mitigations:**

- Transport unproven (`artifactProcessing` on a workflow target, key
  spelling) [S] -> fallback A2 below; spike S3.
- `describe_image` tool_config/model-prefix handling unproven [S] ->
  agent node + `load_artifact` (S2), or `enable_inline_vision` agent.
- Glare and angle on the prop -> matte lamination, fixed photo stand
  with frame guide, preview and "Nochmal" button.
- Hallucinated price on unreadable photos (seen in the probe) -> gate on
  `readable`, require a catalog match, require the price to be within a
  plausibility band of our price (+-60 %).
- Visitors photograph real products/competitors -> the catalog match
  fails gracefully ("Nicht in unserem Sortiment"); never display a real
  chain name returned by the model (the MCP tool shows the matched
  catalog name and a neutral "Wettbewerber").

**Fallbacks:**

- A2: rule targets an agent `gpos-price-scout` (`enableInlineVision:
  true`, structured invocation output schema) -> `successOutput`
  `structured` on `gpos/v1/vision/competitor-result` -> the engine turns it
  into the same trigger event that starts the pricing workflow.
- A3: the Marktleitung tablet uses the SAM WebUI chat (iPad "Foto
  aufnehmen" in the attach dialog) with the same agent; most "SAM-native"
  but more taps.
- A4: control card / button "Wettbewerbspreis (Preset)" that publishes the
  stored result for the prop; the trigger and the approval still run live.

**Effort [A]:** 5-7 PT (capture UI 1.5, rule + workflow 1.5, MCP tool +
tests 1.5, props + prompt tuning 1, spike S1-S3 1).

### 2.2 Feature B - "Regal-Check" (verify the e-paper label after approval)

**What the visitor sees:** after the tap on "Freigeben" the 4.2" label
flips to 6,89 EUR; a small camera above the shelf takes a picture, and
within a few seconds the monitor shows "Regal geprüft: Etikett zeigt
6,89 EUR" with the camera frame, plus a SAM inbox notification.

**Flow:**

1. Engine publishes `gpos/v1/esl/updated` after the e-paper refresh
   completes (expected article and price inside).
2. Shelf-cam service (USB webcam on a fixed arm, or the tablet camera)
   waits 1.5 s, captures the label region, publishes
   `gpos/v1/vision/shelf-photo` with base64 plus expected values.
3. Workflow `gpos-shelf-check`: `describe_image` (prompt contains the
   expected price) -> MCP `verify_label(raw, expected)` -> switch:
   match -> `notify_user` "Regal geprüft" + monitor tick;
   mismatch -> wait/retry once (second photo), then a neutral
   "Bitte Etikett prüfen" notification, never a red "Fehler" on the big
   monitor.

**SAM components:** entrypoint + `artifactProcessing`, workflow,
`describe_image`, MCP tool, Notifications. Shows that the agent checks the
physical result, not only its own database (label compliance is a real
retail pain point).

**Latency [A]:** 3-6 s after the label refresh; asynchronous, not on the
critical approval path (DESIGN target "Freigabe bis Etikett p90 <= 6 s"
stays untouched).

**Risks:** fair lighting/spotlights on the label front, e-paper partial
refresh ghosting (old digits faintly visible -> possible misread), camera
bumped by visitors. Mitigations: rigid mount and fixed exposure, capture
only after the refresh-done event, crop to the label, prompt "lies nur die
große Preiszahl", tolerate one retry, show only the positive result live.
Fallback: hide the step (no visible gap) or verify a rendered PNG of the
simulated label, labelled "Simulation".

**Effort [A]:** 4-6 PT incl. camera mount and calibration (shares workflow
and MCP pattern with A).

### 2.3 Feature C - "KI-Aktionsplakat" (generated promo visual)

**What the visitor sees:** after approval the customer display and the
monitor fade in a fresh campaign poster for the duck with the new price,
"in 8 Sekunden von der KI gestaltet".

**Flow:**

1. Parallel, non-blocking branch after the HITL approval: tool node
   `create_image_from_description` with `tool_config` = LiteLLM
   `imagen-3` (or the seeded `image_gen` settings); prompt built from the
   article and campaign type, with "keine Schrift, keine Logos".
2. MCP tool node `publish_visual(scan_id, image)` where `image` is the late
   embed `«artifact_content:{{gen.output.created_artifact}} >>>
   format:datauri»` (the format exists in the embed grammar, CLI strings)
   [S]; the tool stores the PNG in Postgres and notifies the monitor.
3. Monitor/customer display render the price, "Aktion" and the PAngV
   lines as HTML on top of the image (text is never generated into the
   picture).

**SAM components:** workflow parallel branch, built-in image generation,
artifact late embed, MCP tool. Optional `notify_user` with the campaign
text.

**Latency [V/A]:** imagen-3 7.7 s, gpt-image 17.5 s measured direct;
plus tool overhead about 0.5-1 s; asynchronous after approval.

**Risks:** route health (both image routes broke in the past), cost per
image (imagen-3 0.039 USD; 100-160 visitors per day would be 12-19 USD
over three days if every visit generated one), visual surprises (text
artefacts, odd ducks), moderation refusals, artifact-to-monitor transfer
unproven [S]. Mitigations: cache per article and campaign type (generate
once, reuse; live generation only in show mode or on a control card),
pre-generated library made with the same tool at G2 as the offline
fallback, fixed style prompt, HTML text overlay.

**Effort [A]:** 3-4 PT.

### 2.4 Feature D - "Foto-Scan an der Kasse" (optional)

**What the visitor sees:** an article without barcode (e.g. the duck
without label, or loose fruit) is held under the counter camera; the POS
asks "Erkannt: GEBIT Ente - übernehmen?" and on "Ja" the line appears.

**Flow:** POS simulator "Kamera" button -> `gpos/v1/vision/scan-photo` ->
workflow: `describe_image` with the booth catalog in the prompt -> MCP
`resolve_article` (closed set, confidence >= 0.9, else "nicht erkannt")
-> `successOutput` to the POS -> POS confirm tap -> normal GEBIT line
event (GEBIT format unchanged).

**Latency [A]:** 3-5 s versus 0.3 s for the scanner, so only as a side
moment, never in the 75 s express flow.

**Risks:** closed-set hallucination (probe: 0.75 confidence for a wrong
article), lighting, queue pressure. Confirmation tap and threshold are
mandatory. It does not create a price trigger, so its demo value for this
use case is the lowest.

**Effort [A]:** 4-5 PT (most parts shared with A).

### 2.5 Smaller ideas, not recommended for v1

- **Lieferanten-Preisliste (PDF) as a cost trigger:** a supplier PDF with
  a higher purchase price -> `convert_pdf_to_markdown` or
  `render_document_to_images` + vision -> margin rule -> price proposal.
  Very reliable (typed text), credible for retail experts, little wow;
  good for the depth layer.
- **Spoken announcement on the monitor:** browser Web Speech API with an
  offline German voice reading the approved notification. Works without
  any key, but it is not a SAM capability (no TTS route; SAM TTS tools
  need Gemini).
- **Voice approval:** `transcribe_audio` against proxy `whisper` works
  technically (1.7 s), but the native HITL answer happens in the SAM UI,
  so a voice path would bypass it. Skip.

---

## 3. Ranking and recommendation

Scores 1-5 [A]:

| Feature | Wow | Reliability | Creates a price trigger | SAM capabilities shown | Effort | Rank |
|---|---|---|---|---|---|---|
| A Wettbewerbspreis per Foto | 4 | 4 | yes | Vision, Workflow, Tools, Agent, HITL, Notification | 5-7 PT | **1** |
| B Regal-Check | 3.5 | 3.5 (fixed cam) | no (closes loop) | Vision, Workflow, Notification | 4-6 PT | **2** |
| C KI-Aktionsplakat | 4.5 | 3 live / 4.5 cached | no | Image generation, Workflow, embeds | 3-4 PT | **3** |
| D Foto-Scan Kasse | 3 | 2.5 | no | Vision | 4-5 PT | 4 (optional) |

Why A first: it is the only feature where the multimodal step *is* the
business event (a new, different trigger for a price change, which the
owner asked for), it reuses the existing pricing path and the
SAM-native approval, the props make it deterministic, and the probes show
the model side is fast and accurate. B is second because it runs without
visitor action (robust choreography) and adds a natural use for
Notifications. C is the strongest visual but depends on the shakiest
routes, so it ships with a cache and a pre-generated fallback. D is the
first thing to cut.

Model choice: `fast` (Haiku 4.5) for all vision reads; `workflow`
(Sonnet 5) adds about 1 s per call with no accuracy gain on the props.
Haiku 5.5 is equally fast, returns bare JSON and is ten times cheaper on
list price, but has no SAM alias today (adding one is a later decision).
Give `fast` and `workflow` prices so the cost view stays honest (all lab
models have `price_input/price_output` NULL; `image_gen` is even stored
with `model_type chat`, platform DB read 2026-11-10).

---

## 4. Limits and gotchas

### 4.1 Formats

- `describe_image`, `load_artifact` visual block: PNG, JPEG, WEBP, GIF
  [V docs]. Decision node: PNG, JPEG, WebP (type sniffed from content)
  [V docs].
- `describe_audio`, `transcribe_audio`: WAV, MP3 only [V docs]. Browser
  `MediaRecorder` produces webm/opus: convert in the app or with the
  `ffmpeg` tool first.
- `edit_image_with_gemini` always writes JPEG (moot here).

### 4.2 Sizes

- SAM: `load_artifact` visual block up to 20 MiB; inline vision max 5
  images and 20 MiB per message; decision node max 5 images / 20 MiB,
  8000 px, 40 MP; late embeds up to `gateway_artifact_content_limit_bytes`
  10 MB; uploaded text inline only up to `max_inline_artifact_bytes` 2048
  [V docs].
- Provider side (Anthropic/Bedrock) is stricter than SAM's 20 MiB: a few
  MB per image and 8000 px max; images above about 1568 px long edge are
  downscaled anyway [A, provider docs]. Tokens are about width x height /
  750: 1280x720 = about 1.2k tokens, matching the measured 1267-1397
  prompt tokens with prompt. Send 1024 px JPEG.
- Broker: keep each photo event well under 1 MB (Solace guaranteed
  messages allow more, but every hop copies it) [A].
- Task logging persists file parts up to 10240 bytes and strings up to
  16384 bytes (`TASK_LOGGING_MAX_FILE_PART_SIZE`,
  `TASK_LOGGING_MAX_PAYLOAD_TEXT_BYTES`, gwe.yaml) [V]: keep base64 out of
  `workflow.input` and out of prompts.

### 4.3 MCP and tool-result rules

- MCP results > 2048 bytes are saved as artifacts, > 4096 bytes replaced
  by a reference; image/audio/resource content is **always** saved, so an
  MCP tool that returns an image does not put pixels in front of the
  model by itself (needs `load_artifact` or `artifact_handling_mode:
  embed`) [V docs].
- MCP tools must return Pydantic models (connector needs a manifest list);
  JSON results reach the model as JSON since 2.542.1 (release notes,
  DATAGO-160102) [V].
- Built-in tool results: > 8192 bytes become an artifact
  (`tool_result_auto_artifact_threshold_bytes`), inline cap 100 KB
  [V docs].
- Workflow `tool` nodes cannot index lists; `created_artifact` exists only
  when exactly one artifact was saved [V docs].

### 4.4 Latency (measured direct, one 1280x720 image, about 80 output tokens)

- Haiku 4.5 1.5-2.1 s, Haiku 5.5 about 2.0 s, Sonnet 5 2.7-3.2 s [V].
- In SAM [A]: `describe_image` tool node about 2-3.5 s; agent node with
  `load_artifact` two LLM turns, about 7-10 s (a 1-call `fast` agent is
  4.5-5.6 s on 2.542.1); inline vision or `embed` about 5-7 s.
- Image generation: imagen-3 7.7 s, gpt-image-2.5-flare 17.5 s [V].
- Whisper: 1.7 s for 5 s of audio [V].

### 4.5 Quality

- Haiku 4.5 wrapped the JSON in ```json fences in 7/7 answers, Sonnet 5
  in 3/5, Haiku 5.5 in 0/3 [V]: the MCP parser must strip fences; or use
  agent structured output.
- Unreadable input still yields numbers, unknown objects get a confident
  wrong article [V]: always gate on `readable`, a catalog match and a
  plausibility band; confirmation tap for checkout recognition.

### 4.6 Data and operations

- Event-triggered runs store artifacts under the rule identity
  (`power_user@solace.lab`) in SeaweedFS; chat and artifacts survive an
  uninstall (memory "SAM forensics sources"). The per-visitor reset must
  not depend on deleting them; add a teardown/cleanup step and avoid
  people in the frame (crop in the browser).
- Declarative `tool_config` with `api_key: ${LLM_SERVICE_API_KEY}` is
  substituted at apply time and lands in the platform DB in plain text,
  like model keys (README models) [V for models, A for tool_config].
- `notify_user` carries text only; images reach people through our
  monitor, not through the SAM inbox [V docs].
- `ask_user_question` errors on Event Mesh channels and must not be
  attached to workflow agents [V docs].
- Route health: memory and `scripts/models/README.md` say the proxy's
  gemini-*/azure-* routes are permanently broken; on 2026-11-10 imagen-3,
  gemini-3.6-flash, whisper and gpt-image-2.5-flare all answered 200 [V].
  Treat as "works today, broke before": probe them in the booth preflight
  and keep offline fallbacks.

---

## 5. G0 spike checklist (needs owner approval for lab writes)

| # | Spike | Pass criterion |
|---|---|---|
| S1 | `describe_image` in a workflow `tool` node with `tool_config` (`model` with and without `openai/` prefix, `api_base` with and without `/v1`, `api_key`) | `output.description` contains the JSON for `competitor_tag.jpg` in < 4 s |
| S2 | Agent (`fast`) in WebUI chat: upload PNG, once with `load_artifact`, once with `enableInlineVision: true` | Correct reading; note turns and latency |
| S3 | Event Mesh rule with `artifactProcessing` (camelCase and snake_case keys via `sam config plan`) + workflow target; event with 150 KB base64 | Artifact `cp-<id>.jpg` visible to node 1 of the run; workflow input free of base64 |
| S4 | `create_image_from_description` with LiteLLM `imagen-3` -> `created_artifact` -> MCP tool node input `«artifact_content:... >>> format:datauri»` | MCP tool receives a valid data URI |
| S5 | MCP tool returning `ImageContent` inside a workflow `tool` node and on an agent with `artifactHandlingMode: embed` | `created_artifact` set / model sees image without `load_artifact` |
| S6 (opt.) | `transcribe_audio` with proxy `whisper` | Transcript artifact |

Decision after S1-S3: if S3 fails, A uses fallback A2 (agent target); if
S1 fails, use agent + `load_artifact` (budget +4-6 s).

---

## 6. Evidence and files

- Probe scripts: `impl/mm/make_images.py` (synthetic, brand-free test
  images), `impl/mm/probe_vision.py`, `impl/mm/run_vision.sh` (curl,
  key from `agent-mesh-deployment/.env`, never printed).
- Results: `impl/mm/vision_results.jsonl` (15 calls), generated images
  `impl/mm/imggen_imagen-3.png`, `impl/mm/imggen_gpt-image-2.5-flare.png`.
  Test audio and the proxy model list: local, not versioned.
- Doc excerpts from the 2.542.1 CLI (local, not versioned):
  `impl/mm/cli-doc-agent-limits.txt` (inline vision, MCP thresholds),
  `impl/mm/cli-doc-artifact-processing.txt` (event mesh artifact
  extraction).
- Lab reads: awe `/etc/sam/configs/awe/sam.yaml` (`tool_defaults` for
  Gemini tools only), gwe `/etc/sam/configs/gwe/gwe.yaml:212-250` (speech,
  dormant), awe/gwe env key names (`IMAGE_*` set, `GEMINI_API_KEY` unset),
  platform DB `model_configurations` (10 aliases incl. `image_gen`, no
  prices).
