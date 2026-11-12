# Processamento por CLI

Na raiz do repositório, com o ambiente `.venv` ativo (`source .venv/bin/activate`):

```bash
python -m websensors_flow_rag process \
  --config config/rag.local.yaml \
  --file validation/data/edital.pdf \
  --project fai \
  --output json \
  --output-file .local/resultado-edital.json
```

Esse comando executa processamento real. Planeje a conversão quando houver
capacidade no Docling compartilhado. O CLI não inicia nem interrompe esse serviço.
Ele usa `ProcessDocumentService`, o mesmo núcleo da API: original no Bronze,
Flow, artefatos Silver, chunks, embeddings configurados, publicação textual e,
com `structured_index` habilitado, o registro no índice do tipo.
O YAML local habilita MLflow; métricas e eventos usam os observers existentes.

O stdout contém apenas o resultado JSON; logs/progresso seguem para stderr.
`--metadata` aceita um objeto JSON.

**Identidade do documento.** Por padrão, o documento é identificado pelo
**conteúdo** do PDF (SHA-256), não pelo nome: o mesmo PDF enviado de novo, com
qualquer nome e por qualquer interface, é o mesmo documento e retorna `noop` se
nada mudou. Um PDF diferente, mesmo com nome igual, é outro documento.
Para tratar conteúdos diferentes como versões do mesmo documento (por exemplo,
um edital retificado), informe `--document-id` com uma identidade estável no
projeto; o ID interno é derivado dela e do projeto. Cada original fica numa chave
Bronze com seu SHA-256, preservando os anteriores.

Com classificação habilitada, `--document-type` usa o tipo declarado (validado
contra as categorias do projeto), sem apresentá-lo como predição LLM. Omita esse
parâmetro para classificar automaticamente e nos testes de acurácia.
A configuração local usa Gemini 2.5 Flash para a classificação, retornada em
`classification`. Com extração habilitada, `extraction` contém dados validados,
evidências, status e avisos (veja `resources/12_extracao.md`). Sucesso de execução
não equivale ao aceite funcional do conjunto completo.

## Reutilizar conversão existente

O serviço procura cache Silver compatível com projeto, documento, hash do
original e hash das opções Docling. Se encontrado, não repete a conversão.
Quando a CLI converte, ela própria grava esse cache, então execuções futuras do
mesmo original (inclusive após mudar prompts ou modelo) não reconvertem.
Também aceita `--docling-artifacts CAMINHO.json` com:

```json
{
  "source_sha256": "SHA256_DO_ORIGINAL",
  "options_sha256": "SHA256_DAS_OPCOES_DOCLING",
  "markdown": "# Conteúdo convertido",
  "structural_json": {"schema_name": "DoclingDocument", "pages": {}}
}
```

O JSON acima ilustra o contrato; forneça os artefatos reais, completos e com
proveniência conhecida. Não crie JSON estrutural fictício a partir do texto.
O hash de opções pode ser consultado por Python com
`docling_options_hash(load_rag_settings('config/rag.local.yaml'))`. O hash não
inclui chaves de acesso. Divergência de hashes interrompe a operação.

## Limites

Uploads são limitados a 50 MiB por padrão (`api.max_upload_bytes`). A concorrência
da API é configurada separadamente; executar CLI simultaneamente com ela cria
outro processo e não compartilha seus locks. Nesta máquina, evite conversões
concorrentes enquanto a GPU estiver ocupada.
