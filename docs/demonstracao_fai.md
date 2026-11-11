# Demonstração FAI — do original aos vetores

Execute as consultas no servidor `chope`, com o ambiente `FAI_final` ativo, a
partir de `/exp/golomarcos/websensors-rag`. São verificações de leitura: não
chamam LLM/Docling, não geram embeddings e não alteram dados.

## 1. Fluxo no OpenWebUI

Anexe o currículo e peça o processamento com a Tool habilitada. Aguarde o
resultado terminal e guarde `document_id`, `revision_id`, `trace_id` e `token`.
Com a Tool 0.2.1, cada chamada pede uma nova execução semântica. A conversão
Docling permanece em cache. Só declare a nova revisão concluída se a resposta
for `status=success` e `action=indexed`.

## 2. Conferência integrada no terminal

```bash
python scripts/verify-document.py \
  --document-id a4ad7104f6222dc3cd7f4fe5a9ee806e
```

Esse ID é o `lattes.pdf` atual. Para outro documento, copie o ID retornado pela
Tool. O script busca a revisão ativa dinamicamente; não depende de uma revisão
fixa da demonstração anterior.

Explique estes resultados:

- `bronze.uri`: local do original; `bytes` maior que zero.
- `bronze.sha256_matches_source=true`: bytes do original correspondem ao hash registrado.
- `silver`: Markdown, JSON estrutural, classificação, extração e manifesto, com tamanhos/hashes.
- `silver_hashes_match_manifest=true`: artefatos conferem com o manifesto.
- `elasticsearch.active_chunks`: trechos da revisão ativa do documento.
- `active_chunks_with_embedding`: deve ser igual ao total de chunks ativos.
- `chunks_missing_content=0`: trechos ativos possuem conteúdo indexado.
- `embedding_dimensions_sample=2560`: dimensão do vetor realmente recuperado.
- `embedding_first_four_values`: amostra numérica do vetor, sem imprimir 2560 valores.
- `sample_chunk_text_characters`: quantidade de caracteres do trecho de exemplo.
- `ok=true`: todas as verificações acima passaram.

O script lê os cinco artefatos Silver e o original Bronze; não apenas lista nomes.
A dimensão é conferida em um vetor de amostra. A presença do campo embedding é
conferida em todos os chunks ativos da revisão. Isso prova persistência, não
mede qualidade da recuperação semântica nem acurácia de todos os campos extraídos.

## 3. MinIO visualmente

Na máquina em que abrirá o navegador, crie o túnel SSH:

```bash
ssh -N \
  -L 15901:127.0.0.1:9001 \
  -L 15000:127.0.0.1:5000 \
  golomarcos@143.107.183.199
```

Abra `http://127.0.0.1:15901`. Entre com as credenciais MinIO que você configurou
(`MINIO_ROOT_USER`/`MINIO_ROOT_PASSWORD` no `.env.minio`). Não são as credenciais
do OpenWebUI nem a chave OpenRouter.

No Object Browser, mostre:

- `rag-bronze` → `projetos/fai/documentos/<document_id>/<sha256>/lattes.pdf`.
- `rag-silver` → `documentos/<document_id>/<revision_id>/`.

Use os caminhos exatos impressos pelo script. No Silver, mostre:

| Arquivo | O que demonstra |
| --- | --- |
| `document.md` | Conteúdo convertido em texto estruturado |
| `document.json` | Estrutura e páginas produzidas pelo Docling |
| `classification.json` | Tipo documental atribuído |
| `extraction.json` | Campos e evidências da extração especializada |
| `manifest.json` | Origem, revisão, versões, hashes e referências |

Use Preview quando disponível ou baixe o objeto para abri-lo. Pastas de revisões
anteriores e `conversions/` são histórico/cache; para a apresentação, siga a
revisão ativa apontada pelo Elasticsearch/script.

## 4. Elasticsearch diretamente

Índices físicos: `websensors-rag-documents-v1` e `websensors-rag-chunks-v1`.
Aliases usados nas consultas: `websensors-rag-documents` e `websensors-rag-chunks`.

Listagem dos índices:

```bash
curl --fail -sS 'http://127.0.0.1:9201/_cat/indices/websensors-rag-*?v'
```

Metadados, extração e referências MinIO do currículo:

```bash
curl --fail -sS \
  'http://127.0.0.1:9201/websensors-rag-documents/_doc/a4ad7104f6222dc3cd7f4fe5a9ee806e?pretty&filter_path=_id,found,_source.active_revision,_source.source,_source.silver,_source.classification,_source.extraction'
```

Mapping do campo vetorial:

```bash
curl --fail -sS \
  'http://127.0.0.1:9201/websensors-rag-chunks/_mapping/field/embedding?pretty'
```

Espere `type=dense_vector`, `dims=2560`, `index=true` e `similarity=cosine`.

Texto e amostra de vetor do mesmo chunk ativo:

```bash
curl --fail-with-body -sS \
  'http://127.0.0.1:9201/websensors-rag-chunks/_search?pretty' \
  -H 'Content-Type: application/json' \
  --data-binary @- <<'JSON'
{
  "size": 1,
  "_source": ["document_id", "revision_id", "chunk_id", "active", "content"],
  "query": {
    "bool": {
      "filter": [
        {"term": {"document_id": "a4ad7104f6222dc3cd7f4fe5a9ee806e"}},
        {"term": {"active": true}}
      ]
    }
  },
  "script_fields": {
    "embedding_dims": {
      "script": {"source": "doc['embedding'].vectorValue.length"}
    },
    "embedding_sample": {
      "script": {
        "source": "def v = doc['embedding'].vectorValue; return [v[0], v[1], v[2], v[3]];"
      }
    }
  }
}
JSON
```

O retorno mostra o texto em `_source.content` e os valores do vetor em `fields`.
A contagem global do índice pode incluir chunks de revisões antigas. Use `active`
e `revision_id` ao conferir uma publicação específica.

## 5. MLflow e vínculo entre etapas

Com o mesmo túnel, abra `http://127.0.0.1:15000` e selecione o experimento
`websensors-flow-rag`. Localize a tag `run_id` correspondente ao `trace_id`
retornado pela Tool. Mostre o estado final, steps, modelos e métricas:

- `classification_success=1` e `extraction_success=1` para execução nova.
- `extraction_json_valid=1`, número de campos, tentativas/correções e duração.
- `docling_reused=1`/`docling_conversions=0` quando reutilizou apenas a conversão.
- Etapas de embeddings, validação e publicação concluídas.

As métricas reais têm prefixos dos steps. Valores pessoais extraídos ficam nos
artefatos Silver/resultado da Tool, não em parâmetros/métricas MLflow.

A cadeia a demonstrar é:

```text
OpenWebUI → execução Flow/MLflow
                 ↓
Bronze: original → Silver: conversão + classificação + extração
                 ↓
Elasticsearch: documento/revisão + chunks ativos + vetores
```
