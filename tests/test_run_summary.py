from websensors_flow.observers.base import PipelineObserver
from websensors_flow.observers.mlflow import build_run_summary_markdown
from websensors_flow_rag.services.process_document import ProcessDocumentService

from test_extraction_pipeline import configure
from test_processing import processing  # noqa: F401 - fixture


class Capture(PipelineObserver):
    name = "capture"

    def __init__(self):
        self.events = []

    def on_event(self, event):
        self.events.append(event.model_dump(mode="json"))


def test_summary_has_result_and_steps_without_extracted_values(processing, tmp_path, monkeypatch):  # noqa: F811
    configure(processing, tmp_path, monkeypatch)
    settings, *_ = processing
    service = ProcessDocumentService(settings)
    try:
        request = service.prepare_upload(filename="ficha-joao.pdf", content=b"original", project="fai", document_type="ficha_inscricao")
        capture = Capture()
        result = service.run(request, observers=[capture])
        assert result.report.status == "success", result.failure
        summary = build_run_summary_markdown(capture.events, "success")
    finally:
        service.close()
    assert "| Status | **success** |" in summary
    assert f"| revision_id | {result.output['revision_id']} |" in summary
    assert "| document_type | ficha_inscricao |" in summary
    assert "| extraction_status | success |" in summary
    assert "| extraction_fields_populated | 1 |" in summary
    assert "| publicar_revisao | ok |" in summary
    # Valores extraídos, evidências e nome do arquivo não entram no resumo.
    assert "matrícula acadêmica" not in summary and "ficha-joao" not in summary


def test_summary_reports_failure():
    events = [
        {"event_type": "pipeline_started", "pipeline_name": "p", "run_id": "abc", "timestamp": "t"},
        {"event_type": "step_completed", "step_name": "a", "duration_seconds": 1.5, "metrics": {"x": 1}},
        {"event_type": "step_failed", "step_name": "b", "error_type": "ValueError", "error_message": "falhou | aqui"},
        {"event_type": "pipeline_failed", "duration_seconds": 2.0},
    ]
    summary = build_run_summary_markdown(events, "failed")
    assert "| Status | **failed** |" in summary and "`abc`" in summary
    assert "- **b**: `ValueError` — falhou \\| aqui" in summary
    assert "| 1 | a | ok | 1.50 | x=1 |" in summary and "| 2 | b | falhou |" in summary


def test_root_artifact_is_logged_without_dot_path(tmp_path):
    from types import SimpleNamespace
    import tempfile
    from websensors_flow.observers.mlflow import MLflowObserver

    logged = []
    observer = MLflowObserver.__new__(MLflowObserver)
    observer._mlflow = SimpleNamespace(log_artifact=lambda path, artifact_path=None: logged.append(artifact_path))
    observer._tmpdir = tempfile.TemporaryDirectory()
    observer._log_text_file("x", artifact_path="resumo.md")
    observer._log_text_file("x", artifact_path="steps/a.md")
    observer._tmpdir.cleanup()
    assert logged == [None, "steps"]
