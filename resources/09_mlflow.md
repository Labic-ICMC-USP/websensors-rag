# MLflow do WebSensors-RAG

A instância deste projeto usa MLflow 3.17.2, um ambiente Python separado e
um serviço systemd do usuário. Não depende de Docker ou de um novo banco de
rede. Metadata ficam em SQLite e os artefatos são servidos pelo tracking server.

## Instalar e iniciar

Na raiz do repositório, com o ambiente `.venv` ativo:

```bash
bash scripts/mlflow-install.sh
```

O script cria:

- Ambiente, SQLite e artefatos: `~/.local/share/websensors-rag/mlflow/`.
- Unidade: `~/.config/systemd/user/websensors-rag-mlflow.service`.
- Tracking server e UI: `http://127.0.0.1:5000`.

O banco fica no disco local de `home`, em vez do checkout em `/exp`, que é um
volume de rede nesta máquina. O serviço tem um worker HTTP, jobs de avaliação
online desabilitados, prioridade reduzida, limite de uma CPU e 2 GiB de memória.
`MemoryHigh` é 1,5 GiB. O serviço não carrega modelos de inferência.

Se a porta 5000 estiver ocupada, o instalador interrompe sem parar o processo
que a utiliza. Se a instância deste projeto já estiver ativa, não a reinicia.
Só opera sobre a unidade `websensors-rag-mlflow.service`.

Para mantê-la ativa após logout e iniciá-la no boot, habilite linger uma vez:

```bash
loginctl enable-linger "$USER"
```

Na máquina inspecionada, linger já foi habilitado e a unidade está ativa.

## Cliente no ambiente RAG

Instale a integração no ambiente utilizado pelo RAG:

```bash
python -m pip install -e '.[observability]' 'mlflow==3.17.2'
```

O cliente MLflow 3.17.2 e `psutil` já estão no `.venv` deste checkout. Nesta máquina,
o servidor MLflow (`websensors-rag-mlflow.service`) roda como serviço do usuário
`golomarcos`; os comandos `systemctl --user` abaixo valem para quem o instalou.
Graylog continua desabilitado; não é necessário subir esse serviço.

## Configuração local

O `config/rag.local.yaml` já contém:

```yaml
observability:
  mlflow:
    enabled: true
    tracking_uri: "http://127.0.0.1:5000"
    experiment_name: "websensors-flow-rag"
    run_name: "indexacao-rag"
    track_searches: true
    auth:
      enabled: false
      username: null
      password: null
      token: null

startup:
  enabled: true
  check_mlflow_write: true
```

Integre esses campos aos blocos existentes do YAML, sem duplicar seções nem
remover as outras opções. O endpoint é local e não é publicado na rede externa.

O pipeline continua usando o `MLflowObserver` do WebSensors-Flow. Os steps
retornam `StepResult` e usam o contexto para métricas, progresso, modelos e spans;
não implementam chamadas diretas ao servidor MLflow.

## Validação sem indexação ou inferência local

```bash
python scripts/mlflow-check.py --config config/rag.local.yaml
```

Esse comando executa um step sintético pelo Flow existente, registra métrica,
progresso e spans, consulta a execução finalizada e baixa o artefato de eventos.
Não chama Docling, Ollama, embeddings ou Elasticsearch. O relatório fica em
`.local/mlflow-validation/report.json`, ignorado pelo Git.

Para o diagnóstico de todas as dependências, com o provedor de embeddings
configurado, use:

```bash
websensors-flow-rag-health --config config/rag.local.yaml
```

O preflight também grava uma execução de teste no MLflow. Esse diagnóstico usa
o endpoint de embeddings que estiver no YAML; nesta instalação ele foi migrado
para o OpenRouter, conforme `resources/10_openrouter.md`.

## Acesso e operação

Na própria máquina: <http://127.0.0.1:5000>.

Para abrir a UI de outro computador, execute nesse computador:

```bash
ssh -N -L 15000:127.0.0.1:5000 <seu-usuario>@143.107.183.199
```

Abra <http://127.0.0.1:15000>. Os links de execução retornados pelo diagnóstico
usam o tracking URI local; pelo túnel, substitua a porta por `15000`.

```bash
systemctl --user status websensors-rag-mlflow --no-pager
journalctl --user -u websensors-rag-mlflow -n 60 --no-pager
systemctl --user show websensors-rag-mlflow \
  --property=CPUQuotaPerSecUSec,MemoryHigh,MemoryMax,MemoryCurrent,TasksCurrent
```

Reiniciar somente esta instância, quando necessário:

```bash
systemctl --user restart websensors-rag-mlflow
```

Não apague `mlflow.db` ou `artifacts/`. Ambos precisam entrar no backup. O limite
de memória se aplica a esta instância; não altera os limites ou os processos dos
outros serviços. Os limites reduzem a disputa por recursos, mas não equivalem a
uma reserva exclusiva de CPU ou disco.

## Evidência da validação em 11/11/2026

- `/health`: HTTP 200.
- Observer existente: execução `FINISHED`, métrica conferida e artefato de
  eventos baixado com progresso e spans presentes.
- Diagnóstico de embeddings OpenRouter também foi executado pelo Flow, com
  modelo, duração e métricas no MLflow e nenhuma chamada de inferência local.

Fontes: [tracking server](https://mlflow.org/docs/latest/self-hosting/architecture/tracking-server/)
e [release 3.17.2](https://github.com/mlflow/mlflow/releases/tag/v3.17.2).
