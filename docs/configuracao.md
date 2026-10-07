# Configuração

O serviço utiliza um único arquivo YAML.

## Projeto e ambiente

```yaml
project:
  name: websensors-flow-rag
  description: "Serviço de indexação e recuperação documental para RAG."

environment:
  name: local
  deployment_id: rag-local
  owner: labic
```

## Runtime

```yaml
runtime:
  report_dir: ./outputs/reports
  include_traceback: true
  raise_on_failure: false
  console:
    enabled: true
    progress: true
    show_metrics: true
```

A opção `progress` habilita eventos de progresso e ETA durante loops internos.

A opção `show_metrics` inclui as métricas produzidas por cada step no terminal.

## MinIO

```yaml
services:
  minio:
    endpoint: "http://localhost:9000"
    access_key: "ALTERE_AQUI"
    secret_key: "ALTERE_AQUI"
    secure: false
    bronze_bucket: rag-bronze
    silver_bucket: rag-silver
    silver_prefix: documentos
    timeout_seconds: 10
```

## Elasticsearch

```yaml
services:
  elasticsearch:
    endpoint: "http://localhost:9200"
    username: elastic
    password: "ALTERE_AQUI"
    verify_certs: false
    timeout_seconds: 30
    index_creation_timeout_seconds: 180
    indices:
      documents: websensors-rag-documents-v1
      chunks: websensors-rag-chunks-v1
    aliases:
      documents: websensors-rag-documents
      chunks: websensors-rag-chunks
    shards: 1
    replicas: 0
```

## Docling

```yaml
services:
  docling:
    endpoint: "http://localhost:5001"
    timeout_seconds: 600
    poll_interval_seconds: 1
    options:
      from_formats:
        - pdf
        - image
        - docx
        - pptx
        - html
        - md
        - xlsx
      image_export_mode: placeholder
      do_ocr: true
      force_ocr: false
      pdf_backend: dlparse_v4
      table_mode: accurate
      ocr_preset: rapidocr
      pipeline: standard
      abort_on_error: false
      do_table_structure: true
      do_picture_description: true
      picture_description_preset: labic_vision
      do_picture_classification: true
```

O preset visual pertence ao Docling. O RAG não chama um VLM diretamente.

## Embeddings

```yaml
services:
  embeddings:
    endpoint: "http://localhost:4000/v1"
    path: /embeddings
    api_key: "ALTERE_AQUI"
    model: inpi-text-embedding
    dimensions: 1024
    batch_size: 32
    timeout_seconds: 120
```

A dimensão configurada precisa coincidir com a dimensão real retornada pelo modelo e com o mapping `dense_vector` do índice de chunks.

## Verificação na inicialização

```yaml
startup:
  enabled: true
  retries: 2
  retry_interval_seconds: 2
  timeout_seconds: 10
  validate_embedding_vector: true
  check_mlflow_write: true
```

A validação cobre Elasticsearch, MinIO, Docling e embeddings. MLflow e Graylog entram no diagnóstico quando estão habilitados.

## Chunking

```yaml
indexing:
  processing_version: "1"
  chunking:
    strategy: structural
    target_tokens: 600
    max_tokens: 900
    overlap_tokens: 80
    min_chunk_tokens: 40
```

`processing_version` deve mudar quando uma alteração lógica precisa invalidar os resultados de processamento existentes.

## Busca lexical

```yaml
search:
  lexical:
    fields:
      - title^3
      - heading_text^2.5
      - section^2
      - content
```

Os pesos favorecem título, hierarquia de seções e seção antes do corpo do chunk.

## Busca semântica

```yaml
search:
  semantic:
    candidates: 50
    num_candidates: 200
```

`num_candidates` controla a quantidade de candidatos aproximados considerados pelo kNN.

## Busca híbrida

```yaml
search:
  hybrid:
    rank_window_size: 50
    rank_constant: 60
```

`rank_window_size` define a janela de candidatos usada pelo RRF.

`rank_constant` controla a suavização da contribuição das posições de ranking.

## API

```yaml
api:
  host: "0.0.0.0"
  port: 8000
  indexing_workers: 4
  event_history_limit: 1000
  cors_origins: []
  auth:
    enabled: false
    token: null
```

`indexing_workers` controla quantas indexações podem executar em paralelo dentro do processo da API.
