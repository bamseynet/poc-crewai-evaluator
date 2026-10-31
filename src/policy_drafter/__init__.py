"""CrewAI evaluator-optimizer proof of concept for enterprise policy drafting."""

import os

# A proof of concept must run offline and send nothing to third parties by default. CrewAI reads
# these when it is imported, so they have to be set before any `crewai` import.
os.environ.setdefault("CREWAI_TRACING_ENABLED", "false")
os.environ.setdefault("CREWAI_DISABLE_TELEMETRY", "true")
os.environ.setdefault("OTEL_SDK_DISABLED", "true")
