from websensors_flow_rag.clients.docling_client import DoclingClient


def test_normalize_docling_result():
    payload = {
        "document": {
            "md_content": "# Título\n\nTexto",
            "json_content": {"name": "documento"},
        },
        "status": "success",
        "processing_time": 1.2,
    }
    result = DoclingClient.normalize_result(payload)
    assert result["markdown"].startswith("# Título")
    assert result["json"]["name"] == "documento"
    assert result["status"] == "success"
