# OpenWebUI: original, conversão única e Tool

## Estado verificado

Na versão 0.11.0 desta máquina, o anexo de teste retornou:

- `data.status: completed` e `data.content` com 487 caracteres;
- `GET /api/v1/files/{id}/content`: HTTP 200, 28.495 bytes e assinatura `%PDF-`;
- nenhum JSON estrutural nas chaves `data` ou `meta.data` observadas.

O original é recuperável com a permissão do usuário. O texto dessa resposta não
substitui o par Markdown/JSON Docling. O token do usuário não deve ser enviado
à API RAG nem guardado em Valves.

## Fluxo implementado

```text
Upload OpenWebUI
  → extrator externo na mesma API RAG
  → original Bronze
  → Flow de conversão (steps existentes Docling e Silver)
  → Markdown + JSON + cache de proveniência no Silver
  → texto devolvido ao OpenWebUI

Tool na conversa
  → recuperar original pela API interna do OpenWebUI, com identidade do usuário
  → POST multipart à API RAG, exigindo cache
  → mesmo ProcessDocumentService usado pelo CLI
  → Flow completo, reutilizando artefatos Docling
  → consulta de status e resultado no chat
```

O adaptador externo é uma rota da FastAPI existente; não há outro servidor de
conversão. A conversão no upload é observada pelo MLflow e não indexa chunks.
A Tool inicia o restante do processamento. Sem cache compatível, a Tool recusa
uma segunda conversão silenciosa. Anexos antigos, convertidos antes desse
adaptador, precisam de um novo upload após sua ativação ou de uma importação
explícita dos artefatos completos; o texto isolado não basta.

## API RAG nesta máquina

A API está ativa como `websensors-rag-api.service` do usuário, em
`http://172.18.0.1:8000`, endereço da ponte Docker usada pelo OpenWebUI.
O token é `RAG_API_TOKEN` no `.env` local. Consulte-o apenas no editor da máquina;
não publique seu valor na conversa ou no Git. O YAML usa `${RAG_API_TOKEN}`.

A instância tem limite de uma CPU, 2 GiB de RAM e um worker de indexação. Isso
limita esta API, não o servidor Docling compartilhado. O startup validou os cinco
serviços e preparou os índices/aliases textuais com 2560 dimensões. Nenhuma
conversão real foi disparada na implantação da Fase B.

```bash
systemctl --user status websensors-rag-api --no-pager
journalctl --user -u websensors-rag-api -n 40 --no-pager
```

Para instalar o serviço a partir de qualquer checkout (usa `.venv/` e
`config/rag.local.yaml` do próprio repositório, com `api.host`/`api.port`):

```bash
bash scripts/rag-api-install.sh
loginctl enable-linger "$USER"   # manter ativo após logout
```

O instalador não para outros processos: se `172.18.0.1:8000` estiver em uso, ele
interrompe sem alterar nada. Para trocar a API de um checkout por outro na mesma
porta, o dono do serviço antigo executa antes
`systemctl --user disable --now websensors-rag-api`. O OpenWebUI (extrator e
Valves da Tool) não precisa mudar se o endereço e o `RAG_API_TOKEN` forem os mesmos.
Depois de atualizar o código, aplique com `systemctl --user restart websensors-rag-api`.

`deploy/rag/websensors-rag-api.service` é a unidade original do checkout
`/exp/golomarcos`, mantida como referência.

## Configurar o extrator externo

Esta é uma configuração **global** do OpenWebUI (já aplicada nesta instalação).
Ela muda o caminho de extração dos uploads de todos os usuários. Em outra
instalação, registre a configuração Docling anterior antes de fazer a troca.

Em **Painel de administração → Configurações → Documentos**:

| Campo | Valor |
| --- | --- |
| Content Extraction Engine | External |
| Document Loader URL | `http://172.18.0.1:8000/api/v1/openwebui` |
| API Key | valor de `RAG_API_TOKEN` do `.env` |
| Headers | JSON abaixo |

```json
{
  "X-RAG-Project": "fai",
  "X-Original-Filename": "{{FILE_NAME}}"
}
```

