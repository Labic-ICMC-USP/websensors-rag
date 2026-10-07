# Tutorial de indexação

A indexação parte de um objeto existente no bucket Bronze do MinIO.

A API devolve um token e executa o processamento de forma assíncrona.

## Etapas executadas

| Ordem | Step | Responsabilidade |
| --- | --- | --- |
| 1 | `resolver_fonte` | localizar o objeto no MinIO e calcular o hash da origem |
| 2 | `detectar_alteracoes` | decidir entre nova revisão, atualização de metadados ou nenhuma ação |
| 3 | `converter_docling` | produzir Markdown e JSON estrutural |
| 4 | `armazenar_silver` | gravar Markdown, JSON e manifesto no MinIO Silver |
| 5 | `segmentar_documento` | criar chunks estruturais |
| 6 | `gerar_embeddings` | gerar vetores para os chunks |
| 7 | `preparar_revisao_elasticsearch` | gravar chunks inativos |
| 8 | `validar_revisao` | conferir a revisão preparada |
| 9 | `publicar_revisao` | ativar a nova revisão e atualizar o documento lógico |

## Enviar um documento

Considere um arquivo já disponível em `rag-bronze/documentos/manual.pdf`.

```bash
curl -X POST http://localhost:8000/documents/index \
  -H 'Content-Type: application/json' \
  -d '{
    "key": "documentos/manual.pdf",
    "metadata": {
      "colecao": "manuais",
      "ano": 2026,
      "area": "engenharia"
    }
  }'
```

A resposta contém um token.

```json
{
  "token": "TOKEN",
  "status": "queued",
  "terminal": false,
  "status_url": "/indexing/TOKEN"
}
```

## Acompanhar o processamento

```bash
curl http://localhost:8000/indexing/TOKEN
```

Durante a execução, `progress.current_step` informa o step atual. Loops internos também publicam progresso, taxa e ETA.

## Saída no terminal

O terminal apresenta cada step separadamente.

```text
step 3/9  converter_docling  EXECUTANDO
Step iniciado
progresso  2/9
ETA do fluxo  calculando

converter_docling  Docling em processamento
Tempo decorrido  18.4s
ETA  12.7s

step 3/9  converter_docling  OK
Documento convertido pelo Docling para Markdown e JSON.
duração  31.8s
progresso  3/9
ETA do fluxo  54.2s
```

No final, uma tabela resume todos os steps e suas durações.

## Repetir a mesma indexação

Quando o arquivo, a configuração de processamento e os metadados não mudaram, a execução termina como `noop`.

```bash
curl -X POST http://localhost:8000/documents/index \
  -H 'Content-Type: application/json' \
  -d '{
    "key": "documentos/manual.pdf",
    "metadata": {
      "colecao": "manuais",
      "ano": 2026,
      "area": "engenharia"
    }
  }'
```

## Atualizar somente metadados

Quando somente os metadados mudam, o serviço não executa Docling, chunking ou embeddings novamente.

```bash
curl -X POST http://localhost:8000/documents/index \
  -H 'Content-Type: application/json' \
  -d '{
    "key": "documentos/manual.pdf",
    "metadata": {
      "colecao": "manuais",
      "ano": 2026,
      "area": "engenharia",
      "revisado": true
    }
  }'
```

## Forçar reprocessamento

```bash
curl -X POST http://localhost:8000/documents/index \
  -H 'Content-Type: application/json' \
  -d '{
    "key": "documentos/manual.pdf",
    "force": true
  }'
```

`force` cria uma nova revisão mesmo quando a origem permanece igual.

## Artefatos Silver

A revisão completa grava três objetos.

```text
document.md
document.json
manifest.json
```

O Markdown é usado para chunking.

O JSON preserva estrutura e informações extraídas pelo Docling.

O manifesto liga a revisão ao arquivo de origem e à configuração de processamento.
