# MinIO para o processamento documental

Execute os comandos abaixo na máquina que hospeda o OpenWebUI, a partir da raiz
do repositório. Nesta máquina o MinIO já está instalado e em uso; este guia serve
para reinstalação ou outra máquina. Este guia prepara apenas o MinIO; Elasticsearch,
Docling e embeddings serão verificados separadamente. O pipeline completo ainda
não deve ser iniciado para validar este passo.

A implantação usa AIStor em um único contêiner, com licença fornecida pelo operador,
um volume persistente e um usuário separado para a aplicação. O Compose está em
[`compose.minio.yaml`](../compose.minio.yaml). API S3 e console são publicados
somente em `127.0.0.1`, nas portas 9000 e 9001.

## 1. Conferir o Docker Compose

```bash
cd <raiz-do-repositório>
sudo docker compose version
```

O ambiente inspecionado tem Compose v2.40.3. Use `sudo` nos comandos Docker
se seu usuário não tiver acesso ao daemon.

## 2. Colocar a licença no repositório local

```bash
mkdir -p .local/minio
chmod 700 .local .local/minio
```

Copie o arquivo recebido para `.local/minio/minio.license`. Por exemplo, se
você o salvou em `~/minio.license`:

```bash
cp ~/minio.license .local/minio/minio.license
chmod 600 .local/minio/minio.license
test -s .local/minio/minio.license
```

Ajuste somente o caminho de origem ao nome real do arquivo. O Compose monta a
licença como arquivo somente leitura e falha se ela não existir. Licença e
`.local/` são ignorados pelo Git. Não cole o conteúdo em YAML ou no código.

## 3. Gerar credenciais locais

As credenciais ficam no `.env` único da raiz, junto com `OPENROUTER_API_KEY` e
`RAG_API_TOKEN`. O comando gera senhas distintas, não as imprime e acrescenta as
chaves ao `.env`; interrompe se alguma chave MinIO já estiver definida.

```bash
python - <<'PY'
import os
import secrets

content = (
    'MINIO_IMAGE=quay.io/minio/aistor/minio:latest\n'
    'MINIO_ROOT_USER=rag-admin\n'
    f'MINIO_ROOT_PASSWORD={secrets.token_hex(32)}\n'
    'RAG_MINIO_ACCESS_KEY=websensors-rag\n'
    f'RAG_MINIO_SECRET_KEY={secrets.token_hex(32)}\n'
)
path = '.env'
existing = open(path).read() if os.path.exists(path) else ''
if any(line.startswith(('MINIO_ROOT_', 'RAG_MINIO_')) for line in existing.splitlines()):
    raise SystemExit('Chaves MinIO já existem em .env; nada foi alterado.')
fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
with os.fdopen(fd, 'a') as stream:
    stream.write(('\n' if existing and not existing.endswith('\n') else '') + content)
os.chmod(path, 0o600)
print('Credenciais acrescentadas ao .env, com permissão 600.')
PY
```

O modelo para edição manual é [`.env.example`](../.env.example).
Use valores em sintaxe de shell; o gerador usa hexadecimal, compatível tanto com
Compose quanto com o script de inicialização. `.env` não entra no Git.

## 4. Iniciar o servidor

```bash
sudo docker compose -f compose.minio.yaml config --quiet
sudo docker compose -f compose.minio.yaml pull
sudo docker compose -f compose.minio.yaml up -d
sudo docker compose -f compose.minio.yaml ps
curl --fail --silent --show-error http://127.0.0.1:9000/minio/health/live
```

O health check bem-sucedido pode não imprimir corpo. Caso falhe, confira:

```bash
sudo docker compose -f compose.minio.yaml logs --tail=80 minio
```

A imagem inicial segue `latest`, como no guia oficial. Para reproduzir a versão
validada, depois do primeiro pull obtenha seu digest:

```bash
sudo docker image inspect quay.io/minio/aistor/minio:latest --format '{{index .RepoDigests 0}}'
```

Substitua o valor de `MINIO_IMAGE` em `.env` pela referência completa
`quay.io/minio/aistor/minio@sha256:...` retornada. Assim, próximos `up`/`pull`
usam a mesma imagem. Não execute atualizações de versão sem decisão explícita.

## 5. Instalar o cliente e preparar buckets/usuário

Baixe o AIStor Client oficial, localmente, sem instalar no sistema:

```bash
case "$(uname -m)" in
  x86_64) minio_arch=amd64 ;;
  aarch64|arm64) minio_arch=arm64 ;;
  *) echo 'Arquitetura não contemplada neste guia'; exit 1 ;;
esac
curl --fail --location --show-error \
  "https://dl.min.io/aistor/mc/release/linux-${minio_arch}/mc" \
  --output .local/minio/mc
chmod 700 .local/minio/mc
.local/minio/mc --version
bash scripts/minio-init.sh
```

