# Observabilidade, progresso e ETA

O serviço apresenta informações de inicialização e indexação no terminal. MLflow e Graylog podem ser habilitados no YAML.

## Diagnóstico de inicialização

```bash
websensors-flow-rag-health --config config/rag.local.yaml
```

A saída contém uma tabela com os serviços obrigatórios.

```text
Diagnóstico de infraestrutura

Serviço         Estado     Tempo     Tent.    Resultado
Elasticsearch   OK         0.04s     1        cluster=rag status=green nodes=1
MinIO           OK         0.03s     1        buckets=rag-bronze, rag-silver
Docling         OK         0.02s     1        health=ok ready=ok
Embeddings      OK         0.41s     1        modelo=inpi-text-embedding dimensoes=1024 inferencia=ok
```

Quando uma dependência falha, o relatório mostra uma ação específica e a API não é iniciada.

## Steps no terminal

Cada indexação possui nove steps.

O início de um step mostra sua posição e o ETA do fluxo.

O final mostra duração, métricas e novo ETA.

Loops internos mostram quantidade processada, taxa, tempo decorrido e ETA.

Exemplo.

```text
step 6/9  gerar_embeddings  EXECUTANDO
Step iniciado
progresso  5/9
ETA do fluxo  24.6s

Gerando embeddings  4/8 lotes  50.0%  taxa 1.72 lotes/s  decorrido 2.326s  ETA 2.326s

step 6/9  gerar_embeddings  OK
Embeddings gerados para todos os chunks.
duração  4.817s
progresso  6/9
ETA do fluxo  13.2s
```

O primeiro ETA de uma operação pode aparecer como `calculando` enquanto ainda não existe histórico suficiente para uma estimativa.

## ETA

O ETA de loops internos usa a taxa observada na própria operação.

O ETA do fluxo usa a duração média dos steps já concluídos.

O Docling exibe o ETA informado pelo serviço quando disponível. Quando o Docling não informa progresso suficiente, a saída mantém o tempo decorrido e indica que o ETA está sendo calculado.

## MLflow

Configuração básica.

```yaml
observability:
  mlflow:
    enabled: true
    tracking_uri: "http://localhost:5000"
    experiment_name: "websensors-flow-rag"
    run_name: "indexacao-rag"
    track_searches: true
```

Cada fluxo registra informações de execução, métricas dos steps, modelos utilizados e artefatos declarados pelo pipeline.

Quando `track_searches` está habilitado, as consultas também podem registrar modalidade, quantidade de resultados e duração.

## Graylog

```yaml
observability:
  graylog:
    enabled: true
    host: "localhost"
    port: 12201
    protocol: tcp
    facility: websensors-flow-rag
    level: INFO
```

## Relatórios locais

```yaml
runtime:
  report_dir: ./outputs/reports
```

O relatório local mantém os dados estruturados da execução e permite investigar falhas sem depender somente da saída do terminal.
