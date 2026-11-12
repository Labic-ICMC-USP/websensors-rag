"""Teste de integração com os documentos de validação e os serviços reais.

Para cada PDF de referência: processa pelo mesmo ProcessDocumentService da API/CLI,
confere Bronze, Silver, chunks/embeddings e índice do tipo (verify-document.py),
compara a classificação com a referência e, por fim, reenvia o mesmo arquivo para
confirmar que nada é reprocessado (action=noop).

Chama Docling, Gemini e embeddings (custo no OpenRouter). O relatório contém só
tipos, status, identificadores e contagens; nunca valores extraídos.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import time
from datetime import datetime, timezone
from pathlib import Path

from websensors_flow_rag.config import load_rag_settings
from websensors_flow_rag.services.process_document import ProcessDocumentService

_spec = importlib.util.spec_from_file_location("verify_document", Path(__file__).with_name("verify-document.py"))
_verify = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_verify)
verify_document = _verify.verify_document

EXPECTED_SILVER = {"markdown", "json", "classification", "extraction", "manifest"}
EMPTY = (None, "", [], {})


def check_document(service, settings, item, content, project, check_noop):
    checks: dict[str, bool] = {}
    row = {"filename": item["filename"], "expected": item["expected_document_type"]}
    started = time.monotonic()
    result = service.process_file(filename=item["filename"], content=content, project=project)
    row["seconds"] = round(time.monotonic() - started, 1)
    row["flow_run_id"] = result.report.run_id
    checks["pipeline_success"] = result.report.status == "success"
    if not checks["pipeline_success"]:
        row.update(checks=checks, ok=False, error=f"{result.failure.step_name}: {result.failure.error_type}" if result.failure else None)
        return row

    output = result.output
    classification = output.get("classification") or {}
    extraction = output.get("extraction") or {}
    data = extraction.get("data") or {}
    row.update(
        action=output.get("action"), document_id=output.get("document_id"), revision_id=output.get("revision_id"),
        predicted=classification.get("document_type"), extraction_status=extraction.get("status"),
        fields_populated=sum(v not in EMPTY for v in data.values()), fields_total=len(data),
        warnings=len(extraction.get("warnings") or []),
    )
    checks["published"] = row["action"] in {"indexed", "updated", "noop", "metadata_updated"}
    checks["classification_correct"] = row["predicted"] == row["expected"]
    checks["extraction_valid"] = row["extraction_status"] in {"success", "needs_review"}
    fields = item.get("extraction_fields_to_check", [])
    # Inconsistências não são campo do schema: o prompt as registra em warnings.
    present = lambda f: bool(extraction.get("warnings")) if f == "avisos_inconsistencias" and f not in data else data.get(f) not in EMPTY
    missing = [f for f in fields if not present(f)]
    checks["reference_fields_present"] = not missing
    row["reference_fields_missing"] = missing

    verified = verify_document(settings, row["document_id"])
    bronze_key = (verified.get("bronze") or {}).get("uri", "")
    checks["bronze_original"] = bool((verified.get("bronze") or {}).get("sha256_matches_source")) and item["sha256"] in bronze_key
    checks["silver_artifacts"] = set(verified.get("silver") or {}) == EXPECTED_SILVER and bool(verified.get("silver_hashes_match_manifest"))
    es = verified.get("elasticsearch") or {}
    checks["chunks_with_embeddings"] = es.get("active_chunks", 0) > 0 and es.get("active_chunks") == es.get("active_chunks_with_embedding")
    structured = verified.get("structured") or {}
    alias = (structured.get("pointer") or {}).get("alias")
    checks["structured_index"] = bool(structured.get("record_active")) and alias == f"{settings.structured_index.index_prefix}-{project}-{row['expected']}"
    checks["verify_document_ok"] = bool(verified.get("ok"))
    row["structured_alias"] = alias

    if check_noop:
        again = service.process_file(filename=item["filename"], content=content, project=project)
        checks["resend_is_noop"] = again.report.status == "success" and again.output.get("action") == "noop" \
            and again.output.get("revision_id") == row["revision_id"]

    row["checks"] = checks
    row["ok"] = all(checks.values())
    return row


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", default="config/rag.local.yaml")
    parser.add_argument("--reference", default="validation/reais-golo.reference.json")
    parser.add_argument("--data-dir", default="validation/data")
    parser.add_argument("--project", default="fai")
    parser.add_argument("--only", nargs="*", help="Processar só estes arquivos (nomes da referência)")
    parser.add_argument("--skip-noop", action="store_true", help="Não reenviar para conferir action=noop")
    parser.add_argument("--output", default=".local/integration/report.json")
    args = parser.parse_args()

    reference = json.loads(Path(args.reference).read_text(encoding="utf-8"))
    items = [i for i in reference["documents"] if not args.only or i["filename"] in args.only]
    settings = load_rag_settings(args.config)
    if not settings.structured_index.enabled:
        raise SystemExit("structured_index desabilitado na configuração; o teste exige o ciclo completo.")
    service = ProcessDocumentService(settings)
    rows = []
    try:
        for item in items:
            path = Path(args.data_dir) / item.get("source_file", item["filename"])
            if not path.is_file():
                rows.append({"filename": item["filename"], "ok": False, "error": "arquivo ausente"})
                print(f"FALTA  {item['filename']}", flush=True)
                continue
            content = path.read_bytes()
            if hashlib.sha256(content).hexdigest() != item["sha256"]:
                raise SystemExit(f"Hash divergente para {item['filename']}; teste interrompido.")
            row = check_document(service, settings, item, content, args.project, not args.skip_noop)
            rows.append(row)
            failed = [name for name, passed in (row.get("checks") or {}).items() if not passed]
            print(f"{'OK   ' if row['ok'] else 'FALHA'}  {item['filename']}  {row.get('predicted')}  "
                  f"{row.get('action')}  {row.get('seconds')}s" + (f"  falhou: {', '.join(failed)}" if failed else ""), flush=True)
    finally:
        service.close()

    passed = sum(bool(r.get("ok")) for r in rows)
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(), "project": args.project,
        "documents": len(rows), "passed": passed, "ok": bool(rows) and passed == len(rows), "results": rows,
    }
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"\n{passed}/{len(rows)} documentos aprovados. Relatório: {out}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
