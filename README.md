# WebSensors Flow RAG

`websensors-flow-rag` fornece uma API para indexação documental e recuperação lexical, semântica e híbrida.

O MinIO armazena os arquivos de origem e os artefatos derivados. O Docling centraliza a conversão de PDFs, imagens e outros formatos suportados. A saída documental é preservada em Markdown e JSON. O serviço gera chunks estruturais, cria embeddings e publica os dados no Elasticsearch.

A recuperação oferece três modalidades.

| Modalidade | Funcionamento |
| --- | --- |
| BM25 | recuperação lexical executada pelo Elasticsearch |
| Semântica | embedding da consulta e busca kNN no Elasticsearch |
| Híbrida | BM25 e kNN no Elasticsearch com fusão RRF realizada pela aplicação |

## Componentes

| Componente | Responsabilidade |
| --- | --- |
| MinIO | arquivos originais e artefatos Markdown, JSON e manifesto |
| Docling Serve | conversão, OCR, estrutura, tabelas e descrição de imagens |
| VLM configurado no Docling | descrição visual quando habilitada no preset |
| Serviço de embeddings | vetorização dos chunks e das consultas |
| Elasticsearch | documentos, chunks, BM25, kNN e filtros |
| FastAPI | indexação assíncrona, busca síncrona e OpenAPI |
| MLflow | rastreamento de execuções quando habilitado |
| Graylog | centralização de logs quando habilitado |

## Fluxo de indexação

```text
MinIO Bronze
    |
    v
Resolver fonte
    |
    v
Detectar alterações
    |
    v
Docling Serve
    |
    +--> Markdown
    |
    +--> JSON estrutural
    |
    v
MinIO Silver
    |
    v
Chunking estrutural
    |
    v
Embeddings
    |
    v
Preparar revisão no Elasticsearch
    |
    v
Validar revisão
    |
    v
Publicar revisão ativa
```

Cada revisão recebe um identificador derivado do conteúdo de origem e da configuração de processamento. Os novos chunks são preparados como inativos. A revisão só passa a responder às buscas depois da validação completa.

Quando apenas os metadados mudam, o serviço atualiza os documentos e os chunks ativos sem repetir Docling, chunking ou embeddings.

## Fluxo de busca híbrida

```text
                         consulta
                            |
               +------------+------------+
               |                         |
               v                         v
             BM25                embedding da consulta
               |                         |
               |                         v
               |                    busca kNN
               |                         |
               +------------+------------+
                            |
                            v
                           RRF
                            |
                            v
                        resultados
```

O Elasticsearch executa BM25 e kNN separadamente. A aplicação recebe as duas listas e aplica RRF usando as posições dos resultados. Não existe soma direta entre score BM25 e similaridade vetorial. Esse desenho não depende do retriever RRF nativo do Elasticsearch.

## Configuração

A configuração fica em um único arquivo YAML.

```bash
cp config/rag.yaml config/rag.local.yaml
chmod 600 config/rag.local.yaml
```

Trecho principal.

```yaml
services:
  minio:
    endpoint: "http://localhost:9000"
    access_key: "ALTERE_AQUI"
    secret_key: "ALTERE_AQUI"
    bronze_bucket: rag-bronze
    silver_bucket: rag-silver

  elasticsearch:
    endpoint: "http://localhost:9200"
    username: elastic
    password: "ALTERE_AQUI"
    verify_certs: false

  docling:
    endpoint: "http://localhost:5001"
    options:
      do_ocr: true
      ocr_preset: rapidocr
      do_picture_description: true
      picture_description_preset: labic_vision

  embeddings:
    endpoint: "http://localhost:4000/v1"
    path: /embeddings
    api_key: "ALTERE_AQUI"
    model: inpi-text-embedding
    dimensions: 1024

search:
  default_top_k: 10
  max_top_k: 50
  semantic:
    candidates: 50
    num_candidates: 200
  hybrid:
    rank_window_size: 50
    rank_constant: 60
```

## Inicialização

O diagnóstico verifica Elasticsearch, MinIO, Docling e embeddings antes de criar ou validar índices.

```bash
websensors-flow-rag-health --config config/rag.local.yaml
```

A API pode ser iniciada em seguida.

```bash
websensors-flow-rag-api --config config/rag.local.yaml
```

A saída do terminal apresenta os serviços em uma tabela. Durante cada indexação, os nove steps são exibidos individualmente com estado, duração, métricas, progresso e ETA.

## API

Endereços padrão.

```text
API       http://localhost:8000
Swagger   http://localhost:8000/docs
OpenAPI   http://localhost:8000/openapi.json
Health    http://localhost:8000/health
```

Principais operações.

| Método | Rota | Finalidade |
| --- | --- | --- |
| POST | `/documents/index` | indexar ou atualizar documento |
| GET | `/indexing/{token}` | acompanhar indexação |
| GET | `/documents` | listar documentos |
| GET | `/documents/{document_id}` | obter documento |
| POST | `/search/bm25` | executar busca lexical |
| POST | `/search/semantic` | executar busca semântica |
| POST | `/search/hybrid` | executar busca híbrida com RRF |

## Exemplo de indexação

O objeto precisa existir no bucket Bronze.

```bash
curl -X POST http://localhost:8000/documents/index \
  -H 'Content-Type: application/json' \
  -d '{
    "key": "documentos/relatorio.pdf",
    "metadata": {
      "empresa": "ROMI",
      "ano": 2026,
      "tipo": "relatorio"
    }
  }'
```

A resposta contém um token que pode ser consultado durante o processamento.

```bash
curl http://localhost:8000/indexing/SEU_TOKEN
```

## Exemplo de busca BM25

```bash
curl -X POST http://localhost:8000/search/bm25 \
  -H 'Content-Type: application/json' \
  -d '{
    "query": "compensação térmica",
    "top_k": 10
  }'
```

## Exemplo de busca semântica

```bash
curl -X POST http://localhost:8000/search/semantic \
  -H 'Content-Type: application/json' \
  -d '{
    "query": "erros durante o aquecimento inicial da máquina",
    "top_k": 10
  }'
```

## Exemplo de busca híbrida

```bash
curl -X POST http://localhost:8000/search/hybrid \
  -H 'Content-Type: application/json' \
  -d '{
    "query": "compensação térmica durante o início da operação",
    "top_k": 10,
    "debug": true
  }'
```

## Notebook Jupyter

O notebook assume que a API e os serviços já estão em execução. Ele começa diretamente pelo envio de documentos ao MinIO e pela indexação via API.

O tutorial cobre indexação, acompanhamento dos steps, inspeção dos artefatos Silver, BM25, busca semântica, busca híbrida, filtros, atualizações e comparação dos rankings.

```text
notebooks/tutorial_completo.ipynb
```

## Documentação

| Arquivo | Conteúdo |
| --- | --- |
| `docs/arquitetura.md` | arquitetura e responsabilidades |
| `docs/configuracao.md` | YAML completo |
| `docs/api.md` | contratos HTTP |
| `docs/tutorial_indexacao.md` | indexação e atualização |
| `docs/tutorial_busca_bm25.md` | busca lexical |
| `docs/tutorial_busca_semantica.md` | busca vetorial |
| `docs/tutorial_busca_hibrida.md` | BM25, kNN e RRF |
| `docs/tutorial_observabilidade.md` | terminal, ETA, MLflow e Graylog |
| `docs/tutorial_jupyter.md` | uso do notebook |
| `resources/README.md` | instalação dos serviços |
