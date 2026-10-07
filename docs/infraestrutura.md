# Infraestrutura

O diretório `resources` contém guias independentes para instalar e validar cada serviço.

| Guia | Conteúdo |
| --- | --- |
| `resources/01_requisitos.md` | Docker, rede e portas |
| `resources/02_elasticsearch.md` | Elasticsearch, índices, BM25 e kNN |
| `resources/03_minio.md` | MinIO e buckets |
| `resources/04_docling.md` | Docling Serve, OCR, Markdown e JSON |
| `resources/05_vllm.md` | serviço de VLM ou embeddings quando necessário |
| `resources/06_litellm.md` | gateway compatível com OpenAI |
| `resources/07_validacao.md` | validação da pilha completa |
| `resources/08_openwebui.md` | integração pela especificação OpenAPI |
| `resources/09_mlflow.md` | MLflow |

O RAG exige Elasticsearch, MinIO, Docling e embeddings.

O VLM é opcional e pertence à configuração interna do Docling.

LiteLLM é opcional quando o endpoint de embeddings já é compatível com o contrato esperado.

MLflow e Graylog são opcionais.
