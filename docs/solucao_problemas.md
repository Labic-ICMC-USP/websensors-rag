# Solução de problemas

## Elasticsearch em estado red

Consulte a saúde do cluster.

```bash
curl -s http://localhost:9200/_cluster/health?pretty
```

Liste os shards.

```bash
curl -s http://localhost:9200/_cat/shards?v
```

Solicite uma explicação de alocação.

```bash
curl -s -X POST http://localhost:9200/_cluster/allocation/explain?pretty \
  -H 'Content-Type: application/json' \
  -d '{}'
```

A API não inicia enquanto o cluster permanecer em estado `red`.

## Credencial inválida no MinIO

Erro comum.

```text
InvalidAccessKeyId
```

Confira `services.minio.endpoint`, `services.minio.access_key` e `services.minio.secret_key`.

Confirme também se a credencial possui acesso aos buckets Bronze e Silver.

## Docling indisponível

```bash
curl -s http://localhost:5001/health
curl -s http://localhost:5001/ready
```

Os dois endpoints precisam responder com sucesso.

## Modelo de embeddings ausente

Consulte o catálogo do endpoint compatível com OpenAI.

```bash
curl -s http://localhost:4000/v1/models
```

Confirme o valor de `services.embeddings.model`.

## Dimensão de embedding incompatível

O mapping do índice de chunks precisa ter a mesma dimensão configurada no YAML.

Quando a dimensão muda, crie um novo índice físico e atualize o alias.

## Timeout ao criar índice

Aumente `services.elasticsearch.index_creation_timeout_seconds` quando o cluster estiver saudável, mas a criação exigir mais tempo.

Antes disso, confira tarefas pendentes.

```bash
curl -s http://localhost:9200/_cluster/pending_tasks?pretty
```
