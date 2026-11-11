#!/usr/bin/env bash
# Executar no host depois de iniciar compose.minio.yaml.
set -euo pipefail
repo_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_dir"
if [[ ! -f .env.minio ]]; then
  echo 'Crie .env.minio conforme resources/03_minio.md.' >&2
  exit 1
fi
# Arquivo local gerado pelo operador; valores devem usar sintaxe de shell.
source .env.minio
: "${MINIO_ROOT_USER:?}" "${MINIO_ROOT_PASSWORD:?}"
: "${RAG_MINIO_ACCESS_KEY:?}" "${RAG_MINIO_SECRET_KEY:?}"
for value in "$MINIO_ROOT_PASSWORD" "$RAG_MINIO_SECRET_KEY"; do
  if [[ "$value" == SUBSTITUA* || ${#value} -lt 8 ]]; then
    echo 'Configure os dois segredos com pelo menos 8 caracteres (recomendado: 16 ou mais).' >&2
    exit 1
  fi
done
if [[ "$RAG_MINIO_ACCESS_KEY" == "$MINIO_ROOT_USER" ]]; then
  echo 'Use usuários distintos para administrador e aplicação.' >&2
  exit 1
fi
mc_bin="$repo_dir/.local/minio/mc"
if [[ ! -x "$mc_bin" ]]; then
  echo 'Instale o cliente mc conforme resources/03_minio.md.' >&2
  exit 1
fi
# Aliases contêm credenciais; manter apenas em diretório temporário privado.
export MC_CONFIG_DIR
MC_CONFIG_DIR="$(mktemp -d)"
trap 'rm -rf -- "$MC_CONFIG_DIR"' EXIT
"$mc_bin" alias set bootstrap http://127.0.0.1:9000 "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD" >/dev/null
"$mc_bin" ready bootstrap
"$mc_bin" mb --ignore-existing bootstrap/rag-bronze
"$mc_bin" mb --ignore-existing bootstrap/rag-silver
"$mc_bin" admin policy create bootstrap websensors-rag "$repo_dir/deploy/minio/rag-policy.json"
if "$mc_bin" admin user info bootstrap "$RAG_MINIO_ACCESS_KEY" >/dev/null 2>&1; then
  echo 'Usuário RAG já existe; preservando sua senha.'
else
  "$mc_bin" admin user add bootstrap "$RAG_MINIO_ACCESS_KEY" "$RAG_MINIO_SECRET_KEY"
fi
"$mc_bin" admin policy attach bootstrap websensors-rag --user "$RAG_MINIO_ACCESS_KEY"
"$mc_bin" alias set rag http://127.0.0.1:9000 "$RAG_MINIO_ACCESS_KEY" "$RAG_MINIO_SECRET_KEY" >/dev/null
# Conferir escrita/leitura com as credenciais da aplicação, em ambos os buckets.
probe_key="validacao/minio-init-$(date +%s)-$$.txt"
for bucket in rag-bronze rag-silver; do
  printf '%s' 'websensors-rag-minio-ok' | "$mc_bin" pipe "rag/$bucket/$probe_key" >/dev/null
  probe_result="$("$mc_bin" cat "rag/$bucket/$probe_key")"
  if [[ "$probe_result" != 'websensors-rag-minio-ok' ]]; then
    echo "Falha de leitura no bucket $bucket; objeto de diagnóstico: $probe_key" >&2
    exit 1
  fi
  "$mc_bin" rm "rag/$bucket/$probe_key" >/dev/null
  echo "$bucket: escrita e leitura conferidas; objeto de teste removido."
done
echo 'MinIO preparado. Configure config/rag.local.yaml conforme resources/03_minio.md.'
