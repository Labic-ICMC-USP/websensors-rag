# OpenWebUI

A API publica uma especificação OpenAPI que pode ser utilizada por interfaces compatíveis.

## Endpoint OpenAPI

```text
http://HOST:8000/openapi.json
```

## Operações de busca

```text
buscar_bm25
buscar_semantica
buscar_hibrida
```

Para recuperação geral, a busca híbrida é uma boa operação padrão porque combina correspondência lexical e proximidade semântica com RRF.

## Exemplo de consulta híbrida

```bash
curl -X POST http://localhost:8000/search/hybrid \
  -H 'Content-Type: application/json' \
  -d '{
    "query": "compensação térmica no aquecimento inicial",
    "top_k": 10
  }'
```

## Indexação

A operação `indexar_documento` inicia um job assíncrono.

A operação `consultar_indexacao` permite acompanhar o token até `success` ou `failed`.
