# Tutorial de busca com reranking

O reranking é executado dentro do Elasticsearch com `text_similarity_reranker`.

## Pré requisito

O YAML informa apenas o identificador de inferência:

```yaml
search:
  reranker:
    enabled: true
    inference_id: websensors-rag-rerank
    field: content
    rank_window_size: 30
    top_k: 10
    min_score: null
    chunk_rescorer_enabled: true
    chunk_rescorer_size: 1
```

Confirme o endpoint:

```bash
curl http://localhost:9200/_inference/rerank/websensors-rag-rerank?pretty
```

O resultado precisa informar:

```json
{
  "task_type": "rerank",
  "service": "elasticsearch"
}
```

## Consulta

```bash
curl -X POST http://localhost:8000/search/hybrid/rerank \
  -H 'Content-Type: application/json' \
  -d '{
    "query": "quais erros aparecem antes da estabilização térmica",
    "top_k": 5,
    "debug": true
  }'
```

## Execução no Elasticsearch

A árvore enviada é equivalente a:

```text
text_similarity_reranker
          |
          v
         RRF
        /   \
       /     \
    BM25     kNN
```

O RRF gera a primeira lista. `rank_window_size` define quantos candidatos seguem para o modelo de reranking. `top_k` define quantos resultados finais são solicitados.

## chunk_rescorer

Modelos de reranking possuem limite de tokens. Quando `chunk_rescorer_enabled=true`, o Elasticsearch pode dividir o campo de texto em trechos adequados ao modelo e selecionar os melhores trechos antes da inferência.

Configuração recomendada para o comportamento automático do Elasticsearch:

```yaml
search:
  reranker:
    chunk_rescorer_enabled: true
    chunk_rescorer_size: 1
```

O pacote não configura `chunking_settings` do rescorer. O Elasticsearch usa as configurações associadas ao endpoint de inferência. Avalie a opção com o modelo escolhido, pois o rescorer pode reduzir relevância quando o modelo não usa truncamento simples.

## Modelo integrado

Um endpoint usando o modelo Elastic Rerank pode ser criado no Elasticsearch:

```bash
curl -X PUT http://localhost:9200/_inference/rerank/websensors-rag-rerank \
  -H 'Content-Type: application/json' \
  -d '{
    "service": "elasticsearch",
    "service_settings": {
      "model_id": ".rerank-v1",
      "num_threads": 1,
      "adaptive_allocations": {
        "enabled": true,
        "min_number_of_allocations": 1,
        "max_number_of_allocations": 4
      }
    }
  }'
```

O modelo `.rerank-v1` é destinado a conteúdo em inglês e possui janela máxima de 512 tokens. Para acervo em português, use um modelo `text_similarity` com suporte adequado ao idioma, carregado no próprio Elasticsearch, e crie o endpoint com `service: elasticsearch`.

## Score

No modo `hybrid_rerank`, `reranker_score` recebe `_score` retornado pelo Elasticsearch depois do reranking.

Evite fixar um `min_score` sem avaliar a distribuição do modelo escolhido.
