"""Métricas de consulta sem armazenar conteúdo sensível das perguntas."""

from __future__ import annotations

import logging

from websensors_flow_rag.config import RAGSettings

logger = logging.getLogger("websensors_flow_rag.telemetry")


def record_search(settings: RAGSettings, mode: str, results: int, elapsed_seconds: float) -> None:
    """Registra apenas métricas agregadas. Erros de observabilidade não afetam a busca."""
    cfg = settings.observability.mlflow
    if not cfg.enabled or not cfg.track_searches:
        return
    try:
        from mlflow.tracking import MlflowClient

        client = MlflowClient(tracking_uri=cfg.tracking_uri)
        experiment = client.get_experiment_by_name(cfg.experiment_name)
        if experiment is None:
            logger.warning("Experimento MLflow %s não encontrado para registrar a consulta", cfg.experiment_name)
            return
        run = client.create_run(
            experiment_id=experiment.experiment_id,
            tags={"run_type": "rag_search", "search_mode": mode, "mlflow.runName": f"busca_{mode}"},
        )
        try:
            client.log_metric(run.info.run_id, "search.results", float(results))
            client.log_metric(run.info.run_id, "search.elapsed_seconds", elapsed_seconds)
            client.set_terminated(run.info.run_id, status="FINISHED")
        except Exception:
            try:
                client.set_terminated(run.info.run_id, status="FAILED")
            except Exception:
                pass
            raise
        logger.info("Busca registrada no MLflow. Run %s Modo %s", run.info.run_id, mode)
    except Exception as exc:
        logger.warning("Falha ao registrar busca no MLflow. %s %s", type(exc).__name__, str(exc)[:250])
