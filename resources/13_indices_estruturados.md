# Índices estruturados — Fase E

Publica a extração validada (Fase D) em um índice Elasticsearch por projeto e
tipo documental, ativado junto com a revisão textual (chunks).

```yaml
structured_index:
  enabled: true            # exige classification e extraction habilitadas
  index_prefix: rag-estruturado
```

Com isso o fluxo passa a ter **12 steps**: `preparar_registro_estruturado` entra
logo após `preparar_revisao_elasticsearch`. Indexações sem projeto e documentos
sem dados estruturados (`outro`, ou extração sem `data`) não geram registro.

## Nomes e mappings

| Item | Formato | Exemplo |
| --- | --- | --- |
| Alias de leitura | `<prefixo>-<projeto>-<tipo>` | `rag-estruturado-fai-ficha_inscricao` |
| Índice físico | `<alias>-<sha256(mapping)[:12]>` | `rag-estruturado-fai-ficha_inscricao-1a2b3c4d5e6f` |
| ID do registro | `<document_id>:<revision_id>` | — |

O mapping vem de `projects/<projeto>/document_types/<tipo>/mapping.json`
(`dynamic: strict`). Alterar um mapping cria outro índice físico; o alias passa a
escrever no novo e continua lendo os anteriores. Mapping, schema e configuração
entram no `pipeline_hash`, então a mudança gera nova revisão mesmo com o mesmo
original (sem reconverter no Docling: o cache continua válido).

Campos do registro: `document_id`, `revision_id`, `document_type`, `project`,
`filename`, `extraction_version` (hash do prompt), `schema_version`, `status`,
`needs_review`, `warnings`, `data` (schema do tipo), `sources` (guardado, não
indexado), `active`, `source.bucket/key`, `created_at`, `updated_at`.

## Protocolo de publicação

O Elasticsearch não tem transação entre índices; por isso:

1. **Preparar**: o registro é gravado com `active=false`. Se uma tentativa
   anterior deixou esse registro ativo, o registro ativo anterior é restaurado.
2. **Validar** (`validar_revisao`): o registro existe, está inativo, pertence à
   revisão e `data` valida contra o schema do tipo, junto com a contagem de chunks.
3. **Publicar**: ativa os chunks da revisão; ativa o novo registro; desativa o
   registro anterior (troca de revisão, tipo ou mapping); confere que não há
   outros registros ativos do documento em `<prefixo>-<projeto>-*`; grava o
   documento com o ponteiro `structured`.
4. **Compensar**: qualquer falha no passo 3 restaura a revisão textual e o
   registro estruturado anteriores (ou deixa nada ativo na primeira publicação)
   e a execução termina como falha. Se a própria compensação falhar, o erro diz
   isso explicitamente e o documento precisa de revisão manual.

No-op e atualização só de metadados devolvem o ponteiro persistido sem chamar o
LLM. O resultado da execução inclui `structured` com `alias`, `index`,
`record_id` e `document_type`.

## Observabilidade

Métricas via `StepResult`/MLflow: `structured_staged`, `structured_fields_count`,
`structured_record_bytes`, `structured_previous_restored`, `structured_validated`,
`structured_published` e `publication_compensated`. Nenhum valor extraído vai
para métricas ou parâmetros.

## Consultas úteis

```bash
# Registros ativos de um tipo
curl -s 'http://127.0.0.1:9201/rag-estruturado-fai-ficha_inscricao/_search' \
  -H 'Content-Type: application/json' \
  -d '{"query":{"term":{"active":true}},"_source":{"excludes":["sources"]}}'

# Conferência completa de um documento (Bronze, Silver, chunks e registro)
python scripts/verify-document.py --document-id <document_id>
```

## Validação realizada (12/11/2026)

- 11 testes novos (`tests/test_structured_index.py`): publicação, no-op, troca de
  tipo (incl. para `outro`), falha parcial com compensação, primeira publicação
  com falha, retry com registro órfão ativo, registro inválido bloqueando a
  publicação, novo índice por mudança de mapping e confinamento de caminhos.
- Os 8 mappings e os métodos do cliente foram exercitados no Elasticsearch real
  (9.5.5) com prefixo temporário: criação, alias idempotente, gravação, ativação,
  contagem por padrão e rejeição de campo fora do mapping. Índices removidos.
- Suíte: 114 aprovados; as 5 falhas de reranking preexistentes continuam.
- **Ponta a ponta pela CLI** (ficha de inscrição, já autorizada para o Gemini):
  12 steps, Docling reutilizado (0 conversões), `ficha_inscricao`, 9 campos e 9
  evidências, registro ativo em `rag-estruturado-fai-ficha_inscricao-96b09cfc790d`
  e nenhum outro ativo para o documento. MLflow `492b499504f44dd2ba2ff4818a526625`
  com `structured_staged/validated/published = 1` e `publication_compensated = 0`.
- `scripts/verify-document.py`: Bronze, 5 artefatos Silver com hashes do manifesto,
  3 chunks com vetores de 2560 dimensões e registro estruturado ativo: `ok=true`.
- Segunda execução: `noop`, mesma revisão, extração e ponteiro, sem chamada LLM.
- Artefato de eventos do MLflow sem valores pessoais extraídos nem segredos do `.env`.
- Buscas BM25, semântica e híbrida continuam respondendo no índice real.
