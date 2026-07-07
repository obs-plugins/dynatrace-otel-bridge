from __future__ import annotations

import json
import logging
import os
import time
from contextlib import asynccontextmanager
from typing import Any
from urllib.parse import urlencode

import httpx
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter, SimpleSpanProcessor
from opentelemetry.trace import Span, SpanKind, Status, StatusCode


LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(level=LOG_LEVEL, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("dify-workflow-otel-exporter")

DIFY_API_BASE_URL = os.getenv("DIFY_API_BASE_URL", "http://api:5001").rstrip("/")
SERVICE_NAME = os.getenv("OTEL_SERVICE_NAME", "dify-workflow-otel-exporter")
CAPTURE_CONTENT = os.getenv("DIFY_OTEL_CAPTURE_CONTENT", "false").lower() == "true"
CONSOLE_EXPORT = os.getenv("DIFY_OTEL_CONSOLE_EXPORT", "false").lower() == "true"
MAX_ATTRIBUTE_VALUE_LENGTH = int(os.getenv("DIFY_OTEL_MAX_ATTRIBUTE_VALUE_LENGTH", "4096"))
REQUEST_TIMEOUT_SECONDS = float(os.getenv("DIFY_OTEL_REQUEST_TIMEOUT_SECONDS", "30"))

HOP_BY_HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
    "host",
    "content-length",
}


def configure_tracing() -> trace.Tracer:
    resource = Resource.create({"service.name": SERVICE_NAME})
    provider = TracerProvider(resource=resource)
    if CONSOLE_EXPORT:
        provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))
    if os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT") or not CONSOLE_EXPORT:
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    trace.set_tracer_provider(provider)
    return trace.get_tracer(__name__)


TRACER = configure_tracing()


def _truncate(value: str) -> str:
    if len(value) <= MAX_ATTRIBUTE_VALUE_LENGTH:
        return value
    return value[:MAX_ATTRIBUTE_VALUE_LENGTH] + "...[truncated]"


def _json_dumps(value: Any) -> str:
    return _truncate(json.dumps(value, ensure_ascii=True, default=str, separators=(",", ":")))


def _set_attr(span: Span, key: str, value: Any) -> None:
    if value is None:
        return
    if isinstance(value, (bool, int, float, str)):
        span.set_attribute(key, _truncate(value) if isinstance(value, str) else value)
        return
    if isinstance(value, list) and all(isinstance(item, (bool, int, float, str)) for item in value):
        span.set_attribute(key, value)
        return
    span.set_attribute(key, _json_dumps(value))


def _set_content_attrs(span: Span, prefix: str, value: Any) -> None:
    if value is None:
        return
    if CAPTURE_CONTENT:
        _set_attr(span, f"{prefix}.json", value)
        return
    if isinstance(value, dict):
        _set_attr(span, f"{prefix}.keys", sorted(str(key) for key in value.keys()))
        _set_attr(span, f"{prefix}.size", len(value))
    elif isinstance(value, list):
        _set_attr(span, f"{prefix}.size", len(value))
    else:
        _set_attr(span, f"{prefix}.type", type(value).__name__)


def _status_code(status: str | None, error: Any = None) -> Status:
    if error:
        return Status(StatusCode.ERROR, str(error))
    if status in {"failed", "error", "stopped"}:
        return Status(StatusCode.ERROR, status)
    return Status(StatusCode.UNSET)


def _filtered_request_headers(request: Request) -> dict[str, str]:
    return {
        key: value
        for key, value in request.headers.items()
        if key.lower() not in HOP_BY_HOP_HEADERS
    }


def _filtered_response_headers(headers: httpx.Headers) -> dict[str, str]:
    return {
        key: value
        for key, value in headers.items()
        if key.lower() not in HOP_BY_HOP_HEADERS
    }


def _target_url(request: Request) -> str:
    path = request.url.path
    query = request.query_params.multi_items()
    url = f"{DIFY_API_BASE_URL}{path}"
    if query:
        url = f"{url}?{urlencode(query, doseq=True)}"
    return url


def _is_workflow_path(path: str) -> bool:
    return "/workflows/run" in path or "/workflow/" in path and path.endswith("/events")


