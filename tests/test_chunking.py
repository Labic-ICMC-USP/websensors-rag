from websensors_flow_rag.config import ChunkingSettings
from websensors_flow_rag.indexing.chunking import attach_pages, structural_chunks


def test_structural_chunking_preserves_section():
    markdown = """# Relatório\n\n## Resultados\n\nPrimeiro parágrafo importante sobre compensação térmica.\n\nSegundo parágrafo com resultados experimentais.\n"""
    settings = ChunkingSettings(target_tokens=64, max_tokens=128, overlap_tokens=10, min_chunk_tokens=1)
    title, chunks = structural_chunks(markdown, settings)
    assert title == "Relatório"
    assert chunks
    assert chunks[0]["section"] == "Resultados"
    assert "Título: Relatório" in chunks[0]["embedding_text"]


def test_attach_pages_from_docling_json():
    chunks = [
        {
            "content": "Primeiro parágrafo importante sobre compensação térmica.",
        }
    ]
    docling_json = {
        "texts": [
            {
                "text": "Primeiro parágrafo importante sobre compensação térmica.",
                "prov": [{"page_no": 3}],
            }
        ]
    }
    attach_pages(chunks, docling_json)
    assert chunks[0]["page_start"] == 3
    assert chunks[0]["page_end"] == 3
