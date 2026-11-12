# Testes

Os testes são de dois níveis:

| Nível | O que usa | Custo | Quando rodar |
| --- | --- | --- | --- |
| **Automatizados** (`pytest`) | Simulações: sem MinIO, Elasticsearch, Docling, LLM ou MLflow reais | Nenhum, ~5 s | A cada mudança de código |
| **Integração** | Serviços reais desta máquina | Chama Docling, Gemini e embeddings | Antes de entregar ou após mudar config/prompts |

Todos os comandos rodam na raiz do repositório, com `source .venv/bin/activate`.

## 1. Testes automatizados

```bash
python -m pytest
```

Resultado esperado hoje: todos passam, exceto **5 falhas conhecidas** de rerank
(`test_elasticsearch_rerank_endpoint.py` e `test_search_elasticsearch_rerank.py`),
que já existiam e não fazem parte do processamento documental.

Para rodar só o processamento documental:

```bash
python -m pytest tests/test_processing.py tests/test_classification*.py \
  tests/test_extraction*.py tests/test_structured_index.py \
  tests/test_openwebui_tool.py tests/test_run_summary.py
```

Eles cobrem conversão única e cache, identidade por conteúdo, `noop`,
classificação, extração com evidências, índices por tipo, publicação com
compensação, autorização da Tool e o resumo do MLflow.

## 2. Testes de integração

Usam os serviços reais e geram custo no OpenRouter. Os documentos reais têm dados
pessoais: ficam em `validation/data/` (fora do Git) e só podem ir ao Gemini os
autorizados.

### 2.1 Serviços de pé

```bash
websensors-flow-rag-health --config config/rag.local.yaml   # MinIO, ES, Docling, OpenRouter, MLflow
python scripts/mlflow-check.py --config config/rag.local.yaml  # escrita no MLflow, sem documentos
systemctl --user status websensors-rag-api --no-pager        # API (só para o cenário do chat)
```

### 2.2 Os 8 documentos de validação (comando único)

Este é o teste de integração principal. Ele roda o ciclo completo para cada PDF
de `validation/data/` listado em `validation/reais-golo.reference.json`:

```bash
python scripts/integration.py --config config/rag.local.yaml
```

Para cada documento ele:

1. confere o SHA-256 do arquivo com a referência;
2. processa pelo mesmo serviço da API e da CLI, sem informar o tipo;
3. confere:

| Verificação | O que significa |
| --- | --- |
| `pipeline_success` | As 12 etapas terminaram sem erro. |
| `published` | `action` é `indexed`, `updated`, `noop` ou `metadata_updated`. |
| `classification_correct` | O tipo previsto é igual ao da referência. |
| `extraction_valid` | Extração com status `success` ou `needs_review`. |
| `reference_fields_present` | Os campos que a referência manda conferir foram preenchidos (no edital, `avisos_inconsistencias` é conferido em `warnings`). |
| `bronze_original` | O original está no Bronze, com o hash correto. |
| `silver_artifacts` | Os 5 arquivos do Silver existem e batem com o manifesto. |
| `chunks_with_embeddings` | Há trechos ativos e todos têm vetor. |
| `structured_index` | O registro está ativo em `rag-estruturado-fai-<tipo esperado>`. |
| `verify_document_ok` | A conferência completa do `verify-document.py` passou. |
| `resend_is_noop` | Reenviar o mesmo PDF devolve `noop` e a mesma revisão. |

Saída no terminal, uma linha por documento, e um resumo:

```text
OK     disp.pdf  declaracao_disponibilidade  indexed  41.2s
FALHA  hab.pdf  documento_identificacao_foto  indexed  55.0s  falhou: reference_fields_present
...
7/8 documentos aprovados. Relatório: .local/integration/report.json
```

Termina com código 0 só se os 8 passarem. O relatório JSON traz, por documento,
cada verificação, ids, tempos e contagens, sem valores extraídos.

Opções úteis:

- `--only disp.pdf edital.pdf` processa só alguns arquivos;
- `--skip-noop` pula o reenvio.

Na primeira vez, cada PDF passa pelo Docling (alguns minutos para o conjunto) e
pelo Gemini. Nas seguintes, sem mudança de arquivo ou configuração, tudo vira
`noop` e nada é chamado de novo. Para forçar o ciclo inteiro outra vez, mude a
configuração (prompt, schema ou modelo) ou use a CLI com `--force`.

### 2.3 Cenário B: CLI com um documento

```bash
python -m websensors_flow_rag process --config config/rag.local.yaml \
  --file validation/data/edital.pdf --project fai \
  --output json --output-file .local/resultado-edital.json

python scripts/verify-document.py --config config/rag.local.yaml \
  --document-id "$(python -c 'import json;print(json.load(open(".local/resultado-edital.json"))["document_id"])')"
```

Passou se:

- o comando termina com código 0 e o JSON tem `action` `indexed` ou `updated`,
  `classification.document_type` correto e `extraction.status` igual a `success`
  ou `needs_review`;
- `verify-document.py` termina com `"ok": true` (Bronze, Silver, chunks com
  embeddings e registro ativo no índice do tipo);
- a execução aparece no MLflow com `resumo.md` (veja abaixo).

Rodar o mesmo comando de novo deve dar `action: noop`, sem chamar Docling nem
Gemini.

### 2.4 Cenário A: chat do OpenWebUI

1. Numa conversa nova, anexe um PDF autorizado e espere o upload terminar.
2. Peça para processar o documento (a Tool `processar_documento` é chamada).
3. Guarde o `token` e o `document_id` da resposta.

Passou se a resposta tem `status=success` e `action` `indexed` ou `updated`; no
MLflow, a execução com tag `run_id = <token>` tem `docling_reused=1` e
`docling_conversions=0`; e `verify-document.py --document-id <document_id>`
retorna `"ok": true`. Detalhes em [OpenWebUI](tutorial_openwebui.md).

### 2.5 Aceitação da classificação (relatório da Fase G)

```bash
python scripts/acceptance.py --config config/rag.local.yaml \
  --output .local/acceptance/report.json
```

Classifica cada PDF de `validation/data/` sem informar o tipo e compara com
`validation/reais-golo.reference.json` (o hash de cada arquivo é conferido antes).
Passou se `classification_approved: true` (acurácia exigida: 100%). O relatório
traz matriz de confusão e status da extração, sem valores extraídos. Os valores
em si exigem revisão humana no Silver (`extraction.json`).

## 3. Ver o resultado no MLflow

Abra `http://127.0.0.1:5000` (ou o túnel da [demonstração](demonstracao_fai.md)),
experimento `websensors-flow-rag`, e abra a execução. Em **Artifacts**,
`resumo.md` é a visão rápida:

- status, `run_id`, início e duração total;
- resultado: ação (`indexed`, `updated`, `noop`...), `document_id`, `revision_id`,
  tipo, status da extração, campos preenchidos e vazios, avisos e índice do tipo;
- erro, quando houver (etapa, tipo e mensagem);
- tabela das etapas com status, duração e principais métricas.

O resumo não contém texto do documento, valores extraídos, evidências nem o nome
do arquivo. Para o detalhe completo, use `steps/`, `events/events.json` e as métricas.