def _is_streaming_request(body: bytes, request: Request) -> bool:
    if request.method == "GET" and "/events" in request.url.path:
        return True
    if not body:
        return False
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return False
    return payload.get("response_mode") == "streaming"


class DifyWorkflowTrace:
    def __init__(self, path: str, method: str):
        self.path = path
        self.method = method
        self.root_span: Span | None = None
        self.node_spans: dict[str, Span] = {}
        self.started_at = time.time()

    def ensure_root(self, payload: dict[str, Any] | None = None, data: dict[str, Any] | None = None) -> Span:
        if self.root_span is not None:
            return self.root_span

        payload = payload or {}
        data = data or {}
        workflow_run_id = payload.get("workflow_run_id") or data.get("workflow_run_id") or data.get("id")
        workflow_id = data.get("workflow_id") or payload.get("workflow_id")
        attributes = {
            "dify.operation": "workflow",
            "dify.workflow_run_id": workflow_run_id,
            "dify.workflow_id": workflow_id,
            "dify.task_id": payload.get("task_id"),
            "http.request.method": self.method,
            "url.path": self.path,
        }
        self.root_span = TRACER.start_span(
            "dify.workflow",
            kind=SpanKind.SERVER,
            attributes={key: value for key, value in attributes.items() if value is not None},
        )
        return self.root_span

    def handle_sse_payload(self, payload: dict[str, Any]) -> None:
        event = payload.get("event")
        data = payload.get("data") or {}
        if not isinstance(data, dict):
            data = {"value": data}

        root_span = self.ensure_root(payload, data)
        root_span.add_event(f"dify.{event}", attributes=self._event_attrs(payload, data))

        if event == "workflow_started":
            self._apply_workflow_attrs(root_span, data)
            return

        if event == "workflow_finished":
            self._finish_workflow(root_span, data)
            return

        if event == "node_started":
            self._start_node(payload, data)
            return

        if event in {"node_finished", "node_failed"}:
            self._finish_node(data)
            return

        if event in {"text_chunk", "reasoning_chunk"}:
            node_id = data.get("node_id")
            if node_id:
                span = self.node_spans.get(str(node_id))
                if span:
                    span.add_event(f"dify.{event}", attributes=self._event_attrs(payload, data))

    def finish_open_spans(self, error: str | None = None) -> None:
        seen_spans: set[int] = set()
        for span in list(self.node_spans.values()):
            if id(span) in seen_spans:
                continue
            seen_spans.add(id(span))
            if error:
                span.set_status(Status(StatusCode.ERROR, error))
            span.end()
        self.node_spans.clear()

        if self.root_span is not None:
            if error:
                self.root_span.set_status(Status(StatusCode.ERROR, error))
            self.root_span.end()
            self.root_span = None

    def finish_http_error(self, status_code: int, body: bytes | None = None) -> None:
        span = self.ensure_root()
        span.set_attribute("http.response.status_code", status_code)
        if body:
            span.set_attribute("http.response.body.size", len(body))
        span.set_status(Status(StatusCode.ERROR, f"upstream HTTP {status_code}"))
        self.finish_open_spans()

    def handle_blocking_response(self, payload: dict[str, Any], status_code: int) -> None:
        span = self.ensure_root(data=payload.get("data") if isinstance(payload.get("data"), dict) else payload)
        span.set_attribute("http.response.status_code", status_code)
        data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
        if isinstance(data, dict):
            self._apply_workflow_attrs(span, data)
            span.set_status(_status_code(data.get("status"), data.get("error")))
            _set_content_attrs(span, "dify.workflow.outputs", data.get("outputs"))
        self.finish_open_spans()

    def _event_attrs(self, payload: dict[str, Any], data: dict[str, Any]) -> dict[str, Any]:
        attrs = {
            "dify.event": payload.get("event"),
            "dify.task_id": payload.get("task_id"),
            "dify.workflow_run_id": payload.get("workflow_run_id") or data.get("workflow_run_id"),
            "dify.node_id": data.get("node_id"),
            "dify.node_execution_id": data.get("id"),
            "dify.node_type": data.get("node_type"),
        }
        return {key: value for key, value in attrs.items() if value is not None}

    def _apply_workflow_attrs(self, span: Span, data: dict[str, Any]) -> None:
        scalar_attrs = {
            "dify.workflow_id": data.get("workflow_id"),
            "dify.workflow_run_id": data.get("workflow_run_id") or data.get("id"),
            "dify.workflow.status": data.get("status"),
            "dify.workflow.elapsed_time": data.get("elapsed_time"),
            "dify.workflow.total_tokens": data.get("total_tokens"),
            "dify.workflow.total_steps": data.get("total_steps"),
            "dify.workflow.created_at": data.get("created_at"),
            "dify.workflow.finished_at": data.get("finished_at"),
            "dify.workflow.error": data.get("error"),
        }
        for key, value in scalar_attrs.items():
            _set_attr(span, key, value)
        _set_content_attrs(span, "dify.workflow.inputs", data.get("inputs"))
        _set_content_attrs(span, "dify.workflow.outputs", data.get("outputs"))

    def _start_node(self, payload: dict[str, Any], data: dict[str, Any]) -> None:
        root_span = self.ensure_root(payload, data)
        node_key = str(data.get("id") or data.get("node_id") or len(self.node_spans))
        parent_context = trace.set_span_in_context(root_span)
        node_type = data.get("node_type") or "unknown"
        title = data.get("title") or data.get("node_id") or node_type
        span = TRACER.start_span(
            f"dify.workflow.node.{node_type}",
            context=parent_context,
            kind=SpanKind.INTERNAL,
            attributes={key: value for key, value in {
                "dify.operation": "workflow.node",
                "dify.workflow_run_id": payload.get("workflow_run_id"),
                "dify.node_execution_id": data.get("id"),
                "dify.node_id": data.get("node_id"),
                "dify.node_type": node_type,
                "dify.node.title": title,
                "dify.node.index": data.get("index"),
                "dify.node.created_at": data.get("created_at"),
            }.items() if value is not None},
        )
        self.node_spans[node_key] = span
        if data.get("node_id") is not None:
            self.node_spans[str(data["node_id"])] = span

    def _finish_node(self, data: dict[str, Any]) -> None:
        node_key = str(data.get("id") or data.get("node_id"))
        span = self.node_spans.get(node_key)
        if span is None:
            self._start_node({}, data)
            span = self.node_spans.get(node_key)
        if span is None:
            return

        scalar_attrs = {
            "dify.node.status": data.get("status"),
            "dify.node.elapsed_time": data.get("elapsed_time"),
            "dify.node.finished_at": data.get("finished_at"),
            "dify.node.error": data.get("error"),
            "dify.node.total_tokens": data.get("total_tokens"),
        }
        for key, value in scalar_attrs.items():
            _set_attr(span, key, value)
        _set_content_attrs(span, "dify.node.inputs", data.get("inputs"))
        _set_content_attrs(span, "dify.node.outputs", data.get("outputs"))
        if data.get("node_type") == "llm":
            self._apply_llm_genai_attrs(span, data)
        span.set_status(_status_code(data.get("status"), data.get("error")))
        span.end()

        for key, value in list(self.node_spans.items()):
            if value is span:
                self.node_spans.pop(key, None)

    def _apply_llm_genai_attrs(self, span: Span, data: dict[str, Any]) -> None:
        process_data = data.get("process_data")
        process_data = process_data if isinstance(process_data, dict) else {}
        outputs = data.get("outputs")
        outputs = outputs if isinstance(outputs, dict) else {}
        usage = process_data.get("usage") or outputs.get("usage")
        usage = usage if isinstance(usage, dict) else {}

        operation_name = process_data.get("model_mode") or "chat"
        model_name = process_data.get("model_name")
        model_provider = process_data.get("model_provider")
        provider_name = model_provider.rsplit("/", 1)[-1] if isinstance(model_provider, str) else None
        finish_reason = process_data.get("finish_reason")

        _set_attr(span, "gen_ai.operation.name", operation_name)
        _set_attr(span, "gen_ai.request.model", model_name)
        _set_attr(span, "gen_ai.provider.name", provider_name)
        _set_attr(span, "gen_ai.usage.input_tokens", usage.get("prompt_tokens"))
        _set_attr(span, "gen_ai.usage.output_tokens", usage.get("completion_tokens"))
        if finish_reason is not None:
            _set_attr(span, "gen_ai.response.finish_reasons", [finish_reason])

        if model_name:
            span.update_name(f"{operation_name} {model_name}")

        if CAPTURE_CONTENT:
            _set_attr(span, "gen_ai.input.messages", process_data.get("prompts"))
            _set_attr(span, "gen_ai.output.messages", outputs.get("text"))

        _set_attr(span, "dify.gen_ai.total_tokens", usage.get("total_tokens"))
        _set_attr(span, "dify.gen_ai.total_price", usage.get("total_price"))
        _set_attr(span, "dify.gen_ai.currency", usage.get("currency"))
        _set_attr(span, "dify.gen_ai.time_to_first_token", usage.get("time_to_first_token"))
        _set_attr(span, "dify.gen_ai.provider_raw", model_provider)

    def _finish_workflow(self, span: Span, data: dict[str, Any]) -> None:
        self._apply_workflow_attrs(span, data)
        span.set_status(_status_code(data.get("status"), data.get("error")))
        self.finish_open_spans()


