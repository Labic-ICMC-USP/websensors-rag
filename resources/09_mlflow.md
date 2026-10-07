# Instalação do MLflow

O MLflow registra execuções de indexação, informações dos modelos, métricas de cada etapa, duração e progresso. Também pode registrar métricas agregadas das buscas.

## 1. Criar uma instalação local

Utilize um ambiente Python exclusivo para o serviço de rastreamento.

```bash
mkdir -p ~/servicos/mlflow
cd ~/servicos/mlflow
python3 -m venv .venv
source .venv/bin/activate
pip install 'mlflow>=3,<4'
```

## 2. Iniciar o tracking server

```bash
mkdir -p artifacts
mlflow server \
  --host 127.0.0.1 \
  --port 5000 \
  --backend-store-uri sqlite:///mlflow.db \
  --default-artifact-root ./artifacts
```

A base SQLite e o diretório de artefatos permanecem nessa pasta. Para múltiplas instâncias e maior volume de execuções, utilize um banco persistente adequado e armazenamento compartilhado de artefatos.

O comando apresentado aceita conexões locais. Para disponibilizar o serviço a outra máquina, configure a interface de rede, autenticação, controle de acesso e TLS no ambiente de implantação.

## 3. Verificar o serviço

Acesse a interface em `http://127.0.0.1:5000`.

A verificação de escrita pode ser feita diretamente pelo pacote RAG, sem depender de um endpoint HTTP específico de saúde do MLflow.

## 4. Configurar o pacote RAG

Instale a integração no mesmo ambiente Python usado para a API RAG.

```bash
pip install -e '.[observability]'
```

Atualize o YAML global.

```yaml
startup:
  enabled: true
  check_mlflow_write: true

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
```

Quando o serviço RAG roda em um contêiner Docker separado, `127.0.0.1` identifica o próprio contêiner. Utilize um endereço que possa ser acessado a partir da rede do contêiner, como o nome do serviço em uma rede Docker compartilhada.

## 5. Validar gravações

```bash
websensors-flow-rag-health --config config/rag.local.yaml
```

A verificação de inicialização abre uma execução de teste no MLflow quando `check_mlflow_write` está habilitado. A saída informa se a gravação foi aceita.

O registro de uma indexação inclui parâmetros, eventos, métricas e, quando disponível, ETA das etapas com progresso mensurável.

A API também permite configurar `track_searches` para registrar duração e quantidade de resultados das consultas sem persistir o texto das perguntas.
