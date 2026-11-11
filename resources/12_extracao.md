# Extração estruturada — Fase D

A configuração local habilita extração por `google/gemini-2.5-flash` via
OpenRouter, após a classificação e antes do armazenamento Silver. O fluxo
completo tem onze steps. Docling continua local e seu cache é reutilizado.
Embeddings usam o `EmbeddingClient` com Qwen3 Embedding 4B remoto.

```yaml
extraction:
  enabled: true
  max_input_chars: 100000
  max_output_tokens: 16384
  structured_output: false
```

É necessário habilitar `classification` e configurar `services.llm`.
`extraction.structured_output` controla apenas o formato pedido ao provedor na
extração: false usa JSON comum com schema explícito no payload; a validação local
por JSON Schema permanece obrigatória. null (padrão) herda a opção de
`services.llm.structured_output`, preservando instalações existentes. A
classificação local continua com saída estruturada no provedor. No YAML de
exemplo, a extração permanece desabilitada para preservar o fluxo legado.
Indexações sem projeto não executam os novos steps semânticos.

## Recursos por tipo

Cada um dos oito tipos em `projects/fai/document_types/` tem `prompt.md`,
`schema.json` e `mapping.json`. A categoria validada seleciona esses recursos.
Os mappings estão preparados para a Fase E; ainda não há publicação em índices
estruturados por tipo.

Schemas usam JSON Schema Draft 2020-12, propriedades explícitas e rejeitam campos
extras. Campos escalares ausentes são null; listas ausentes são vazias. Datas,
valores monetários e identificadores preservam a representação textual original.
O resultado tem o seguinte envelope, montado pelo serviço:

```json
{
  "document_id": "identidade-estavel",
  "revision_id": "revisao",
  "document_type": "ficha_inscricao",
  "status": "success",
  "data": {},
  "sources": [],
  "warnings": []
}
```

`data` segue o schema específico; o exemplo acima apenas ilustra o envelope.
Cada fonte identifica campo de primeiro nível, trecho literal e página ou null.
A validação local confere o trecho no Markdown, tolerando normalização Unicode
e espaços, e rejeita páginas inexistentes no JSON Docling. Isso não demonstra
que a evidência sustenta semanticamente cada valor: a Fase G ainda precisa
comparar os campos com referências humanas.

## Limites e falhas

Uma resposta com JSON, schema ou evidência inválida recebe no máximo uma
solicitação de correção. Retries HTTP transitórios são separados e limitados
pelo cliente. Persistindo a falha, a nova revisão não é publicada; a revisão
ativa anterior é preservada. Respostas interrompidas não são aceitas.

Conteúdo vazio ou acima do limite gera `needs_review`, com dados null e aviso,
sem envio ao modelo ou truncamento silencioso. `outro` gera `not_applicable`,
sem extração especializada. Valores sem evidência, saída sem campos preenchidos,
avisos ou classificação incerta exigem revisão.

O Silver recebe `extraction.json`, junto aos quatro artefatos anteriores. O
manifesto inclui data UTC, referências, hashes dos artefatos, modelo, versões de
prompt/schema e contagens. O `_source` do documento Elasticsearch guarda extração
e metadados; no-op e atualização apenas de metadados os reutilizam. Alterações
nos recursos/configuração de extração invalidam o hash do pipeline.

## Observabilidade e validação

Métricas passam por `StepResult`/contexto do Flow e pelo observer MLflow existente:
duração, validade JSON, campos, bytes, tokens, retries, correção e revisão. Não
se incluem texto integral, dados extraídos ou chave em parâmetros/métricas.

Em 11/11/2026, a ficha autorizada foi classificada e extraída com sucesso:
nove campos preenchidos, nove evidências, zero avisos/correções e zero novas
conversões Docling. Nome, RA e data foram comparados com a referência conhecida.
Execução MLflow: `a40d65856704477f8e36bde2e251635b`. A API ativa também retornou
a extração persistida em no-op, com onze steps e sem nova chamada LLM.

Os quatorze testes novos cobrem os oito schemas, ausência explícita, identificador
com zeros iniciais, evidências, páginas, correção limitada, erro de transporte,
recursos confinados, persistência/hashes, cache e falhas sem trocar a revisão.
A suíte tem 95 testes aprovados e cinco falhas de reranking preexistentes.
A validação de um exemplo não constitui aceite funcional dos oito documentos.

## Diagnóstico de evidências e respostas interrompidas

Erros após a correção preservam o motivo da rejeição, indicando posições como
`sources[10].quote`, sem copiar o conteúdo da evidência. A solicitação de
correção aponta todas as evidências/páginas inválidas encontradas. O prompt de
currículo pede trechos curtos e contínuos e proíbe concatenar citações de partes
separadas. A comparação literal permanece obrigatória.

Respostas interrompidas registram `finish_reason` limitado a valores conhecidos
e o orçamento `max_tokens`. Aumentar tokens não corrige fontes não literais.

## Validação posterior do currículo

Após autorização explícita do usuário, o currículo foi reprocessado com cache
Docling. O diagnóstico reproduziu uma evidência não literal e também interrupção
`finish_reason=length` com 100.000 tokens configurados. A mudança no prompt e no
feedback passou a pedir trechos contínuos e informar todas as posições inválidas.
No teste com JSON comum na extração e 16.384 tokens por chamada, o resultado
passou pela validação de schema/evidências após uma correção: nove campos de
primeiro nível preenchidos e 38 fontes. O modelo e o schema foram mantidos.
Isso indica que essa configuração resolveu o caso testado; não prova uma causa
única no provedor nem estabelece acurácia semântica de todos os valores.

Execução MLflow: `7d3a3f45cc1e4fe1be4d9f900a09c3e3`, Flow
`4a719df23e22459cad33a27f1259c8d4`, `docling_reused=1`, conversões zero.
Relatório sem valores pessoais: `.local/extraction-validation/curriculo-report.json`.
A suíte após estes ajustes tem 103 testes aprovados e as mesmas cinco falhas de
reranking preexistentes. A avaliação humana completa da extração continua na Fase G.
