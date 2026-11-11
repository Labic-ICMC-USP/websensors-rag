# Inferência remota pelo OpenRouter

A decisão de 11/11/2026 substitui os embeddings locais do Ollama por OpenRouter
para reduzir o uso dos recursos de inferência compartilhados. O Ollama e o
Docling existentes não foram parados, reiniciados ou reconfigurados.

## Configuração de embeddings

Guarde a chave no `.env` da raiz do projeto:

```dotenv
OPENROUTER_API_KEY=coloque-a-chave-aqui
```

```bash
chmod 600 .env
```

O arquivo é ignorado pelo Git. O loader resolve valores YAML inteiros no formato
`${VAR}`; não executa o arquivo como script e não exporta suas variáveis para o
processo. Variáveis já definidas no ambiente têm prioridade sobre o `.env`.
Para YAMLs em `config/`, lê o `.env` da raiz; para outros locais, lê o `.env`
adjacente. Python pode selecionar um arquivo explícito com
`load_rag_settings(path, env_file=...)`.

Bloco já aplicado em `config/rag.local.yaml`:

```yaml
services:
  embeddings:
    endpoint: "https://openrouter.ai/api/v1"
    path: /embeddings
    models_path: /embeddings/models
    api_key: "${OPENROUTER_API_KEY}"
    model: qwen/qwen3-embedding-4b
    dimensions: 2560
    batch_size: 32
    timeout_seconds: 120
```

A chave fica referenciada no YAML, sem seu valor. Se ela estiver ausente, o loader
interrompe com o nome da variável faltante. Não há fallback automático para
Ollama. O `EmbeddingClient` existente é mantido; `models_path` permite usar o
catálogo de embeddings do OpenRouter, separado do catálogo de chat.

Após a indisponibilidade do Qwen3 Embedding 0.6B (HTTP 404, sem provedores),
o responsável solicitou o teste do Qwen3 Embedding 4B. O teste autenticado pelo
`EmbeddingClient`, observado no MLflow, passou: dez vetores finitos e não nulos,
2560 dimensões e 5,117 segundos. Cinco consultas retornaram os trechos esperados
em primeiro lugar em um conjunto pequeno e sintético. Isso confirma integração,
não qualidade geral, equivalência ao 0.6B ou aprovação dos documentos reais.

O YAML local agora usa `qwen/qwen3-embedding-4b` e dimensão 2560, conforme a
resposta efetiva. Índice e alias de chunks retornaram 404 antes do ajuste, sem
vetores existentes para migrar. Não há fallback automático para outro modelo.
Trocar modelo muda o espaço vetorial,
mesmo que a dimensão seja igual. Os índices RAG configurados ainda não existiam
na verificação anterior à mudança. Não misturar vetores de modelos diferentes
em uma mesma revisão. O `pipeline_hash` existente já considera o modelo de
embeddings e gera outra revisão quando ele muda.

Os testes remotos usaram apenas texto sintético. O processamento futuro de
originais enviará os textos/chunks ao provedor configurado e será cobrado de
acordo com seu uso da API.

## O que pode ser remoto

| Etapa | Situação |
| --- | --- |
| Embeddings | Qwen3 Embedding 4B testado e configurado no OpenRouter, 2560 dimensões |
| Classificação documental | Prevista via chat OpenAI-compatible/OpenRouter; ainda não implementada |
| Extração semântica | Prevista via chat com prompt/schema; ainda não implementada |
| Descrição de figuras no Docling | Pode usar API remota OpenAI-compatible; preset existente ainda precisa ser auditado |
| PDF, layout, tabelas e OCR | Continuam no Docling local no pipeline standard atualmente usado |
| MinIO, Elasticsearch e MLflow | Permanecem na infraestrutura local |

O OpenRouter não substitui o serviço de conversão Docling na arquitetura atual.
Mover a descrição de figuras requer conferir se o deployment permite serviços
remotos e configurar um preset para um modelo com visão. O preset compartilhado
`labic_vision` não foi alterado. Não assumir que o nome do preset significa que
já aponta para OpenRouter, nem enviar novas conversões antes dessa verificação
se o objetivo for evitar o uso de um VLM local.

Mesmo com inferência remota, o Docling local pode consumir CPU/GPU em OCR,
layout e tabelas. Limitar ou usar apenas CPU exige configurar um deployment
apropriado; alterar o serviço compartilhado pode afetar seus outros usuários.
Isso será tratado separadamente, preservando os processos existentes. Nenhum
novo modelo foi carregado no Ollama durante esta mudança.

## Observabilidade

O teste anterior de embeddings BGE-M3 remotos foi um step diagnóstico do WebSensors-Flow usando
o `EmbeddingClient` existente. O observer MLflow registrou provedor/modelo,
duração, quantidade e dimensão dos vetores; a execução finalizou com sucesso.
Não foram gravados a chave, vetores completos ou documentos pessoais no MLflow.
O relatório local está em `.local/embedding-validation/openrouter-report.json`.

A tentativa com o Qwen solicitado também foi registrada no MLflow, como falha
HTTP 404, sem chamada de inferência local. O relatório está em
`.local/embedding-validation/qwen-openrouter-report.json`.

Na medição de GPU desta etapa, o PID 3664 foi identificado como `docling-serve`
e ocupava 1480 MiB na RTX A5000. Esse valor não é limite; pode crescer conforme
lotes, concorrência e documento. A GPU global estava com 19477/24564 MiB
ocupados e 100% de utilização. Não foram iniciadas conversões para medir picos.
A API RAG local foi configurada com `indexing_workers: 1`, limitando seus próprios
jobs concorrentes quando for iniciada; isso não limita outros consumidores do
Docling nem cria um teto de VRAM para o serviço compartilhado.

O teste não implementa a classificação ou a extração. Essas etapas deverão usar
o mesmo mecanismo de eventos e métricas quando forem adicionadas ao pipeline.

## Fontes verificadas

- [API de embeddings](https://openrouter.ai/docs/api/api-reference/embeddings/submit-an-embedding-request).
- [Catálogo de embeddings](https://openrouter.ai/docs/api/api-reference/embeddings/list-embeddings-models).
- [Modelo bge-m3](https://openrouter.ai/baai/bge-m3).
- [Docling: descrição remota de imagens](https://docling-project.github.io/docling/usage/api_server/rest_api/#picture-description).


Teste Qwen3 4B: relatório em
`.local/embedding-validation/qwen4-openrouter-report.json` e execução MLflow
`44f117da150c4193b7f4f92f74dcef19`. Nenhuma chamada de inferência local,
conversão Docling ou indexação foi realizada neste teste.
