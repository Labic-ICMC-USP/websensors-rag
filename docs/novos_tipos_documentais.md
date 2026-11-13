# Adicionar tipos documentais e projetos

Categorias, prompts, schemas e mappings são arquivos de configuração em
`projects/`. Nenhum tipo documental está fixo no código Python: para incluir um
tipo ou um projeto novo basta criar arquivos, sem alterar `src/`.

```text
projects/
  <projeto>/
    classification/
      categories.json      # categorias aceitas e suas definições
      prompt.md            # regras da classificação
    document_types/
      <tipo>/
        prompt.md          # regras específicas da extração
        schema.json        # JSON Schema 2020-12 do resultado
        mapping.json       # mapping Elasticsearch do índice estruturado
```

Nomes de projeto e tipo usam letras minúsculas, números, `_` ou `-` (o tipo
começa com letra). Caminhos fora de `projects/` são rejeitados.

## 1. Registrar a categoria

Acrescente o tipo em `classification/categories.json`, com uma definição baseada
no **conteúdo** do documento (o nome do arquivo não decide a categoria):

```json
{
  "historico_escolar": "Relação de disciplinas cursadas com notas, frequência e período letivo.",
  "outro": "Documento desconhecido ou sem evidências suficientes."
}
```

`outro` é obrigatório; documentos classificados assim não passam por extração
especializada e continuam indexados textualmente.

## 2. Criar prompt, schema e mapping

Copie um tipo existente como ponto de partida (por exemplo,
`projects/fai/document_types/ficha_inscricao/`) e ajuste:

- **`schema.json`**: o objeto raiz tem `data`, `sources` e `warnings`, todos
  obrigatórios e com `additionalProperties: false`. Em `data`, declare cada campo;
  escalares ausentes são `null` e listas ausentes são `[]`. Em `sources.items.field`,
  o `enum` deve listar os campos de `data`.
- **`prompt.md`**: mantenha o bloco comum (documento como dado não confiável, sem
  inventar, evidência literal por campo) e acrescente as regras específicas do tipo.
- **`mapping.json`**: `dynamic: "strict"`; em `data`, um tipo Elasticsearch para cada
  campo do schema (`text`, `keyword`, `double`, `date`...). Preserve os campos de
  controle (`document_id`, `revision_id`, `document_type`, `project`, `filename`,
  `extraction_version`, `schema_version`, `status`, `needs_review`, `warnings`,
  `sources`, `active`, `source`, `created_at`, `updated_at`).

Datas e identificadores com zeros à esquerda devem ficar como texto no schema e
no mapping, para preservar a forma original.

## 3. Conferir

```bash
# Schemas válidos e aceitação de campos ausentes para todos os tipos
python -m pytest tests/test_extraction.py tests/test_structured_index.py

# Processar um exemplo do novo tipo (sem informar o tipo, para testar a classificação)
python -m websensors_flow_rag process --config config/rag.local.yaml \
  --file exemplo.pdf --project fai --output-file .local/exemplo.json
```

O teste `test_all_eight_schemas_accept_explicit_missing_values` verifica os tipos
do projeto `fai`; ajuste a contagem esperada ao incluir um tipo nesse projeto.

## Efeitos no processamento

- Os arquivos de `classification/` e `document_types/` entram no `pipeline_hash`.
  Alterá-los gera nova revisão no próximo processamento de cada documento, sem
  reconverter no Docling (o cache Silver continua válido).
- Um `mapping.json` alterado cria outro índice físico
  (`<prefixo>-<projeto>-<tipo>-<hash>`); o alias `<prefixo>-<projeto>-<tipo>`
  passa a escrever no novo e continua lendo os anteriores.
- O índice do tipo é criado na primeira publicação; não há passo manual no
  Elasticsearch.

## Novo projeto

Crie `projects/<projeto>/` com a mesma estrutura e envie `project=<projeto>` pela
API, pela Tool (Valve `PROJECT`) ou pela CLI (`--project`). Projetos diferentes
usam índices estruturados diferentes; os índices textuais são compartilhados.

Guias relacionados: [classificação](../resources/11_classificacao.md),
[extração](../resources/12_extracao.md) e
[índices estruturados](../resources/13_indices_estruturados.md).
