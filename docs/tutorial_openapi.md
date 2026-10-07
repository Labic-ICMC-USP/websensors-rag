# Integração OpenAPI

A especificação fica disponível em `/openapi.json`.

```bash
curl http://localhost:8000/openapi.json
```

As operações principais possuem identificadores estáveis.

| Rota | operationId |
| --- | --- |
| `POST /documents/index` | `indexar_documento` |
| `GET /indexing/{token}` | `consultar_indexacao` |
| `POST /search/bm25` | `buscar_bm25` |
| `POST /search/semantic` | `buscar_semantica` |
| `POST /search/hybrid` | `buscar_hibrida` |
| `GET /documents` | `listar_documentos` |
| `GET /documents/{document_id}` | `obter_documento` |

Essa especificação pode ser importada por interfaces que suportam ferramentas OpenAPI.
