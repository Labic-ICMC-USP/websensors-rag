# Processamento por CLI

Com `FAI_final` ativo, na raiz do repositório:

```bash
python -m websensors_flow_rag process \
  --config config/rag.local.yaml \
  --file /exp/golomarcos/edital.pdf \
  --project fai \
  --output json \
  --output-file .local/resultado-edital.json
```

Esse comando executa processamento real. Planeje a conversão quando houver
capacidade no Docling compartilhado. O CLI não inicia nem interrompe esse serviço.
Ele usa `ProcessDocumentService`, o mesmo núcleo da API: original no Bronze,
Flow, artefatos Silver, chunks, embeddings configurados e publicação textual.
O YAML local habilita MLflow; métricas e eventos usam os observers existentes.

O stdout contém apenas o resultado JSON; logs/progresso seguem para stderr.
`--metadata` aceita um objeto JSON. `--document-id` fornece uma identidade lógica
estável no projeto; o ID interno é derivado dessa identidade e do projeto.
Sem essa opção, a identidade usa o nome do arquivo. Fonte alterada recebe outra
chave Bronze com SHA-256, preservando o original anterior.

Com classificação habilitada, `--document-type` usa o tipo declarado (validado
contra as categorias do projeto), sem apresentá-lo como predição LLM. Omita esse
parâmetro para classificar automaticamente e nos testes de acurácia.
A configuração local usa Gemini 2.5 Flash para a classificação, retornada em
`classification`. Com extração habilitada, `extraction` contém dados validados,
evidências, status e avisos (veja `resources/12_extracao.md`). Sucesso de execução
não equivale ao aceite funcional do conjunto completo.

## Reutilizar conversão existente

O serviço procura cache Silver compatível com projeto, identidade, hash do
original e hash das opções Docling. Se encontrado, não repete a conversão.
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
