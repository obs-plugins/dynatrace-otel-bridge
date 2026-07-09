# Legacy — Track B (Dify Workflow OTel Exporter)

Este diretório contém o **Track B**, aposentado na v1.

## O que era
Um reverse-proxy (FastAPI + httpx) que se colocava à frente da API de Workflows
do Dify (porta 8088), intercetava `/v1/workflows/run`, fazia parse do stream SSE
e emitia spans OTel com atributos GenAI, além de uma métrica de tokens
(`gen_ai.client.token.usage`) via MeterProvider.

## Porque foi aposentado
O Dify passou a emitir instrumentação OTel nativa madura ao nível do GraphEngine
(`ObservabilityLayer`), cobrindo todos os caminhos de invocação (Studio, WebApp,
API, Debugger) — um superconjunto do que o proxy cobria (só HTTP síncrono na 8088).
Os processadores de conformidade OTTL no Collector (Fatias 1–8) normalizam o
dialeto nativo para as convenções oficiais, e a app AI Observability do Dynatrace
popula tokens/custo a partir dos atributos de span, sem precisar da métrica dedicada.

Teste de paridade (exporter parado): spans de nó LLM, models, tokens e provider
continuaram a chegar via `langgenius/dify`; `dify-workflow-otel-exporter` deixou de
emitir. Track B confirmado redundante.

## Se precisares no futuro
A lógica do MeterProvider de tokens (`main.py`) pode ser reaproveitada caso surja
um requisito de métrica que o Track A não satisfaça. O `sumconnector` NÃO está na
distribuição dynatrace/dynatrace-otel-collector, por isso reintroduzir métricas de
token via Collector exigiria um build custom (OCB).
