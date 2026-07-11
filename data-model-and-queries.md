# Data model & query reference

Reference for building dashboards and ad-hoc analysis on the telemetry this
bridge produces. Three parts:

1. [Attribute map](#attribute-map) — what attributes exist after the conformance
   pipeline, and where each comes from.
2. [DQL query library](#dql-query-library) — validated queries for common needs.
3. [Dynatrace AI Observability internals](#dynatrace-ai-observability-internals)
   — how the app derives its tiles, so you can reproduce or extend them.

> Queries use Dynatrace Query Language (DQL). The attribute map is backend-
> agnostic (standard OTel span attributes); the DQL and app-internals sections
> are Dynatrace-specific.

---

## Attribute map

Node-level spans arrive under `service.name == "langgenius/dify"`. The table
below lists the attributes available **after** the Collector's conformance
pipeline, and the origin of each:

- **Dify native** — emitted by Dify's native OTel instrumentation as-is.
- **Normalized** — rewritten by a conformance processor to match the official
  OTel GenAI Semantic Conventions.
- **Derived** — created by an enrichment processor (did not exist in the raw
  span).
- **Relocated (`dify.*`)** — moved out of the `gen_ai.*` namespace because the
  attribute is Dify-specific, not part of the convention.

### GenAI convention attributes (span-level)

| Attribute | Contents | Origin |
|---|---|---|
| `gen_ai.request.model` | Model requested at the LLM node (e.g. `qwen/qwen3-32b`). | Dify native |
| `gen_ai.response.model` | Model that produced the response. Copied from `request.model` (Dify does no routing/fallback). | Derived (`transform/genai_response_model`) |
| `gen_ai.provider.name` | Clean provider name (e.g. `groq`). Collapsed from Dify's raw `{org}/{plugin}/{provider}`. | Normalized (`transform/genai_provider_name_normalize`) |
| `gen_ai.operation.name` | Operation type; set to `chat` for LLM node spans. | Derived (`transform/genai_operation_name`) |
| `gen_ai.response.finish_reasons` | Finish reasons as an **array** (convention-compliant). | Normalized (`transform/genai_finish_reasons`) |
| `gen_ai.usage.input_tokens` | Prompt/input token count. | Dify native |
| `gen_ai.usage.output_tokens` | Completion/output token count. | Dify native |
| `gen_ai.usage.total_tokens` | Total token count. | Dify native |
| `gen_ai.input.messages` | Input messages (promoted from legacy `gen_ai.prompt` when absent). | Normalized (`transform/genai_legacy_promotion`) |
| `gen_ai.output.messages` | Output messages (promoted from legacy `gen_ai.completion` when absent). | Normalized (`transform/genai_legacy_promotion`) |
| `gen_ai.tool.name`, `gen_ai.tool.description`, `gen_ai.tool.call.id`, `gen_ai.tool.call.arguments` | Tool-call attributes that ARE part of the official convention — kept as-is. | Dify native |

### Dify-specific attributes (relocated to `dify.*`)

These are Dify-specific and were moved out of `gen_ai.*` to keep the convention
namespace pure. Useful for Dify-specific analysis; not portable across backends.

| Attribute | Contents | Was |
|---|---|---|
| `dify.workflow_id` | Workflow identifier. On the workflow-root span it is `"unknown"` (dispatch span). | (Dify native, unchanged) |
| `dify.span.kind` | Dify's span-kind hint. | `gen_ai.span.kind` |
| `dify.framework` | Fixed to `dify`. | `gen_ai.framework` |
| `dify.user_id` | End-user identifier. | `gen_ai.user.id` |
| `dify.time_to_first_token` | TTFT measurement. | `gen_ai.user.time_to_first_token` |
| `dify.io.input_value`, `dify.io.output_value` | Arize/OpenInference "chain I/O" (distinct from `gen_ai.*.messages`). | `input.value` / `output.value` |
| `dify.tool.call.result`, `dify.tool.type` | Non-official tool attributes. | `gen_ai.tool.call.result` / `gen_ai.tool.type` |
| `dify.retrieval.query`, `dify.retrieval.document` | Retrieval attributes (no stable `gen_ai.retrieval.*` in spec yet). | `retrieval.query` / `retrieval.document` |

### Node & workflow context attributes

These identify *which node*, *what kind of operation*, and *which workflow
execution* a span belongs to. Present on native Dify spans; the conformance
pipeline relocates `dify.span.kind` out of the `gen_ai.*` namespace but does not
otherwise alter these.

| Attribute | Contents | Notes |
|---|---|---|
| `span.name` | The **node's label** as set in the Dify Studio builder (e.g. `LLM`, `User Input`, `Answer`, `Output`, `Query Metric`). | Free text, user-editable per node instance — not a stable category. Renaming a node in Studio changes this value. Most spans under `service.name == "langgenius/dify"` are infrastructure (redis, postgres, celery `run/schedule.*`), not workflow nodes — filter on `node.type` to isolate node spans. |
| `node.type` | The node's **stable category** from Dify's internal node taxonomy. See [Complete node type inventory](#complete-node-type-inventory) below for the full list and which ones were actually observed in this project vs. catalogued from Dify's official docs. | The reliable field for grouping/filtering by node category — use it instead of `span.name` when you want "all LLM nodes" rather than "the node literally named LLM". |
| `dify.span.kind` | Coarser-grained operation kind. Observed values: `TASK` (for `start`/`answer`/`end` nodes), `TOOL` (for `tool` nodes). LLM nodes did not carry this attribute in observed spans. | Relocated from `gen_ai.span.kind` by `transform/genai_dify_namespace_cleanup`. A third, coarser axis alongside `span.name` and `node.type` — useful for a quick TASK-vs-TOOL split without enumerating every `node.type`. |
| `node.id` | Internal node identifier within the workflow definition (e.g. `llm`, or a numeric timestamp-like ID for `start`/`answer`/`end` nodes). | Stable per node position in the graph, not per execution. |
| `node.execution_id` | Unique identifier (UUID) for this specific node execution. | Distinguishes repeated executions of the same node (e.g. in a loop) within one workflow run. |
| `dify.workflow_id` | On workflow-graph node spans (`start`, `llm`, `answer`, `end`, `tool`), this field was **not present** in observed spans — only on the workflow-root span, where it is `"unknown"` (see below). | Do not rely on this attribute for the actual workflow ID — see `sys.workflow_id` below for where the real ID lives. |
| `dify.app_id` / `dify.tenant_id` / `dify.user_id` / `dify.user_type` / `dify.streaming` | App, tenant, end-user, and streaming context on the **workflow-root span** (`AppGenerateService.generate`). | `dify.user_id` is relocated from `gen_ai.user.id`. These identify *which* app/tenant/user, not *what kind* of app. |

**There is no "workflow type" attribute.** Dify does not emit whether an app is a
Chatflow, Workflow, or Agent as a span attribute — only `dify.app_id` (an
identifier, not a category) is present. If you need to distinguish app types,
you currently have to resolve `dify.app_id` against Dify's own database/API;
it cannot be read from telemetry alone.

### Complete node type inventory

The full list of Dify node types, per [Dify's official node documentation](https://docs.dify.ai/en/self-host/use-dify/nodes). **Verified** means observed as a real `node.type` value in this project's test spans (with the `span.name` label actually seen). **Catalogued** means it is a documented Dify node type, expected to emit `node.type` following the same pattern, but not exercised by this project's test workflows — treat its exact `node.type` string as unconfirmed until you observe it.

| Dify node (docs) | Status | Observed `node.type` | Observed `span.name` |
|---|---|---|---|
| Start | Verified | `start` | `User Input` |
| LLM | Verified | `llm` | `LLM`, `LLM 2` |
| Answer | Verified | `answer` | `Answer` |
| Output | Verified | `end` | `Output` |
| Tool | Verified | `tool` | `Query Metric` |
| Agent | Catalogued | — | — |
| Code | Catalogued | — | — |
| Document Extractor | Catalogued | — | — |
| HTTP Request | Catalogued | — | — |
| Human Input | Catalogued | — | — |
| If-Else | Catalogued | — | — |
| Iteration | Catalogued | — | — |
| Knowledge Retrieval | Catalogued | — | — |
| List Operator | Catalogued | — | — |
| Loop | Catalogued | — | — |
| Parameter Extractor | Catalogued | — | — |
| Question Classifier | Catalogued | — | — |
| Template | Catalogued | — | — |
| Trigger (Integration / Schedule / Webhook) | Catalogued | — | — |
| Variable Aggregator | Catalogued | — | — |
| Variable Assigner | Catalogued | — | — |

Note: Dify's docs list "Start Node" and "User Input" as separate concepts, but
this project observed `span.name == "User Input"` on a span with
`node.type == "start"` — they appear to be the same underlying node type with a
context-dependent display label (chat-style apps show "User Input"; the
underlying category is `start`). Not fully confirmed across all app types.

### The `sys.*` fields inside `dify.io.input_value`

The **`start`** node's `dify.io.input_value` attribute is a JSON payload (not
individually-indexed span attributes) containing Dify's internal system
variables:

| Field (inside the JSON) | Contents |
|---|---|
| `sys.workflow_id` | The **actual** workflow ID (unlike the span-level `dify.workflow_id`, which is absent on node spans and `"unknown"` on the root). |
| `sys.workflow_run_id` | ID of this specific workflow execution (run). |
| `sys.app_id` | Same app ID as `dify.app_id` on the root span. |
| `sys.user_id` | Same user ID as `dify.user_id` on the root span. |
| `sys.conversation_id` | Conversation ID, for chat-type apps. |
| `sys.dialogue_count` | Turn count within the conversation. |
| `sys.query` | The end-user's raw input text. |
| `sys.files` | Attached files array (empty if none). |

**These are not DQL-queryable as top-level fields.** They only exist inside the
serialized JSON string in `dify.io.input_value` on the `start` node span; to
use them in DQL you must parse that field (e.g. with `parse` / a JSON
extraction function), not `fields sys.workflow_id`.

### Tool-node spans: plugin integration example

`tool`-type node spans carry rich context about the invoked tool, including
**which Dify plugin served it** — directly relevant if you're building or
debugging a Dify plugin (such as `obs-plugins/dynatrace-dify-plugin`):

| Attribute | Contents | Example observed value |
|---|---|---|
| `gen_ai.tool.name` | Tool's display name. | `Query Metric` |
| `gen_ai.tool.description` | Tool's description, as a JSON payload including the provider. | `{"provider_type": "builtin", "provider_id": "obs-plugins/dynatrace/dynatrace", "plugin_unique_identifier": "obs-plugins/dynatrace:0.1.0@..."}` |
| `gen_ai.tool.call.arguments` | The arguments the tool was invoked with. | `{"metric_selector": "builtin:service.response.time:avg", "from": "now-1h", "resolution": "1m"}` |
| `dify.tool.call.result` | The tool's raw result. | `{"text": "...", "json": [{"metricId": "...", "series": []}]}` |
| `dify.tool.type` | Provider metadata (same shape as `gen_ai.tool.description` in observed data). | See above |

This confirms plugin-invocation spans (e.g. from `dynatrace-dify-plugin` tools
like problem/metric queries) are captured with full context — provider
identity, arguments, and result — without any additional instrumentation.



### Smartscape entities (Dynatrace-derived)

Dynatrace automatically creates Smartscape topology entities from conformant
GenAI spans — visible proof the conformance pipeline feeds Dynatrace's
topology engine, not just dashboards:

| Attribute | Contents |
|---|---|
| `dt.smartscape.gen_ai.model` | Entity ID for the model (`GENAI_MODEL-...`). |
| `dt.smartscape.gen_ai.provider` | Entity ID for the provider (`GENAI_PROVIDER-...`). |
| `dt.smartscape.gen_ai.service` | Entity ID for the service (`GENAI_SERVICE-...`). |
| `dt.smartscape.service` | Entity ID for the Dify service itself. |

These populate automatically once `gen_ai.request.model` / `gen_ai.provider.name`
are present and conformant — no additional configuration needed.



- **HTTP method.** Dify's Flask instrumentation emits the legacy `http.method`.
  What Dynatrace displays as `http.request.method` is Grail's post-ingestion
  normalization — not the raw span attribute. Filters in the Collector must key
  on `http.method`.
- **Console/infra spans are dropped.** Server spans for `/console/api/*`,
  `/health`, `/openapi.json`, `.env` scanner traffic, etc. are filtered out at
  the Collector (`filter/drop_dify_console_noise`) and never reach the backend.

---

## DQL query library

Validated queries. Use a recent timeframe (last 15–30 min) when checking live
changes — span data is immutable, so stale windows show pre-change data.

### Verify LLM node telemetry (post-conformance)

```
fetch spans
| filter service.name == "langgenius/dify"
| filter isNotNull(gen_ai.request.model)
| fields span.name, gen_ai.request.model, gen_ai.response.model, gen_ai.provider.name, gen_ai.operation.name
| limit 20
```
Expect model in both request/response, a clean provider, and `operation.name = chat`.

### Provider distribution

```
fetch spans
| filter service.name == "langgenius/dify"
| filter isNotNull(gen_ai.provider.name)
| summarize count(), by:{gen_ai.provider.name}
| sort `count()` desc
```
After normalization, only clean names (`groq`) appear — no `langgenius/groq/groq`.

### Model count (mirrors the "Number of models" tile)

```
fetch spans
| filter gen_ai.response.model != ""
| summarize models = countDistinct(gen_ai.response.model)
```

### Token usage by model

```
fetch spans
| filter service.name == "langgenius/dify"
| filter isNotNull(gen_ai.usage.total_tokens)
| summarize
    input = sum(gen_ai.usage.input_tokens),
    output = sum(gen_ai.usage.output_tokens),
    total = sum(gen_ai.usage.total_tokens),
    by:{gen_ai.response.model}
| sort total desc
```

### Request volume and latency (p50/p95)

```
fetch spans
| filter service.name == "langgenius/dify"
| filter isNotNull(gen_ai.request.model)
| summarize
    requests = count(),
    p50 = percentile(duration, 50),
    p95 = percentile(duration, 95),
    by:{gen_ai.response.model}
```

### Confirm console/infra noise is being dropped

```
fetch spans
| filter service.name == "langgenius/dify"
| filter isNotNull(http.method)
| filter isNull(gen_ai.request.model)
| summarize count(), by:{span.name}
| sort `count()` desc
```
On a post-deploy window this should be empty/near-empty — the filter drops these
at the Collector.

### Workflow-root spans (dispatch)

```
fetch spans
| filter service.name == "langgenius/dify"
| filter dify.workflow_id == "unknown"
| fields span.name, dify.workflow_id, duration
| limit 20
```
These are the `AppGenerateService.generate` dispatch spans — kept intentionally
(they anchor the trace) even though they carry an HTTP method.

### Node inventory by category (not just LLM)

```
fetch spans
| filter service.name == "langgenius/dify"
| filter isNotNull(node.type)
| summarize count(), by:{node.type, span.name}
| sort `count()` desc
```
`service.name == "langgenius/dify"` also includes non-workflow infrastructure
spans (redis, postgres, celery). Filter on `isNotNull(node.type)` to see only
actual workflow nodes, grouped by their stable category (`node.type`) alongside
the user-given label (`span.name`).

### Tool / plugin invocations

```
fetch spans
| filter service.name == "langgenius/dify"
| filter node.type == "tool"
| fields span.name, gen_ai.tool.name, gen_ai.tool.call.arguments, dify.tool.call.result
| limit 20
```
Surfaces which Dify plugin tools were invoked, with what arguments, and what
they returned — useful when debugging a Dify plugin (e.g.
`obs-plugins/dynatrace-dify-plugin`) from the telemetry side.

---

## Dynatrace AI Observability internals

How the app derives key tiles, discovered by inspecting each tile's underlying
DQL. Useful for reproducing tiles in custom dashboards or diagnosing an empty
one.

| Tile | Derivation | Requirement it implies |
|---|---|---|
| **Number of models** | `countDistinct(gen_ai.response.model)` | `gen_ai.response.model` must be set — hence `transform/genai_response_model`. Counting `request.model` would not populate it. |
| **Number of services** | Distinct `service.name` | With Track B retired, only `langgenius/dify` — count is 1 (no double-counting). |
| **Number of agents** | `gen_ai.agent.*` attributes | 0 for deterministic workflows (no agent). Expected, not a defect. |
| **Token usage / Cost** | Aggregation over span attributes `gen_ai.usage.*_tokens` (via DQL) — **not** a dedicated metric. | Token attributes on spans are sufficient; no token metric required. This is why Track B's MeterProvider was unnecessary. |
| **Model operations** | Spans classified via `gen_ai.operation.name` | `operation.name` must be set — hence `transform/genai_operation_name`. |
| **Invocation error count** | Failed spans on the service | Inflated by console/infra 4xx if not filtered; `filter/drop_dify_console_noise` keeps it reflecting real GenAI operations. |

### Practical implications

- **Tokens come from span attributes, not a metric.** Any token/cost tile can be
  rebuilt with a `sum(gen_ai.usage.*_tokens)` DQL over spans. There is no
  dependency on a token metric (and the `sumconnector` that could produce one is
  not in the `dynatrace/dynatrace-otel-collector` distribution).
- **DQL `lookup` needs `prefix: ""`.** When joining data with `lookup`, set
  `prefix: ""` — otherwise joined fields gain a `lookup.` prefix and read as null
  downstream.
- **Use `start_time`, not `timestamp`, for spans.** Span records filter/sort on
  `start_time`.
