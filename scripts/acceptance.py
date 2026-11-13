"""Validação de aceitação (Fase G): classifica os originais sem rótulo e compara com a referência.

Usa o mesmo ProcessDocumentService da API/CLI. O relatório contém apenas tipos,
status e contagens; valores extraídos ficam somente no Silver/Elasticsearch.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import time
import zipfile
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from websensors_flow_rag.config import load_rag_settings
from websensors_flow_rag.services.process_document import ProcessDocumentService


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="config/rag.local.yaml")
    parser.add_argument("--reference", default="validation/reais-golo.reference.json")
    parser.add_argument("--archive", default="validation/data/reais-golo.zip")
    parser.add_argument("--extra-dir", default="validation/data", help="Arquivos de referência fora do ZIP (ex.: edital.pdf)")
    parser.add_argument("--project", default="fai")
    parser.add_argument("--output", default=".local/acceptance/report.json")
    args = parser.parse_args()

    reference = json.loads(Path(args.reference).read_text(encoding="utf-8"))
    settings = load_rag_settings(args.config)
    service = ProcessDocumentService(settings)
    rows, missing = [], []
    try:
        archive = zipfile.ZipFile(args.archive) if Path(args.archive).is_file() else None
        try:
            for item in reference["documents"]:
                if "archive_member" in item and archive is not None:
                    content = archive.read(item["archive_member"])
                else:
                    # ZIP ausente ou arquivo fornecido separadamente: ler o PDF solto.
                    path = Path(args.extra_dir) / item.get("source_file", item["filename"])
                    if not path.is_file():
                        missing.append(item["filename"])
                        continue
                    content = path.read_bytes()
                if hashlib.sha256(content).hexdigest() != item["sha256"]:
                    raise SystemExit(f"Hash divergente para {item['filename']}; avaliação interrompida.")
                started = time.monotonic()
                result = service.process_file(filename=item["filename"], content=content, project=args.project)
                output = result.output if isinstance(result.output, dict) else {}
                classification = output.get("classification") or {}
                extraction = output.get("extraction") or {}
                data = extraction.get("data") or {}
                rows.append({
                    "filename": item["filename"],
                    "expected": item["expected_document_type"],
                    "predicted": classification.get("document_type"),
                    "correct": classification.get("document_type") == item["expected_document_type"],
                    "classification_needs_review": classification.get("needs_review"),
                    "pipeline_status": result.report.status,
                    "action": output.get("action"),
                    "document_id": output.get("document_id"),
                    "revision_id": output.get("revision_id"),
                    "flow_run_id": result.report.run_id,
                    "extraction_status": extraction.get("status"),
                    "fields_total": len(data),
                    "fields_populated": sum(v not in (None, "", [], {}) for v in data.values()),
                    "sources": len(extraction.get("sources") or []),
                    "warnings_count": len(extraction.get("warnings") or []),
                    "structured_alias": (output.get("structured") or {}).get("alias"),
                    "fields_to_check": item.get("extraction_fields_to_check", []),
                    "fields_checked_present": [f for f in item.get("extraction_fields_to_check", []) if data.get(f) not in (None, "", [], {})],
                    "seconds": round(time.monotonic() - started, 2),
                })
                print(json.dumps({k: rows[-1][k] for k in ("filename", "expected", "predicted", "pipeline_status", "extraction_status")}, ensure_ascii=False), flush=True)
        finally:
            if archive is not None:
                archive.close()
    finally:
        service.close()

    labels = sorted({r["expected"] for r in rows} | {r["predicted"] or "falha" for r in rows})
    confusion = {e: {p: 0 for p in labels} for e in labels}
    per_category = defaultdict(lambda: {"total": 0, "correct": 0})
    for r in rows:
        confusion[r["expected"]][r["predicted"] or "falha"] += 1
        per_category[r["expected"]]["total"] += 1
        per_category[r["expected"]]["correct"] += int(r["correct"])
    correct = sum(r["correct"] for r in rows)
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "dataset": reference.get("dataset"),
        "classification_model": settings.services.llm.model if settings.services.llm else None,
        "documents_evaluated": len(rows),
        "documents_missing": missing,
        "categories_evaluated": len({r["expected"] for r in rows}),
        "accuracy": correct / len(rows) if rows else 0.0,
        "required_accuracy": reference.get("classification_acceptance", {}).get("required_accuracy", 1.0),
        "per_category": dict(per_category),
        "confusion_matrix": confusion,
        "errors": [r for r in rows if not r["correct"] or r["pipeline_status"] != "success"],
        "extraction_status_counts": dict(Counter(r["extraction_status"] for r in rows)),
        "documents": rows,
    }
    report["classification_approved"] = bool(rows) and not missing and report["accuracy"] >= report["required_accuracy"]
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("documents_evaluated", "documents_missing", "accuracy", "classification_approved")}, ensure_ascii=False))
    return 0 if report["accuracy"] >= report["required_accuracy"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
