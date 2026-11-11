# Classificação documental — Fase C

O pipeline do projeto FAI usa `google/gemini-2.5-flash` pelo OpenRouter para
classificar o Markdown produzido pelo Docling. Os embeddings continuam sendo
`qwen/qwen3-embedding-4b`, com 2560 dimensões; são operações diferentes.

## Configuração

Na configuração local, já habilitada:

```yaml
services:
  llm:
    endpoint: https://openrouter.ai/api/v1
    model: google/gemini-2.5-flash
    api_key: "${OPENROUTER_API_KEY}"
    temperature: 0
    max_tokens: 2048
    timeout_seconds: 120
    retries: 2
    structured_output: true

classification:
  enabled: true
  projects_dir: /exp/golomarcos/websensors-rag/projects
  max_input_chars: 100000
```

Integre aos blocos existentes; não duplique `services`. A chave permanece no
`.env`, sem valor literal no YAML. O caminho absoluto é específico desta máquina.
Caminhos relativos são resolvidos a partir da raiz do YAML em `config/`, ou do
diretório do YAML em outros locais.

A classificação é opt-in: desabilitada no YAML de exemplo, mantém os nove steps
anteriores e o hash legado. Habilitada, acrescenta um step após o Docling, antes
de armazenar Silver, totalizando dez steps. Indexação legada sem projeto não
executa classificação LLM. Os fluxos curtos do extrator OpenWebUI só convertem;
a classificação ocorre quando a Tool inicia o processamento completo.

## Recursos e contrato

- `projects/fai/classification/categories.json`: categorias e definições.
- `projects/fai/classification/prompt.md`: regras da classificação.
- `classification/service.py`: carrega recursos, gera schema e valida resultado.
- `classification/steps.py`: step Flow com eventos/métricas e registro do modelo.
- `clients/llm_client.py`: HTTP compatível com Chat Completions, sem servidor novo.

```json
{
  "document_type": "ficha_inscricao",
  "reason": "Documento apresenta campos de candidatura e inscrição.",
  "needs_review": false
}
```

A lista de categorias vem do JSON do projeto. `outro` exige revisão. Categoria
fora da lista, justificativa vazia, booleano inválido ou campos extras são
rejeitados. O conteúdo é enviado como dados e o prompt instrui a ignorar
instruções contidas no documento; essa instrução não elimina todos os riscos de
prompt injection, por isso o resultado é validado localmente.

A fonte de uma decisão explícita por `--document-type` fica registrada como
`declared`, sem apresentar essa decisão como predição LLM. O tipo declarado
precisa pertencer ao projeto. Não fornecer esse parâmetro nos testes de acurácia.

Se o documento estiver vazio ou superar o limite de caracteres, a classificação
retorna `outro` com revisão e justificativa explícita, sem cortar o texto e sem
chamar o modelo. O limite é conservador, em caracteres, não um contador exato de
tokens. Pode ser configurado conforme o contexto e o orçamento do modelo.

## Falhas, persistência e revisões

Falhas de conexão e HTTP transitórios têm tentativas limitadas (408, 429, 5xx
selecionados). Erros de autenticação não são repetidos. JSON inválido, resposta
interrompida ou categoria inválida não são aceitos como sucesso. Uma falha na
classificação interrompe a nova revisão antes da publicação, preservando a
revisão ativa anterior.

O Silver recebe `classification.json`. O manifesto registra modelo, fonte da
decisão e versão do prompt/categorias. A classificação também fica no `_source`
do documento Elasticsearch, para recuperação pelo serviço; o índice estruturado
por tipo continua reservado à Fase E. A classificação não é um campo de
extração semântica.

Mudanças no modelo/configuração, prompt ou categorias alteram `pipeline_hash`.
Mudança de tipo declarado também invalida a revisão. A chave não integra o hash.
No-op ou atualização só de metadados reutilizam a classificação persistida.
O cache Docling continua dependendo apenas de fonte/opções de conversão e pode
ser reutilizado após alterações de classificação, sem usar novamente a GPU.

As métricas usam `StepResult` e o contexto do Flow: duração, sucesso, categoria
outro, necessidade de revisão, retries e tokens informados pelo provedor. Não
se registram documentos integrais ou chave em parâmetros/métricas MLflow.

## Validação realizada

Em 11/11/2026, após autorização explícita do responsável para o envio da ficha
ao Gemini via OpenRouter, o pipeline classificou o exemplo real como
`ficha_inscricao`, com `needs_review=false`. Foram dez steps, com
`docling_reused=1`, `docling_conversions=0`, três chunks publicados e execução
MLflow `7cdc45d9ee84403585696d3a5d16bd15`. A API atualizada também devolveu essa
classificação em uma chamada no-op, sem nova inferência ou conversão.

Os testes automatizados cobrem cliente HTTP, todas as categorias com mocks,
respostas inválidas, desconhecidos, limite sem truncamento, cache, hash,
persistência, reprocessamento e preservação da revisão ativa em falha.

Essa verificação de um documento não equivale ao aceite do conjunto inteiro:
a Fase G ainda deverá avaliar os oito originais e exigir 8/8 acertos. Outros
documentos pessoais não foram enviados ao Gemini nesta validação.
A extração estruturada foi implementada posteriormente: consulte [Fase D](12_extracao.md).

Referência: [respostas estruturadas no OpenRouter](https://openrouter.ai/docs/guides/features/structured-outputs).
