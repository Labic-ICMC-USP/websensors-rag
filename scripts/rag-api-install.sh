#!/usr/bin/env bash
# Instala e inicia a API WebSensors-RAG deste checkout como serviço systemd do usuário.
# Usa .venv/ e config/rag.local.yaml do próprio repositório. Não para outros processos:
# se o endereço configurado estiver ocupado, interrompe sem alterar nada.
set -euo pipefail
repo_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
config="${RAG_CONFIG:-$repo_dir/config/rag.local.yaml}"
api_bin="$repo_dir/.venv/bin/websensors-flow-rag-api"
unit_name=websensors-rag-api.service
unit_dir="$HOME/.config/systemd/user"

[[ -x "$api_bin" ]] || { echo "Ambiente ausente: crie .venv e rode 'pip install -e .[test,observability]'." >&2; exit 1; }
[[ -f "$config" ]] || { echo "Configuração ausente: $config" >&2; exit 1; }

read -r host port < <("$repo_dir/.venv/bin/python" -I - "$config" <<'PY'
import sys, yaml
api = (yaml.safe_load(open(sys.argv[1])) or {}).get("api", {})
print(api.get("host", "0.0.0.0"), api.get("port", 8000))
PY
)

if systemctl --user is-active --quiet "$unit_name"; then
  echo "Serviço já ativo; para aplicar código novo use: systemctl --user restart $unit_name"
  exit 0
fi
if (exec 3<>"/dev/tcp/$host/$port") 2>/dev/null; then
  echo "Endereço $host:$port ocupado por outro processo; nada foi alterado." >&2
  echo "Libere a porta (ex.: o dono do serviço antigo executa 'systemctl --user disable --now $unit_name')." >&2
  exit 1
fi

mkdir -p "$unit_dir"
cat > "$unit_dir/$unit_name" <<EOF
[Unit]
Description=WebSensors-RAG API ($repo_dir)
After=network.target

[Service]
Type=simple
WorkingDirectory=$repo_dir
ExecStart=$api_bin --config $config
Restart=on-failure
RestartSec=10
Nice=10
CPUQuota=100%
MemoryHigh=1536M
MemoryMax=2G
TasksMax=128
UMask=0077
Environment=CUDA_VISIBLE_DEVICES=
Environment=OMP_NUM_THREADS=1
Environment=OPENBLAS_NUM_THREADS=1
Environment=MKL_NUM_THREADS=1
Environment=MLFLOW_DISABLE_AGENT_HINT=1

[Install]
WantedBy=default.target
EOF
chmod 600 "$unit_dir/$unit_name"
systemctl --user daemon-reload
systemctl --user enable --now "$unit_name"
echo "API iniciada em http://$host:$port. Status: systemctl --user status $unit_name"
if [[ "$(loginctl show-user "$USER" --property=Linger --value 2>/dev/null)" != "yes" ]]; then
  echo "Aviso: linger desativado; o serviço para quando você sair da sessão. Ative com: loginctl enable-linger $USER"
fi
