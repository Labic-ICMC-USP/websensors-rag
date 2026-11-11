"""Verifica o observer existente sem documentos, embeddings ou indexação."""
from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

from mlflow.tracking import MlflowClient

from websensors_flow import PipelineStep, StepResult
from websensors_flow.pipeline import build_pipeline_from_settings
from websensors_flow_rag.config import load_rag_settings


class ObservabilityProbe(PipelineStep):
    name = "verificar_observabilidade"

    def execute(self, input, context):
        with context.trace("diagnostico_mlflow", metadata={"synthetic": True}):
            with context.progress(total=2, description="Verificando eventos", unit="eventos") as progress:
                progress.update()
                progress.update()
        return StepResult(
            output={"observability": "ok"},
            has_output=True,
            text="Diagnóstico sintético de observabilidade concluído.",
            metrics={"probe_success": 1},
            params={"probe_kind": "synthetic_no_inference"},
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="config/rag.local.yaml")
    args = parser.parse_args()
    settings = load_rag_settings(args.config)
    if not settings.observability.mlflow.enabled:
        raise SystemExit("MLflow não está habilitado no YAML.")
    flow = settings.to_flow_settings()
    flow.steps = []
    flow.observability.mlflow.run_name = "diagnostico-observabilidade"
    pipeline = build_pipeline_from_settings(flow, include_console=False)
    result = pipeline.add(ObservabilityProbe()).run()
    if result.report.status != "success":
        reason = result.failure.error_message if result.failure else "Falha sem detalhes"
        raise SystemExit(f"Falha no observer MLflow: {reason}")
    client = MlflowClient(tracking_uri=settings.observability.mlflow.tracking_uri)
    experiment = client.get_experiment_by_name(settings.observability.mlflow.experiment_name)
    runs = client.search_runs(
        [experiment.experiment_id],
        filter_string=f"tags.run_id = '{pipeline.run_id}' AND tags.run_type = 'pipeline'",
        max_results=1,
    )
    if not runs:
        raise SystemExit("Execução do Flow não encontrada no MLflow.")
    run = runs[0]
    if run.info.status != "FINISHED" or run.data.metrics.get("verificar_observabilidade_probe_success") != 1:
        raise SystemExit("Estado ou métrica do diagnóstico não foi persistido.")
    with tempfile.TemporaryDirectory() as directory:
        artifact = client.download_artifacts(run.info.run_id, "events/events.json", directory)
        events = json.loads(Path(artifact).read_text())
    types = {event["event_type"] for event in events}
    required = {"pipeline_completed", "step_completed", "progress", "trace_completed"}
    if not required <= types:
        raise SystemExit("Eventos do observer incompletos no artefato persistido.")
    report = {
        "tracking_uri": settings.observability.mlflow.tracking_uri,
        "flow_run_id": pipeline.run_id,
        "mlflow_run_id": run.info.run_id,
        "status": run.info.status,
        "metric_verified": True,
        "events_artifact_downloaded": True,
        "event_types": sorted(types),
        "local_inference_calls": 0,
    }
    output = Path(".local/mlflow-validation")
    output.mkdir(parents=True, exist_ok=True, mode=0o700)
    (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
