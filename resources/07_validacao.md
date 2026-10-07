# Validação da infraestrutura

Execute esta sequência antes de iniciar a API.

## Elasticsearch

```bash
curl -f http://localhost:9200/
curl -f http://localhost:9200/_cluster/health?pretty
```

O estado do cluster precisa ser `green` ou `yellow`.

## MinIO

Confira o acesso aos buckets Bronze e Silver com `mc` ou com o cliente S3 utilizado no ambiente.

Os nomes padrão são `rag-bronze` e `rag-silver`.

## Docling

```bash
curl -f http://localhost:5001/health
curl -f http://localhost:5001/ready
```

## Embeddings

```bash
curl -f http://localhost:4000/v1/models
```

Execute também uma inferência real e confirme a dimensão do vetor.

## Diagnóstico integrado

```bash
websensors-flow-rag-health --config config/rag.local.yaml
```

O relatório precisa mostrar os quatro serviços obrigatórios como disponíveis.

```text
Elasticsearch  OK
MinIO          OK
Docling        OK
Embeddings     OK
```

MLflow e Graylog aparecem quando habilitados.

## Iniciar a API

```bash
websensors-flow-rag-api --config config/rag.local.yaml
```

## Conferir OpenAPI

```bash
curl -f http://localhost:8000/openapi.json
```

## Conferir a descrição do serviço

```bash
curl -f http://localhost:8000/rag
```