O OpenWebUI acrescenta `/process`, envia o original como bytes e autentica com
Bearer. O endpoint é `PUT /api/v1/openwebui/process`. O header de nome original
registra o nome legível do arquivo (sem o prefixo UUID do armazenamento). A
identidade do documento vem do conteúdo do PDF, a mesma usada pela CLI.

Mantenha **Bypass Embedding and Retrieval** ativado, conforme a decisão atual,
para não gerar embeddings no OpenWebUI. O RAG tem sua própria etapa de embeddings
remotos pelo OpenRouter. O bypass não desativa a extração Docling no upload.

## Instalar a Tool

Em **Workspace → Tools**, crie/importe o código de
`integrations/openwebui/process_document_tool.py`. Restrinja seu uso aos usuários
que podem processar arquivos no projeto e habilite-a no modelo de chat escolhido.

Nas Valves:

| Campo | Valor |
| --- | --- |
| RAG_API_URL | `http://172.18.0.1:8000` |
| RAG_API_KEY | valor de `RAG_API_TOKEN` |
| PROJECT | `fai` |

A Tool valida que o ID pertence aos anexos da conversa e consulta a própria API
do OpenWebUI com a autenticação original da requisição. Só encaminha os bytes e
metadados mínimos ao RAG, usando outra chave. Não lê caminhos locais fornecidos
pelo modelo, nem usa uma credencial administrativa do OpenWebUI.

Se o prazo de espera encerrar, preserve o token e use `consultar_processamento`;
não reenvie o documento apenas porque a Tool parou de aguardar. Jobs são mantidos
em memória e se perdem ao reiniciar a API. Artefatos e documentos persistidos
continuam no MinIO/Elasticsearch.

## Validação real

Após configurar o extrator e a Tool, envie a ficha sintética numa nova conversa,
aguarde o upload terminar e acione `processar_documento`. Verifique no MLflow:

1. O fluxo do extrator converte e armazena os artefatos.
2. O fluxo da Tool tem `docling_reused=1` e `docling_conversions=0`.
3. O resultado textual retorna ao chat com documento/revisão identificados.

Os testes simulados verificam conversão única, hashes, cache, publicação, CLI,
API e autorização da Tool. Com a configuração atual o fluxo tem doze steps e a
Tool retorna `classification`, `extraction` e `structured` (índice do tipo).

Em 12/11/2026, `disp.pdf` processado pelo chat (job
`a46dc6ef8bea40998cba0a34aa77adbc`) teve 0 conversões Docling, a mesma
classificação da CLI e os 7 campos extraídos idênticos; veja
[validação](validacao_fase_g.md).

Contrato de referência: [extrator externo oficial](https://docs.openwebui.com/features/chat-conversations/rag/document-extraction/external/)
e [loader da versão 0.11.0](https://github.com/open-webui/open-webui/blob/v0.11.0/backend/open_webui/retrieval/loaders/external_document.py).

## Nova execução pelo fluxo normal do chat

A Tool versão 0.2.1 mantém a assinatura original, sem parâmetro extra. A cada
chamada `processar_documento`, envia `force=true` automaticamente: o usuário
anexa o arquivo e pede seu processamento normalmente, mesmo que os bytes sejam
iguais aos de um envio anterior. Isso gera novas chamadas de classificação,
extração e embeddings e, em caso de sucesso, publica nova revisão com
`action=indexed` (primeiro processamento) ou `action=updated`. Cada chamada pode gerar custos no provedor.

O upload isolado prepara a conversão; o fluxo completo começa quando o modelo
chama a Tool. O cache Docling continua obrigatório, evitando repetir OCR/layout
no servidor compartilhado. Essa configuração se aplica à Tool; outros clientes
da API continuam podendo usar a política de reutilização padrão.

Atualize o código armazenado em Workspace → Tools com
`integrations/openwebui/process_document_tool.py`, salve e confira as Valves.
A cópia armazenada no OpenWebUI não é atualizada apenas por editar o repositório.
A opção `forcar_reprocessamento` da versão 0.2.0 foi removida.