O script usa o administrador para criar `rag-bronze`, `rag-silver`, uma policy
restrita a esses buckets e o usuário `websensors-rag`. O usuário da aplicação
pode listar os dois buckets e ler, gravar ou excluir seus objetos; não pode
administrar o servidor nem criar outros buckets. Essa policy permite o upload
Bronze antes do pipeline e a gravação/leitura dos artefatos Silver.

Os buckets nascem privados. O script não habilita acesso anônimo. Ao final,
confere upload, download e remoção de um objeto de diagnóstico em cada bucket,
usando as credenciais da aplicação. A verificação de objetos também comprova
que a licença permite operações S3, além de o processo estar respondendo.

Pode repetir a inicialização: buckets existentes são preservados, a policy é
atualizada e a senha de um usuário existente não é alterada. Se você mudar
`RAG_MINIO_SECRET_KEY` após criar o usuário, o teste falhará até realizar uma
rotação explícita da credencial. Não execute com `bash -x`, pois expõe segredos.

## 6. Configurar o WebSensors-RAG

Se ainda não tiver configuração local, copie o exemplo uma única vez:

```bash
test -f config/rag.local.yaml || cp config/rag.yaml config/rag.local.yaml
chmod 600 config/rag.local.yaml
```

Edite apenas `services.minio` em `config/rag.local.yaml`:

```yaml
services:
  minio:
    endpoint: "http://127.0.0.1:9000"
    access_key: "websensors-rag"
    secret_key: "${RAG_MINIO_SECRET_KEY}"
    secure: false
    region: null
    bronze_bucket: rag-bronze
    silver_bucket: rag-silver
    silver_prefix: documentos
    timeout_seconds: 10
```

O RAG resolve valores `${VAR}` pelo `.env` da raiz. Prefira referenciar
`secret_key: "${RAG_MINIO_SECRET_KEY}"` em vez de copiar o valor para o YAML.
Não use as credenciais do administrador no RAG. O trecho acima substitui o bloco
MinIO dentro de `services`; preserve os demais serviços do arquivo.

O endpoint `127.0.0.1:9000` vale para o Python/API RAG rodando no host. Se o RAG
passar a rodar em outro contêiner, conecte-o à rede deste Compose e use
`http://minio:9000`. O OpenWebUI encaminhará o original à API RAG; não precisa
ter acesso direto aos buckets nesta arquitetura.

O diagnóstico geral `websensors-flow-rag-health` verifica também outros serviços.
Uma falha nele ainda não significa que o MinIO falhou: use primeiro o teste de
objetos do passo 5 para validar esta etapa isoladamente.

## 7. Abrir o console

Na própria máquina: <http://127.0.0.1:9001>. Entre com `MINIO_ROOT_USER` e
`MINIO_ROOT_PASSWORD` de `.env`.

Para acessar de outro computador, execute **nesse outro computador**:

```bash
ssh -N -L 19001:127.0.0.1:9001 <seu-usuario>@143.107.183.199
```

Depois abra <http://127.0.0.1:19001> no navegador desse computador. Use a sua conta SSH
nessa máquina.

## Organização para o planejamento

```text
rag-bronze/
  projetos/fai/documentos/<document_id>/<source_sha256>/<arquivo-original>

rag-silver/
  documentos/<document_id>/<revision_id>/
    document.md
    document.json
    manifest.json
    classification.json   # previsto na extensão documental
    extraction.json       # previsto na extensão documental
```

Os prefixos S3 são lógicos e não precisam ser criados. O pipeline atual já grava
Markdown, JSON Docling e manifesto no Silver. Os JSONs de classificação e extração
e o serviço de upload Bronze serão adicionados nas fases seguintes. A organização
Bronze acima é a proposta para esse serviço, não um comportamento já implementado.
Não há expiração automática: os documentos de aceitação devem ser preservados.

Não habilitamos versionamento S3 neste passo: o pipeline tem revisões próprias e
a proposta Bronze usa chaves com hash da fonte. Não substituir um original por
outro conteúdo sob uma mesma chave durante o processamento.

## Persistência e reinício

Os dados ficam no volume nomeado `websensors-rag-minio_minio-data`, fora do
checkout. Reiniciar ou recriar o contêiner mantém os dados:

```bash
sudo docker compose -f compose.minio.yaml restart minio
```

Para parar sem remover os dados:

```bash
sudo docker compose -f compose.minio.yaml stop minio
```

Não use `down -v`: remove o volume e os dados. Volume persistente não substitui
backup. Guarde também a licença e as credenciais antes de mover a implantação.

## Referências

- [Instalação oficial em contêiner e cliente AIStor](https://docs.min.io/aistor/installation/container/install/).
- [Licenças AIStor](https://docs.min.io/aistor/operations/licenses/).
- [Criação de usuário](https://docs.min.io/aistor/reference/cli/admin/mc-admin-user/mc-admin-user-add/).
