# Tutorial de busca semântica

A busca semântica transforma a consulta em um vetor e executa kNN no índice de chunks.

Ela é útil quando a pergunta e o documento expressam a mesma ideia com palavras diferentes.

## Consulta básica

```bash
curl -X POST http://localhost:8000/search/semantic \
  -H 'Content-Type: application/json' \
  -d '{
    "query": "o que acontece quando a máquina termina de aquecer",
    "top_k": 5
  }'
```

## Fluxo

```text
consulta textual
      |
      v
serviço de embeddings
      |
      v
vetor da consulta
      |
      v
kNN no Elasticsearch
      |
      v
chunks mais próximos
```

## Candidatos

```yaml
search:
  semantic:
    candidates: 50
    num_candidates: 200
```

`num_candidates` controla o conjunto aproximado considerado pelo Elasticsearch antes de selecionar os vizinhos finais.

## Busca com filtros

```bash
curl -X POST http://localhost:8000/search/semantic \
  -H 'Content-Type: application/json' \
  -d '{
    "query": "efeito do aquecimento sobre a precisão",
    "top_k": 10,
    "filters": {
      "colecao": "relatorios",
      "ano": 2026
    }
  }'
```

O filtro é aplicado dentro da busca vetorial.

## Cuidados

O modelo usado na indexação e o modelo usado na consulta precisam ser compatíveis.

A dimensão configurada precisa coincidir com a dimensão real dos vetores.

Trocar o modelo de embedding exige nova indexação dos chunks.
