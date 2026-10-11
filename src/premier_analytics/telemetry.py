"""OpenTelemetry tracing (A-7).

Each AI moment is one trace: a root span per moment and audience, with a child span per
agent step (Explainer, Critic, Personaliser, Translator) using the OpenTelemetry GenAI
conventions. Agent Framework adds its own spans for the underlying model calls. With
APPLICATIONINSIGHTS_CONNECTION_STRING set, everything is exported to the Application
Insights resource attached to the Foundry project, so traces show in both places.
Without it, spans go nowhere and cost nothing.
"""
from __future__ import annotations

from opentelemetry import trace

tracer = trace.get_tracer("premier_analytics")


def configure(connection_string: str | None, service_version: str = "dev") -> bool:
    """Export traces to Azure Monitor. Returns False (and does nothing) without a connection string."""
    if not connection_string:
        return False
    from agent_framework.observability import enable_instrumentation
    from azure.monitor.opentelemetry import configure_azure_monitor
    from opentelemetry.sdk.resources import Resource

    configure_azure_monitor(
        connection_string=connection_string,
        resource=Resource.create({"service.name": "premier-analytics", "service.version": service_version}),
    )
    # Prompts and completions stay out of telemetry; spans carry names, models, timings and outcomes.
    enable_instrumentation(enable_sensitive_data=False)
    return True
