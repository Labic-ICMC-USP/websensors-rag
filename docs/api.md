# API

A API oferece indexação assíncrona e buscas síncronas.

## Descrição do serviço

```http
GET /rag
```

## Saúde

```http
GET /health
```

O endpoint verifica Elasticsearch, MinIO, Docling e embeddings. MLflow e Graylog aparecem quando estão habilitados.

## Iniciar indexação

```http
POST /documents/index
```

Exemplo de corpo.

```json
{
  "key": "documentos/relatorio.pdf",
  "metadata": {
    "empresa": "ROMI",
    "ano": 2026
  },
  "force": false
}
```

Resposta HTTP 202.

```json
{
  "token": "TOKEN",
  "status": "queued",
  "terminal": false,
  "document_id": "DOCUMENT_ID",
  "message": "Documento aceito para indexação.",
  "status_url": "/indexing/TOKEN"
}
```

## Consultar indexação

```http
GET /indexing/{token}
```

O campo `progress` informa o step atual e os eventos de progresso internos mais recentes.

## Listar documentos

```http
GET /documents?limit=50
```

## Obter documento

```http
GET /documents/{document_id}
```

## Busca BM25

```http
POST /search/bm25
```

```json
{
  "query": "compensação térmica",
  "top_k": 10,
  "filters": {},
  "debug": false
}
```

## Busca semântica

```http
POST /search/semantic
```

O serviço cria o embedding da consulta e executa kNN no Elasticsearch.

## Busca híbrida

```http
POST /search/hybrid
```

A busca híbrida executa BM25 e kNN separadamente no Elasticsearch. O serviço combina os dois rankings com RRF antes de retornar os resultados.

Exemplo com diagnóstico.

```json
{
  "query": "compensação térmica durante o aquecimento",
  "top_k": 10,
  "filters": {
    "empresa": "ROMI"
  },
  "debug": true
}
```

O bloco `debug` informa a janela e a constante do RRF, a quantidade de candidatos de cada busca, os tempos reportados pelo Elasticsearch para BM25 e kNN e o tempo da fusão na aplicação.