def parse_sse_data_line(line: str) -> dict[str, Any] | None:
    if not line.startswith("data:"):
        return None
    data = line.removeprefix("data:").strip()
    if not data or data == "[DONE]":
        return None
    try:
        payload = json.loads(data)
    except json.JSONDecodeError:
        logger.debug("Ignoring non-JSON SSE data line")
        return None
    if isinstance(payload, dict):
        return payload
    return None


@asynccontextmanager
async def lifespan(app: FastAPI):
    timeout = httpx.Timeout(REQUEST_TIMEOUT_SECONDS, read=None)
    app.state.client = httpx.AsyncClient(timeout=timeout)
    yield
    await app.state.client.aclose()


app = FastAPI(title="Dify Workflow OTel Exporter", version="0.1.0", lifespan=lifespan)


@app.get("/healthz")
async def healthz() -> JSONResponse:
    return JSONResponse({"status": "ok", "dify_api_base_url": DIFY_API_BASE_URL})


@app.api_route("/{full_path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
async def proxy(full_path: str, request: Request) -> Response:
    body = await request.body()
    target_url = _target_url(request)
    headers = _filtered_request_headers(request)
    client: httpx.AsyncClient = request.app.state.client
    workflow_trace = DifyWorkflowTrace(path=request.url.path, method=request.method)

    should_trace = _is_workflow_path(request.url.path)
    should_stream = should_trace and _is_streaming_request(body, request)

    if should_stream:
        upstream_request = client.build_request(
            request.method,
            target_url,
            headers=headers,
            content=body,
        )
        upstream = await client.send(upstream_request, stream=True)
        response_headers = _filtered_response_headers(upstream.headers)
        media_type = upstream.headers.get("content-type", "text/event-stream")

        if upstream.status_code >= 400:
            response_body = await upstream.aread()
            workflow_trace.finish_http_error(upstream.status_code, response_body)
            await upstream.aclose()
            return Response(content=response_body, status_code=upstream.status_code, headers=response_headers)

        async def stream_generator():
            try:
                async for line in upstream.aiter_lines():
                    payload = parse_sse_data_line(line)
                    if payload is not None:
                        try:
                            workflow_trace.handle_sse_payload(payload)
                        except Exception:
                            logger.exception("Failed to convert Dify SSE payload to span")
                    yield f"{line}\n".encode("utf-8")
            except Exception as exc:
                workflow_trace.finish_open_spans(error=str(exc))
                raise
            finally:
                workflow_trace.finish_open_spans()
                await upstream.aclose()

        return StreamingResponse(
            stream_generator(),
            status_code=upstream.status_code,
            headers=response_headers,
            media_type=media_type,
        )

    upstream_response = await client.request(
        request.method,
        target_url,
        headers=headers,
        content=body,
    )
    response_headers = _filtered_response_headers(upstream_response.headers)

    if should_trace:
        try:
            payload = upstream_response.json()
            if isinstance(payload, dict):
                workflow_trace.handle_blocking_response(payload, upstream_response.status_code)
        except Exception:
            if upstream_response.status_code >= 400:
                workflow_trace.finish_http_error(upstream_response.status_code, upstream_response.content)

    return Response(
        content=upstream_response.content,
        status_code=upstream_response.status_code,
        headers=response_headers,
        media_type=upstream_response.headers.get("content-type"),
    )
