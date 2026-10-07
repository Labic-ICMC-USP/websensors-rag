# LiteLLM

LiteLLM é opcional.

Ele pode funcionar como gateway para o serviço de embeddings e para endpoints utilizados internamente pelo Docling.

## Uso com embeddings

O RAG espera um endpoint compatível com a operação de embeddings.

```yaml
services:
  embeddings:
    endpoint: "http://localhost:4000/v1"
    path: /embeddings
    api_key: "ALTERE_AQUI"
    model: inpi-text-embedding
    dimensions: 1024
```

## Verificar modelos

```bash
curl -s http://localhost:4000/v1/models
```

## Testar embeddings

```bash
curl -X POST http://localhost:4000/v1/embeddings \
  -H 'Content-Type: application/json' \
  -H 'Authorization: Bearer SUA_CHAVE' \
  -d '{
    "model": "inpi-text-embedding",
    "input": ["texto de teste"]
  }'
```

A quantidade de valores no vetor precisa coincidir com `services.embeddings.dimensions`.
