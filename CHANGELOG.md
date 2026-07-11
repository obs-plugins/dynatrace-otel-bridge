# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0] — 2026-07-11

First stable release: a backend-agnostic OTel GenAI conformance bridge for
Dify, validated end-to-end against Dynatrace AI Observability.

### Added

- **Telemetry conformance pipeline** — an OTel Collector pipeline that
  normalizes Dify's native (non-conformant) GenAI telemetry to the official
  OTel GenAI Semantic Conventions:
  - `transform/genai_finish_reasons` — promotes `gen_ai.response.finish_reason`
    (string) to `gen_ai.response.finish_reasons` (array).
  - `transform/genai_dify_namespace_cleanup` — relocates Dify-specific
    attributes out of the `gen_ai.*` namespace into `dify.*`.
  - `transform/genai_legacy_promotion` — promotes legacy `gen_ai.prompt` /
    `gen_ai.completion` to `gen_ai.input.messages` / `gen_ai.output.messages`.
  - `transform/genai_tool_retrieval_namespace` — relocates non-official
    tool/retrieval attributes to `dify.*`.
  - `transform/genai_provider_name_normalize` — collapses Dify's raw
    `{org}/{plugin}/{provider}` provider string to a clean provider name.
  - `transform/genai_operation_name` — derives `gen_ai.operation.name = "chat"`
    for LLM node spans (Dify defines but never emits this attribute).
  - `transform/genai_response_model` — copies `gen_ai.request.model` to
    `gen_ai.response.model`, enabling Dynatrace AI Observability's "Number of
    models" tile (which counts via `countDistinct(gen_ai.response.model)`).
  - `filter/drop_dify_console_noise` — drops Dify console/infra HTTP spans
    (`/console/api/*`, `/health`, `.env` scanner traffic) that inflated error
    counts and ingest volume without carrying any GenAI signal.
- **`docs/data-model-and-queries.md`** — reference document: the full GenAI
  attribute map (native vs. normalized vs. derived), a validated DQL query
  library, and a breakdown of how the Dynatrace AI Observability app derives
  its tiles internally.
- **`dashboards/dify-genai-observability-dashboard.json`** — a ready-to-import
  Dynatrace dashboard (schema v21) covering models, tokens, providers,
  latency, and a console-noise regression check.
- **RUNBOOK.md** — full rewrite: architecture overview with a Mermaid diagram,
  a backend-agnostic vs. Dynatrace-specific breakdown of every conformance
  processor, a portability guide for targeting other OTel backends, and a
  consolidated set of operational notes (deployment gotchas, DQL quirks,
  filter-validation pitfalls).
- **README.md** — repositioned as a backend-agnostic OTel GenAI conformance
  bridge, with Dynatrace as the validated reference backend.

### Changed

- All source comments and documentation normalized to English.
- GCP is now documented as the tested provisioning path, not a hard
  requirement — the stack runs on any Docker Compose–capable host.

### Removed

- **Track B** (the SSE reverse-proxy/exporter on port 8088) retired. A parity
  test with the exporter stopped confirmed the native Track A pipeline
  (Dify → Collector conformance pipeline → Dynatrace) delivers node spans,
  token usage, provider, and model data on its own. The exporter's code is
  archived under [`legacy/`](legacy/README.md), not deleted.

### Fixed

- Console-noise filter now matches Dify's actual raw HTTP attribute
  (`http.method`, the legacy Flask dialect) rather than the Grail-normalized
  `http.request.method`, which the Collector never sees.
