#!/usr/bin/env bash
# Instala somente a instância MLflow do WebSensors-RAG no usuário atual.
set -euo pipefail
repo_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
state_dir="$HOME/.local/share/websensors-rag/mlflow"
unit_dir="$HOME/.config/systemd/user"
unit_name=websensors-rag-mlflow.service
python_bin="${MLFLOW_PYTHON:-python3}"
if systemctl --user is-active --quiet "$unit_name"; then
  echo 'A instância MLflow do RAG já está ativa; nenhuma alteração realizada.'
  exit 0
fi
"$python_bin" - <<'PY'
import socket
with socket.socket() as sock:
    try:
        sock.bind(('127.0.0.1',5000))
    except OSError:
        raise SystemExit('Porta 5000 ocupada; nenhum serviço será interrompido.')
PY
mkdir -p "$state_dir/artifacts" "$unit_dir"
chmod 700 "$state_dir" "$state_dir/artifacts"
if [[ ! -x "$state_dir/venv/bin/python" ]]; then
  "$python_bin" -m venv "$state_dir/venv"
fi
nice -n 10 "$state_dir/venv/bin/python" -m pip install --quiet 'mlflow==3.17.2'
install -m 600 "$repo_dir/deploy/mlflow/$unit_name" "$unit_dir/$unit_name"
systemctl --user daemon-reload
systemctl --user enable --now "$unit_name"
echo 'Instância MLflow iniciada; use systemctl --user status websensors-rag-mlflow.'
