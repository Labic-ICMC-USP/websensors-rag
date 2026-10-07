# Requisitos

## Software

| Recurso | Uso |
| --- | --- |
| Linux | ambiente recomendado para os serviços |
| Docker | execução dos serviços de infraestrutura |
| Python 3.10 ou superior | execução do pacote |
| curl | testes HTTP |
| jq | inspeção de respostas JSON |

## Portas de referência

| Serviço | Porta |
| --- | --- |
| WebSensors Flow RAG | 8000 |
| Elasticsearch | 9200 |
| MinIO API | 9000 |
| MinIO Console | 9001 |
| Docling Serve | 5001 |
| LiteLLM | 4000 |
| MLflow | 5000 |

As portas podem ser alteradas. Os valores usados pelo RAG ficam no YAML global.

## Rede

Quando todos os serviços estão em Docker, use uma rede comum.

```bash
docker network create websensors-rag
```

Quando a API roda diretamente no host, os endpoints do YAML podem usar `localhost` nas portas publicadas pelos containers.

## Armazenamento

Reserve espaço persistente para Elasticsearch e MinIO.

O Elasticsearch mantém índices e vetores.

O MinIO mantém originais, Markdown, JSON e manifestos.
