# Recursos de infraestrutura

Este diretório descreve os serviços utilizados pelo `websensors-flow-rag`.

## Ordem de preparação

1. Preparar Docker, rede e portas
2. Instalar Elasticsearch
3. Instalar MinIO e criar os buckets
4. Disponibilizar o serviço de embeddings
5. Instalar Docling Serve
6. Configurar o VLM dentro do Docling quando necessário
7. Configurar MLflow quando desejado
8. Validar toda a infraestrutura
9. Iniciar o serviço RAG

## Guias

| Arquivo | Conteúdo |
| --- | --- |
| `01_requisitos.md` | requisitos e rede |
| `02_elasticsearch.md` | Elasticsearch, BM25 e vetores |
| `03_minio.md` | MinIO e buckets |
| `04_docling.md` | Docling Serve |
| `05_vllm.md` | VLM e embeddings com vLLM |
| `06_litellm.md` | LiteLLM como gateway opcional |
| `07_validacao.md` | validação dos serviços |
| `08_openwebui.md` | integração OpenAPI |
| `09_mlflow.md` | MLflow |

## Serviços obrigatórios

Elasticsearch, MinIO, Docling e embeddings são obrigatórios.

O VLM é necessário apenas quando o preset do Docling utiliza descrição visual externa.

MLflow e Graylog são opcionais.
