# Elasticsearch

O Elasticsearch armazena documentos e chunks e executa BM25 e kNN. A fusão RRF da busca híbrida é feita pelo `websensors-flow-rag`.

## Execução com Docker

Exemplo para um nó local.

```bash
docker run -d \
  --name websensors-elasticsearch \
  --network websensors-rag \
  -p 9200:9200 \
  -e discovery.type=single-node \
  -e xpack.security.enabled=false \
  -e ES_JAVA_OPTS="-Xms4g -Xmx4g" \
  -v websensors-es-data:/usr/share/elasticsearch/data \
  docker.elastic.co/elasticsearch/elasticsearch:9.5.5
```

Em produção, habilite segurança, TLS, autenticação e persistência adequada.

## Verificar o cluster

```bash
curl -s http://localhost:9200/
curl -s http://localhost:9200/_cluster/health?pretty
```

O cluster precisa estar `green` ou `yellow` para a inicialização do RAG.

## Índices usados pelo RAG

O serviço cria dois índices físicos e dois aliases.

```text
websensors-rag-documents-v1
websensors-rag-chunks-v1
websensors-rag-documents
websensors-rag-chunks
```

Os nomes podem ser alterados no YAML.

## Vetores

O campo `embedding` utiliza `dense_vector` com indexação habilitada e similaridade cosseno.

A dimensão é obtida de `services.embeddings.dimensions`.

A dimensão do índice e a dimensão retornada pelo modelo precisam coincidir.

## BM25

BM25 utiliza os campos textuais definidos em `search.lexical.fields`.

## kNN

A busca semântica utiliza o campo `embedding` e recebe o vetor produzido pelo serviço de embeddings.

O filtro de metadados entra na própria busca kNN.

## Busca híbrida

A busca híbrida não depende do retriever RRF nativo do Elasticsearch. O serviço executa uma consulta BM25 e uma consulta kNN e combina as posições dos resultados na aplicação.

```text
1. Executar BM25 no Elasticsearch
2. Executar kNN no Elasticsearch
3. Receber até rank_window_size candidatos de cada ranking
4. Somar 1 / (rank_constant + posição) para cada ocorrência
5. Ordenar pela pontuação RRF
6. Retornar top_k resultados
```

O RRF combina posições dos rankings. Isso evita somar diretamente scores que possuem escalas diferentes e permite usar a busca híbrida sem depender do recurso RRF nativo do Elasticsearch.

## Diagnóstico de shards

```bash
curl -s http://localhost:9200/_cat/shards?v
```

Quando o cluster está `red`, consulte a explicação de alocação.

```bash
curl -s -X POST http://localhost:9200/_cluster/allocation/explain?pretty \
  -H 'Content-Type: application/json' \
  -d '{}'
```
