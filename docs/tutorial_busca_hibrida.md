# Tutorial de busca híbrida

A busca híbrida executa BM25 e kNN no Elasticsearch e aplica RRF no serviço `websensors-flow-rag`.

## Objetivo

BM25 favorece correspondência lexical.

kNN favorece proximidade semântica.

RRF combina as posições dos dois rankings sem exigir que os scores estejam na mesma escala.

Para cada documento, o algoritmo soma contribuições calculadas a partir de sua posição em cada lista. Uma ocorrência entre os primeiros resultados de BM25 e kNN aumenta a pontuação de fusão. Um documento ausente de uma das listas recebe contribuição somente da lista em que apareceu.

A pontuação final é usada para ordenar os resultados. Ela não representa uma probabilidade de relevância e não deve ser interpretada como similaridade cosseno.

## Consulta simples

```bash
curl -X POST http://localhost:8000/search/hybrid \
  -H 'Content-Type: application/json' \
  -d '{
    "query": "compensação térmica no início da operação",
    "top_k": 10
  }'
```

## Consulta com diagnóstico

```bash
curl -X POST http://localhost:8000/search/hybrid \
  -H 'Content-Type: application/json' \
  -d '{
    "query": "compensação térmica no início da operação",
    "top_k": 10,
    "debug": true
  }'
```

Exemplo conceitual do diagnóstico.

```json
{
  "engine": "elasticsearch+application",
  "retrieval": "rrf",
  "fusion": "application",
  "components": ["bm25", "knn"],
  "rank_window_size": 50,
  "rank_constant": 60
}
```

## Consultas enviadas ao Elasticsearch

O vetor da consulta é gerado previamente pelo serviço de embeddings. A aplicação executa duas buscas independentes no Elasticsearch. Os dois ramos usam os mesmos filtros, inclusive a condição de revisão ativa.

```python
query = "compensação térmica"
vetor = obter_embedding(query)
filtros = [{"term": {"active": True}}]

bm25 = {
    "size": 50,
    "query": {
        "bool": {
            "must": [{
                "multi_match": {
                    "query": query,
                    "fields": ["title^3", "heading_text^2.5", "section^2", "content"],
                }
            }],
            "filter": filtros,
        }
    },
}

semantica = {
    "size": 50,
    "knn": {
        "field": "embedding",
        "query_vector": vetor,
        "k": 50,
        "num_candidates": 200,
        "filter": {"bool": {"filter": filtros}},
    },
}

ranking_bm25 = elasticsearch.search(bm25)
ranking_semantico = elasticsearch.search(semantica)
resultado = aplicar_rrf(ranking_bm25, ranking_semantico, rank_constant=60)
```

Na utilização normal, a aplicação constrói as duas consultas automaticamente a partir de `POST /search/hybrid` e aplica a fusão RRF depois de receber os rankings.

## Filtros

Os mesmos filtros são aplicados ao ramo lexical e ao ramo vetorial.

```bash
curl -X POST http://localhost:8000/search/hybrid \
  -H 'Content-Type: application/json' \
  -d '{
    "query": "modelo de compensação",
    "top_k": 10,
    "filters": {
      "empresa": "ROMI",
      "ano": 2026
    }
  }'
```

## Ajuste de rank_window_size

Uma janela pequena reduz a quantidade de candidatos disponíveis para a fusão.

Uma janela maior oferece mais candidatos para cada uma das duas buscas e aumenta o volume de resultados processado pela aplicação.

A avaliação deve usar consultas reais do domínio e métricas como Recall@K, MRR e nDCG@K.

## Ajuste de rank_constant

Valores maiores reduzem a diferença de contribuição entre posições próximas.

Valores menores aumentam a vantagem dos primeiros colocados em cada ranking.

O valor deve ser avaliado empiricamente em um conjunto de consultas anotadas.

## Comparação com as outras modalidades

Use a mesma consulta, os mesmos filtros e o mesmo `top_k`.

```text
/search/bm25
/search/semantic
/search/hybrid
```

A comparação permite observar casos em que termos exatos favorecem BM25, casos em que paráfrases favorecem kNN e casos em que o RRF recupera evidências úteis dos dois mecanismos.
