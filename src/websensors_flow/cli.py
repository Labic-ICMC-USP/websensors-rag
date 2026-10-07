"""Command-line entry points for WebSensors Flow."""

from __future__ import annotations

import argparse

from websensors_flow.api import create_app
from websensors_flow.config import load_settings
from websensors_flow.runner import run_configured_flow


def main_run() -> None:
    """Run a configured flow from the command line."""

    parser = argparse.ArgumentParser(description="Run a WebSensors Flow project.")
    parser.add_argument("--config", default="flows/example_dmoz/flow.yaml", help="Path to the flow YAML file.")
    args = parser.parse_args()

    settings = load_settings(args.config)
    result = run_configured_flow(settings)
    if result.failure is not None:
        print(result.failure.text)


def main_api() -> None:
    """Start the FastAPI runner for a configured flow."""

    parser = argparse.ArgumentParser(description="Serve a WebSensors Flow project through FastAPI.")
    parser.add_argument("--config", default="flows/example_dmoz/flow.yaml", help="Path to the flow YAML file.")
    args = parser.parse_args()

    try:
        import uvicorn
    except Exception as exc:  # pragma: no cover
        raise RuntimeError("Uvicorn is required for API mode. Install websensors-flow with the 'api' extra.") from exc

    settings = load_settings(args.config)
    app = create_app(settings)
    uvicorn.run(app, host=settings.api.host, port=settings.api.port)
