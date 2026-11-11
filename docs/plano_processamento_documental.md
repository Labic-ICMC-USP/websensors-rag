# Fase A — análise e decisões de processamento documental

Data: 11/11/2026. Fonte: plano fornecido pelo usuário, `reais-golo.zip` e `edital.pdf` adicional.

## Verificação posterior dos serviços locais

Atualização de 11/11/2026, após a inspeção inicial descrita abaixo:

- MinIO AIStor iniciado em `http://127.0.0.1:9000`; buckets Bronze/Silver e
  usuário RAG preparados; escrita/leitura confirmadas nos dois buckets.
- Elasticsearch existente reativado em `http://127.0.0.1:9201`; versão 9.5.5,
  cluster green e acesso local sem autenticação. Nenhum índice alterado.
- Docling Serve 1.34.0 em `http://127.0.0.1:5001`; health/ready HTTP 200.
  Docling interno 2.128.0. Rotas async/poll/result compatíveis com o cliente.
- Conversões pelo `DoclingClient` existente, mantendo as opções do projeto
  (`rapidocr`, `dlparse_v4`, `labic_vision`): ficha de inscrição em 16,05 s
  (487 caracteres Markdown), CNH em 9,05 s (1.508 caracteres Markdown), ambas
  com JSON estrutural e sem erros reportados. Cada original foi salvo no Bronze
  antes da conversão e convertido uma vez neste diagnóstico.
- Na CNH digitalizada, presença do nome, indicação de habilitação, nascimento
  e validade foi conferida no Markdown. Isso demonstra OCR para esse exemplo;
  não equivale à validação semântica de todos os campos ou do conjunto completo.
- Resultados diagnósticos estão em `.local/docling-validation/`, fora do Git.
  Não foram indexados no Elasticsearch ou publicados como revisão Silver.
- Dependências declaradas do projeto instaladas em modo editável no ambiente
  `FAI_final`, permitindo carregar o YAML e usar os clientes existentes.
- Endpoint Docling ajustado no YAML local; opções de conversão preservadas.
  Esta instalação não expõe `/v1/capabilities` (404); a verificação funcional
  dos parâmetros usou a conversão real, sem pressupor essa rota.

As limitações de rede relatadas na inspeção inicial se referem aos nomes Docker
no YAML de exemplo. Os três serviços acima já estão acessíveis pelas portas do
host.

Embeddings verificados posteriormente no Ollama existente, por escolha explícita
do usuário: `http://127.0.0.1:11434/v1`, modelo `qwen3-embedding:0.6b`, 1024
dimensões, sem chave no endpoint local. O `EmbeddingClient` existente gerou dois
vetores finitos e não nulos em 23,82 s no primeiro teste. Não foram encontrados
LiteLLM/vLLM nas portas locais 4000/8000. Os índices/aliases RAG configurados
retornaram 404; não houve migração ou alteração de vetores existentes.

O YAML local usa o Ollama no lugar do exemplo LiteLLM/inpi. O mecanismo de
embeddings foi preservado. Essa escolha substitui a premissa inicial do plano
sobre o provedor de embeddings disponível. O provedor de chat/classificação é
uma configuração separada e ainda não foi definido.

Classificação, extração semântica e validação de aceitação ainda não foram executadas.

## Decisão posterior: observabilidade obrigatória e inferência remota

Em 11/11/2026, o responsável solicitou MLflow antes da indexação e execução sem
interromper ou prejudicar outros processos. Foi instalada uma instância separada
MLflow 3.17.2 em `http://127.0.0.1:5000`, por systemd de usuário, com SQLite e
artefatos persistentes em disco local, limite de uma CPU e 2 GiB de memória.
Jobs de avaliação online foram desativados. Métrica, progresso, spans e download
de artefato foram conferidos pelo `MLflowObserver` existente.

Após a chave ser disponibilizada pelo responsável no `.env`, embeddings foram
migrados para `https://openrouter.ai/api/v1`, modelo `baai/bge-m3`, dimensão 1024.
Teste real com dois textos sintéticos passou dentro de um fluxo observado pelo
MLflow. O cliente `EmbeddingClient` foi preservado. O loader passou a resolver
`${VAR}` pelo ambiente/`.env`; a chave não foi gravada no YAML.

Nenhum serviço compartilhado foi reiniciado. Nenhuma inferência foi enviada ao
Ollama durante essa etapa. Docling permanece local: OCR/layout ainda consomem
recursos da máquina; migrar o VLM do preset compartilhado exige análise separada.
Classificação e extração semântica ainda serão implementadas.

Validação automatizada: 41 testes passaram; cinco testes de reranking falharam.
As mesmas cinco falhas foram reproduzidas numa cópia temporária do HEAD original,
sem estas mudanças. Não foram corrigidas fora do escopo. Guias atualizados em
`resources/09_mlflow.md` e `resources/10_openrouter.md`.

## Escolha posterior de modelo e medição de GPU

O responsável manteve Docling local e escolheu explicitamente
`qwen/qwen3-embedding-0.6b` para embeddings no OpenRouter, com LLM também remota.
O YAML local foi atualizado e não usa fallback para BGE ou Ollama. O teste
observado pelo Flow retornou HTTP 404, sem endpoints para esse modelo; a execução
foi registrada como falha no MLflow. Naquele momento a API de provedores informou
zero endpoints e o catálogo de embeddings listou apenas Qwen 4B/8B. A indexação
não deve prosseguir sem o modelo disponível ou outra decisão do responsável.

O PID 3664 (`docling-serve`) já ocupava 1480 MiB de VRAM. A GPU global tinha
19477/24564 MiB ocupados e 100% de utilização no instante consultado. Essa medição
não estabelece teto de consumo do Docling. Não houve nova conversão ou inferência
local. A concorrência da futura API RAG foi reduzida a um worker de indexação;
essa medida não limita o servidor Docling compartilhado nem garante uso fixo de
memória ou ausência de disputa por GPU. Nenhum processo alheio foi alterado.

## Teste posterior do Qwen3 Embedding 4B

Após a indisponibilidade do 0.6B no OpenRouter, o responsável solicitou o teste
do 4B. Em 11/11/2026, o `EmbeddingClient` existente retornou dez vetores válidos
de 2560 dimensões em 5,117 s. Cinco consultas recuperaram os trechos esperados
em primeiro lugar num teste sintético pequeno. Não é avaliação funcional dos
originais nem comparação medida contra o 0.6B.

A execução foi registrada no MLflow como FINISHED
(`44f117da150c4193b7f4f92f74dcef19`). O YAML local agora seleciona
`qwen/qwen3-embedding-4b` com 2560 dimensões. Índice e alias de chunks ainda não
existiam na conferência anterior à mudança. Não houve migração, indexação,
conversão Docling ou inferência local. O 0.6B permanece indisponível no provedor;
o teste bem-sucedido do 4B substitui o estado de espera descrito acima.

## Fase B — implementação e estado de integração

O usuário confirmou no navegador a recuperação do anexo original (HTTP 200,
28.495 bytes, assinatura PDF) e texto convertido de 487 caracteres. Os campos
observados continham apenas `data.status` e `data.content`, sem JSON estrutural.

Implementados `ProcessDocumentService`, upload multipart na FastAPI existente,
consulta de jobs, CLI `python -m websensors_flow_rag process`, entrada opcional
de artefatos com hashes e Tool OpenWebUI. Executor, store, locks e observadores
existentes foram centralizados no serviço. A rota antiga de indexação permanece.

Para evitar dupla conversão entre upload e Tool, a mesma API também implementa
o contrato de extrator externo OpenWebUI: preserva Bronze, reutiliza steps
Docling/Silver num Flow observado e mantém cache no Silver por fonte/opções.
A Tool exige artefatos compatíveis e recusa reconversão silenciosa. Não se
construiu outro conversor ou servidor independente.

A API está ativa na ponte Docker `172.18.0.1:8000`, com token referenciado no
`.env`, limite de uma CPU e 2 GiB de RAM. Autenticação e publicação de rotas
foram verificadas por HTTP; os cinco serviços passaram no startup. Índices e
aliases textuais foram preparados com dimensão 2560. Nenhuma conversão de
produção foi iniciada nesta implementação.

Testes: 54 passaram; as mesmas cinco falhas anteriores de reranking permanecem.
Os treze testes novos da Fase B usam clientes externos simulados e cobrem
conversão única, cache/proveniência, Bronze antes do Flow, falhas, limites, rota
antiga, CLI, jobs e separação de credenciais na Tool.

**Pendente para concluir a integração real da Fase B:** configurar o extrator
externo e importar/habilitar a Tool no OpenWebUI; testar o retorno no chat e
comparar com CLI nos serviços reais. Essas configurações globais do OpenWebUI
não foram alteradas durante o desenvolvimento. Guias em `docs/tutorial_cli.md`
e `docs/tutorial_openwebui.md`. Classificação e extração continuam pendentes
para as Fases C/D e são retornadas como null com aviso explícito.

## Fase C — classificação integrada e validada

O responsável definiu `google/gemini-2.5-flash` como modelo de chat. Implementados
cliente com retries limitados, categorias/prompt externos, schema de resposta,
validação local e `ClassifyDocumentTypeStep` entre Docling e Silver. O modelo,
os parâmetros e os recursos de classificação integram o hash, sem a chave.
No-op reutiliza a classificação; falha impede a nova publicação.

A revisão automática inicialmente rejeitou o envio da ficha por conter dados
pessoais. Após autorização explícita do usuário para esse documento/destino,
o teste real passou: `ficha_inscricao`, `needs_review=false`, cache Docling
reutilizado e zero conversões novas. A execução MLflow é
`7cdc45d9ee84403585696d3a5d16bd15`, com dez steps concluídos e três chunks ativos.
A API RAG foi atualizada, sem reiniciar Docling/Ollama/OpenWebUI; a classificação
persistida também foi conferida em uma requisição no-op pela API.

A classificação é armazenada em Silver e no `_source` do documento. Fase D ainda
precisa implementar schemas/prompts de extração e Fase E os índices estruturados.
A avaliação funcional completa dos oito exemplos é pendente da Fase G.
Os testes de todas as categorias realizados aqui usam mocks, além do teste real
específico da ficha autorizado pelo usuário. Detalhes em `resources/11_classificacao.md`.

## Fase D — extração implementada e ativada

Criados prompts, schemas estritos e mappings explícitos para os oito tipos.
`ExtractStructuredDataStep` seleciona recursos pela classificação, valida JSON e
evidências, permite uma correção e registra revisão quando faltam evidências ou
o conteúdo excede o limite. Falha de validação impede publicar a nova revisão.
`outro` não chama a extração especializada. Configuração/hash, WorkItem, Silver,
manifesto com hashes/data UTC, resultado e no-op incluem a extração.

A ficha já autorizada foi validada com Gemini/OpenRouter: nove campos, nove
fontes, JSON válido, sem avisos, sem correções e sem nova conversão Docling.
Nome, RA e data foram comparados com a referência. Execução MLflow
`a40d65856704477f8e36bde2e251635b`. Relatórios locais em
`.local/extraction-validation/`, sem valores pessoais no relatório de métricas.
A API própria foi reiniciada e validada com onze steps; no-op devolve a extração
persistida. Docling, Ollama e OpenWebUI não foram reiniciados.

Quatorze testes novos de extração passaram; suíte: 95 aprovados e as mesmas
cinco falhas preexistentes de reranking. Guia: `resources/12_extracao.md`.
Fase E segue pendente: publicação estruturada por tipo e compensação entre
índices. Os mappings preparados nesta fase ainda não são índices publicados.
A avaliação funcional dos oito documentos permanece reservada à Fase G.

## Ajuste posterior da Fase D — currículo

O usuário autorizou explicitamente o reenvio do currículo ao Gemini/OpenRouter
para investigar falhas. O novo diagnóstico identificou evidência não literal e
interrupção por comprimento, mesmo com teto configurado de 100.000 tokens.
Foram preservados os motivos seguros de falha e posições de todas as evidências
inválidas, para correção única. O prompt de currículo pede citações contínuas.

O teste com saída JSON comum na extração, schema explícito no payload e validação
local obrigatória passou com 16.384 tokens por chamada: 38 fontes, nove campos
preenchidos, uma correção e nenhuma conversão Docling. Modelo preservado.
MLflow `7d3a3f45cc1e4fe1be4d9f900a09c3e3`. A configuração de formato da extração
foi separada da classificação. Guia atualizado em `resources/12_extracao.md`.
Testes: 103 aprovados e as cinco falhas preexistentes de reranking. Isso não
substitui a comparação humana completa dos valores prevista para a Fase G.

## Estado e limites da inspeção inicial

Inspeção do código e dos oito PDFs realizada. Os sete rótulos do ZIP foram
confirmados explicitamente pelo usuário; o oitavo foi fornecido por ele como edital. A arquitetura abaixo é a proposta para
as fases B–H; nenhuma implementação funcional foi iniciada nesta fase.

O OpenWebUI foi verificado em `http://143.107.183.199:35000`: `/health`
retornou 200 e status true; `/api/version` informou versão **0.11.0**;
`/api/config` confirmou autenticação habilitada. A listagem `/api/v1/files/`
retornou 401 sem credenciais, como esperado. Não houve login, upload ou acesso a
arquivos de outros usuários nessa verificação.

Os nomes configurados no `config/rag.yaml` são `http://minio:9000`,
`http://elasticsearch:9200`, `http://docling:5001`, `http://litellm:4000/v1`
e `http://mlflow:5000` (observabilidade desabilitada no YAML de exemplo).
MinIO, Elasticsearch, Docling e LiteLLM não resolveram nesta sessão de terminal.
São compatíveis com nomes de serviço em rede Docker, mas essa topologia não foi
confirmada. Isso não implica indisponibilidade do OpenWebUI ou dos serviços em
sua rede de implantação. `docker ps` retornou acesso negado ao socket.

Não há `.env` nem configuração local no repositório. O YAML não identifica
endpoint/modelo de chat do OpenRouter. O acesso autenticado à configuração real
de Docling e dos provedores LLM continua pendente; o endereço e a versão do
OpenWebUI já foram identificados.

## Inventário e referência confirmada

São 8 PDFs, 29 páginas, 8 categorias: sete arquivos do ZIP mais o edital separado. O manifesto
`validation/reais-golo.reference.json` fixa SHA-256, páginas e rótulos, sem copiar
os documentos ou seus dados pessoais para o repositório. Os originais permanecem
no ZIP externo e em `/exp/golomarcos/edital.pdf`; arquivos auxiliares de inspeção
estão em `/tmp`.

| Arquivo | Páginas | Tipo confirmado | Estrutura e qualidade local | Campos principais |
| --- | ---: | --- | --- | --- |
| `lattes.pdf` | 10 | `curriculo_lattes` | Seções, foto, ícones, formação e vínculos; texto selecionável com quebras e URLs partidas. Termina no meio da descrição de um projeto. | Nome, ID Lattes, atualização, formação, experiências, projetos |
| `mot-golo.pdf` | 1 | `carta_motivacao` | Título e parágrafos com destinatário, motivação e competências; texto legível, sem imagens raster. | Candidato, curso, instituição, processo, motivação, competências, data |
| `ficha_inscricao_marcos_simplificada (1).pdf` | 1 | `ficha_inscricao` | Formulário de campos em duas colunas; extração mistura rótulos e valores. Identifica-se como material sintético de teste; sem imagens raster. | Candidato, RA, curso, instituição, campus, e-mail, telefone, data, processo |
| `disp.pdf` | 1 | `declaracao_disponibilidade` | Declaração em parágrafo, título e data; texto legível, sem imagens raster. | Declarante, modalidade presencial, local, 20 horas semanais, processo, data |
| `comprovativo-matricula.pdf` | 1 | `comprovante_matricula` | Cabeçalho institucional, declaração, emissão e código; logos e marca d'água. Texto legível. | Aluno, instituição, unidade, matrícula, doutorado, programa, situação, orientador, emissão, validade do código |
| `boleto_09_43_33.pdf` | 2 | `comprovante_residencia` | Conta de energia: endereço do titular, tabelas financeiras, gráfico, códigos de barras e QR. Página 1 tem texto denso; página 2 é visual, com orientações e publicidade, sem texto selecionável. | Titular, endereço, emissor, competência, emissão, vencimento, valor |
| `hab.pdf` | 1 | `documento_identificacao_foto` | CNH digitalizada com retrato, campos e assinatura. Sem camada textual; exige OCR pelo Docling. | Nome, tipo CNH, RG/emissor, CPF, nascimento, filiação, registro, categoria, validade, emissão |
| `edital.pdf` | 12 | `edital` | Texto selecionável com seções numeradas, cronograma e três anexos em tabelas; logos/cabeçalhos raster. Leitura legível, com colunas que precisam ser preservadas. | Órgão, processo, vaga, requisitos, documentos, cronograma, bolsa, jornada, duração, critérios, nota mínima e inconsistências |

A inspeção usou `pdfinfo`, `pdftotext -layout`, `pdfimages -list` e renderização
visual. Isso é diagnóstico dos PDFs, não conversão alternativa do pipeline nem
medida da qualidade do Docling. Os textos de todos os PDFs foram lidos; houve
inspeção visual da primeira página de cada arquivo do ZIP, das páginas finais da
conta e do CV e das páginas 7 (cronograma) e 10 (Anexo I) do edital.

### Ambiguidades e condições de extração

- A conta é confirmada como residência pelo responsável, embora também seja
  documento fiscal e cobrança. O prompt deve considerar sua finalidade no projeto
  e identificar o endereço do titular, separando-o do endereço da concessionária.
- A declaração de matrícula tem título genérico “DECLARAÇÃO”; o conteúdo comprova
  matrícula. O código de autenticidade tem validade própria, distinta da situação
  acadêmica. Registrar datas sem declarar fraude ou validade acadêmica por inferência.
- Carta, ficha e disponibilidade mencionam edital; essa menção não as torna edital.
- O currículo contém uma foto; isso não o torna documento de identificação.
- Carta/ficha e comprovante/CV descrevem contextos acadêmicos diferentes. Não
  corrigir um documento usando outro nem inventar uma reconciliação cadastral.
- Preservar grafia e acentos; identificadores são strings. CPF mascarado na conta
  continua mascarado. Campos de contato ausentes na CNH não vêm da ficha.
- O CV fornecido é parcial. Publicações não presentes devem ficar ausentes/listas
  vazias; não buscar o Lattes online para completar os dados.
- O edital inclui 1 vaga, jornada de 20 horas semanais, bolsa de R$ 1.140,00,
  período de 12 meses e nota mínima de 7,0. Os três anexos tratam de documentos
  habilitatórios, avaliação curricular (até 4 pontos) e entrevista (até 6 pontos).
- O cronograma do edital inicia inscrições em 02/02/2026, antes da publicação em
  03/02/2026. A seção 9.2 menciona acompanhamento do resultado em 18/02/2026,
  enquanto o cronograma registra aprovados em 20/02/2026. Preservar as datas e
  sinalizar a divergência com referências; não escolher uma como correção.
- Os anexos reiniciam a numeração impressa: páginas físicas 10–12 mostram 1–3.
  Evidências devem distinguir página física de número impresso.
- As regras de candidatura contidas no edital são conteúdo a extrair, sem executar
  inscrições, acessar formulários ou tomar decisões sobre aprovação de candidato.
- Sem exemplos de `outro`, essa categoria não terá validação funcional real neste
  conjunto. Casos simulados podem testar software, sem ampliar a acurácia reportada.

## Código existente e reutilização

| Componente | Evidência no repositório | Decisão |
| --- | --- | --- |
| API | `src/websensors_flow_rag/api.py` | Estender a mesma factory FastAPI, autenticação e respostas |
| Execução assíncrona | `ThreadPoolExecutor`, `JobStore`, `JobStatusObserver`, locks por documento | Extrair a orquestração para serviço comum; não adicionar fila |
| Flow | `src/websensors_flow/runner.py`, contexto, eventos e observers | Chamar `run_configured_flow`; métricas via `StepResult` e contexto |
| Docling | `clients/docling_client.py` | Reutilizar conversão async, polling e normalização existentes |
| Bronze/Silver | `clients/minio_client.py` | Upload binário já existe; persistir original antes de enfileirar |
| Embeddings | `clients/model_client.py` | Preservar `EmbeddingClient` e configurações atuais |
| Elasticsearch | `clients/elasticsearch_client.py` | Manter índices/aliases de documentos e chunks; mappings atuais têm `dynamic: false` |
| Revisões/hash | `indexing/steps.py`, `utils.py` | Preservar detecção de alterações, no-op, atualização só de metadados e publicação |
| CLI | `cli.py`, scripts em `pyproject.toml` | Acrescentar processamento de arquivo; CLI atual recebe objeto já no Bronze |
| OpenWebUI | `resources/08_openwebui.md`, `docs/tutorial_openapi.md` | Hoje só documenta importação OpenAPI; criar adaptador de anexos |
| Testes | `tests/` | Reutilizar regressões de Docling, chunking, índices, API e busca |

### Os nove steps atuais

1. `ResolveSourceStep`: lê bytes do Bronze e calcula SHA-256/identidade da fonte.
2. `DetectChangesStep`: consulta documento existente, compara fonte e pipeline,
   decide no-op, atualização de metadados ou revisão nova.
3. `ConvertDoclingStep`: uma chamada de conversão produz Markdown e JSON;
   registra modelo/preset e progresso pelo contexto.
4. `StoreSilverStep`: grava Markdown, JSON e manifesto por documento/revisão.
5. `ChunkDocumentStep`: segmenta Markdown e associa páginas do JSON estrutural.
6. `GenerateEmbeddingsStep`: usa cliente e modelo existentes em lotes.
7. `StageElasticsearchStep`: prepara chunks inativos com IDs determinísticos;
   trata retomada de revisão e limpeza do staging.
8. `ValidateRevisionStep`: confere contagem de chunks da revisão preparada.
9. `PublishRevisionStep`: ativa revisão, verifica consistência e publica documento;
   também finaliza no-op e atualização só de metadados.

Não há hoje classificação, extração semântica, índices estruturados ou upload
multipart pela API. O hash atual inclui versão, opções Docling, chunking e
modelo/dimensões/caminho dos embeddings, sem prompts ou modelo de chat.

## Arquitetura proposta

```text
OpenWebUI Tool ── multipart ── API existente ─┐
CLI Python ─────────────────────────────────┤
                                           v
                              ProcessDocumentService
                               upload original Bronze
                               normalizar projeto/entrada
                               executar WebSensors-Flow
                                           |
 resolver fonte → detectar alterações → Docling/reuso verificado
                                           |
                           classificar → extrair/validar
                                           |
 Silver: MD + JSON Docling + classificação + extração + manifesto
                                           |
              chunks → embeddings atuais → staging textual/estruturado
                                           |
                       validar → publicar revisão → resultado
```

- O serviço comum terá upload/preparação, execução e recuperação de resultado.
  A API mantém execução assíncrona com o executor/store existentes. A CLI pode
  aguardar execução síncrona do mesmo núcleo sem depender de uma segunda API.
- Expor `POST /api/v1/documents/process` com multipart (`file`, `project`,
  `metadata` JSON e tipo opcional), status 202 e consulta em
  `GET /api/v1/jobs/{job_id}`. Manter contratos atuais de indexação e busca.
- Acrescentar `__main__.py` para `python -m websensors_flow_rag process --file ...
  --project fai --config ... --output json`, com opção de arquivo de saída.
  Logs/progresso no stderr para stdout JSON utilizável.
- Projetos de documentos são distintos de `settings.project.name`, hoje fixo em
  `websensors-flow-rag`. Não substituir esse identificador de serviço por `fai`.
- Usar chave Bronze estável por projeto/documento e conteúdo imutável ou versionado
  para impedir troca da fonte entre upload e leitura. Validar nomes e caminhos;
  conservar nome original como metadado, sem aceitar caminhos arbitrários.
- Artefatos Docling opcionais precisam de Markdown + JSON, hash da fonte e
  identidade das opções/conversor. Sem evidência de correspondência, converter
  uma vez com o cliente existente. Texto do contexto do chat não substitui o original.
- Reutilizar Silver para fonte/opções idênticas quando houver artefatos válidos;
  mudar apenas prompt/modelo deve criar nova revisão sem conversão desnecessária.
- Ativar processamento especializado por configuração/projeto. Sem ativação,
  manter comportamento atual e preservar hashes legados quando aplicável.

### Integração OpenWebUI e conversão única

A documentação de argumentos reservados descreve `__files__` como referências
a anexos, sem os bytes embutidos. A ferramenta obterá o ID do anexo e buscará
o original pela API autenticada de arquivos. O código upstream oferece rota
`/{id}/content` que entrega o arquivo, distinta de `/{id}/data/content`, que
entrega texto extraído. Na release `v0.11.0`, a factory monta o router em `/api/v1/files`, resultando
em `GET /api/v1/files/{id}/content`. A instalação informou essa versão; conferir
o fluxo autenticado e eventuais modificações locais antes da integração. Não usar caminhos enviados pelo modelo ou
credencial administrativa global para contornar acesso ao arquivo.

Fontes consultadas em 11/11/2026:
- [Argumentos reservados do OpenWebUI](https://docs.openwebui.com/features/extensibility/plugin/development/reserved-args/).
- [Router de arquivos da release v0.11.0](https://github.com/open-webui/open-webui/blob/v0.11.0/backend/open_webui/routers/files.py).

- [Prefixo do router na release v0.11.0](https://github.com/open-webui/open-webui/blob/v0.11.0/backend/open_webui/main.py).

O código da release corresponde à versão reportada pela instalação. Ainda não
foi demonstrado o download de um anexo real com autenticação ou o reuso dos
artefatos Docling. Não inferir a configuração de extração a partir da versão.
O adaptador deve emitir progresso, enviar o original à API RAG, consultar o job e
retornar classificação, justificativa, revisão, JSON, avisos e IDs.

O OpenWebUI pode já converter anexos no upload. Antes da demonstração, verificar
se expõe os dois artefatos Docling e sua proveniência; reutilizá-los quando houver.
Se não expuser, evitar a extração automática redundante nesse fluxo e delegar a
conversão ao RAG, conforme mecanismo suportado pela versão instalada. Não assumir
que uma flag da Tool desativa processamento que já ocorreu no upload. A condição
de uma conversão precisa ser demonstrada com contagem de chamadas Docling.

### LLM, configuração e schemas

Criar cliente HTTP OpenAI-compatible de chat usando `httpx` já existente.
Configurar endpoint, modelo, timeout, temperatura, tokens, formato de resposta e
limites de tentativas. Chave OpenRouter vem do ambiente/`.env`; chave da API RAG
ou OpenWebUI é independente. O loader YAML atual não expande variáveis nem lê
`.env`; adicionar suporte explícito, com `.env.example` sem segredos.

Categorias e recursos vivem em `projects/fai/`, com registro configurável,
prompt de classificação e `document_types/<tipo>/{prompt.md,schema.json,mapping.json}`.
Não codificar as categorias em Python. Criar os oito tipos do plano; `outro`
não recebe schema especializado. Um registro declara schema/prompt/mapping/index
por tipo e suas versões/hashes.

Usar JSON Schema para validação, adicionando dependência de validação compatível.
Schemas têm propriedades explícitas, campos ausentes null/listas vazias e
`additionalProperties: false`. O manifesto de validação propõe os campos por
categoria; congelar valores esperados em referência local antes da avaliação.
Edital terá órgão/processo, objeto, requisitos, documentos exigidos, prazos,
vagas, carga horária e critérios. Cada extração inclui fontes por campo
(página/trecho), avisos e versão. Evidências vêm do próprio documento.

Classificação usa conteúdo, nome apenas como contexto, enum do projeto e saída
validada (`document_type`, `reason`, `needs_review`). Não aceitar categoria
inexistente ou JSON inválido como sucesso. Tipo informado pelo usuário será
registrado como decisão explícita, distinto da predição na avaliação.

Extração seleciona recursos pela classificação validada. Permitir uma correção
de resposta inválida, separada dos retries de transporte. Limites de contexto
são verificados antes do envio; inicialmente, interromper explicitamente a
extração e pedir revisão se excedidos, preservando texto e sem declarar extração
completa. Não cortar conteúdo silenciosamente. Tratar o conteúdo do documento
como dados, sem executar instruções nele encontradas.

### Persistência, publicação e observabilidade

Adicionar classificação e extração ao `WorkItem`, com avisos, versões e modelo.
`StoreSilverStep` passa a guardar os cinco artefatos e seus hashes/referências no
manifesto por revisão, com data UTC. Em `outro`, registrar extração não aplicável,
sem fabricar JSON de outra categoria.

Índices estruturados têm mapping explícito e IDs `document_id:revision_id`.
Staging estruturado é inativo; validar JSON e presença da revisão antes de
publicar. Na troca de tipo, desativar o registro antigo no índice da categoria
anterior. Atualização só de metadados e no-op também devem retornar classificação
e extração persistidas, sem repetir chamadas LLM.

Elasticsearch não oferece transação entre esses índices. Ampliar o protocolo
atual com validações, compensação/restauração da revisão anterior e testes de
falha parcial. Nunca declarar publicação concluída com divergência conhecida
entre revisão textual e estruturada. Verificar existência e contagens no retry.

O novo hash inclui projeto documental, categorias, modelo/endpoint sem segredos,
parâmetros de classificação/extração e conteúdo/hash dos prompts/schemas/mappings.
Mudanças devem invalidar a revisão mesmo com bytes da fonte iguais.

Métricas de classificação/extração, tentativas, validade JSON, contagem de campos,
bytes e duração passam por `StepResult`/eventos; modelo via
`context.register_model`. O observer MLflow já escuta esses eventos. Não inserir
texto integral, JSON com dados pessoais ou chave de API em parâmetros/métricas.
Revisar também mensagens de erro, tracing e artefatos de eventos para evitar
vazamento incidental dos novos payloads.

O `JobStore` é em memória: jobs não sobrevivem ao reinício, e o deployment atual
usa um processo. Documentar essa limitação; não criar Redis/Celery. Os resultados
persistidos em Silver/Elasticsearch continuam recuperáveis por documento/revisão.

## Arquivos previstos para as próximas fases

Modificar:
- `src/websensors_flow_rag/api.py`, `cli.py`, `config.py`, `models.py`, `utils.py`.
- `src/websensors_flow_rag/indexing/steps.py`.
- `src/websensors_flow_rag/clients/elasticsearch_client.py`.
- `config/rag.yaml`, `pyproject.toml`, README e documentação solicitada.
- Testes existentes apenas onde contratos e extensões exigirem.

Adicionar:
- `src/websensors_flow_rag/services/process_document.py`.
- `src/websensors_flow_rag/clients/llm_client.py`.
- Módulos de registro de projetos, recursos/validação e steps especializados.
- `src/websensors_flow_rag/__main__.py`.
- `integrations/openwebui/` com Tool importável e configuração documentada.
- `projects/fai/` com registro, classificação e recursos dos oito tipos.
- `.env.example`, testes unitários/integrados e runner/relatório de aceitação.

## Plano de testes e aprovação

1. Unitários com mocks: cliente LLM (HTTP/timeout/retries/JSON), categorias e
   `outro`, seleção e validação de schemas, campos ausentes, contexto excedido,
   limite de uma correção, proveniência de artefatos e ausência de vazamento.
2. Serviço/API/CLI: Bronze antes do pipeline; mesma requisição normalizada;
   resposta JSON/arquivo; erros de upload, projeto e metadados; anexos com
   acesso autorizado e negado; polling e limites de tempo.
3. Persistência/revisões: staging e publicação textual/estruturada, troca de
   categoria, falha parcial, idempotência, no-op, metadados e mudança de prompts,
   schemas/modelo; contagem de conversões e reuso verificado.
4. Regressões: suíte atual, principalmente BM25, semântica, híbrida, chunking,
   embeddings, mappings, Docling e contratos de indexação.
5. Integração real: usar os serviços existentes e a versão real do OpenWebUI;
   comprovar Bronze, uma conversão, Silver, índices e observer MLflow. Comparar
   CLI e chat com mesma configuração e hashes; não usar mocks nesse aceite.
6. Aceitação: validar hash dos oito originais; classificar sem fornecer rótulo;
   exigir 8/8 acertos exatos; registrar matriz de confusão, por categoria, erros,
   revisões e versões. Qualquer falha impede aprovação funcional.
7. Extração: validar schema e comparar campos-chave com referência humana
   congelada antes da execução; verificar campos ausentes, valores mascarados,
   páginas de origem e ausência de complementação entre documentos.

O conjunto é pequeno e será inteiramente teste de aceitação, com uso no ajuste
de prompts declarado. Não afirmar generalização ou acurácia nas categorias sem
exemplos. Nenhuma acurácia foi medida nesta fase.

## Verificações e pendências

Realizado: inventário do ZIP, SHA-256 dos originais, leitura do texto, diagnóstico
visual, confirmação dos rótulos, análise dos nove steps e clientes/observadores,
consulta do código oficial da release 0.11.0, acesso aos endpoints públicos do
OpenWebUI e sondagem limitada dos hosts. Cinco valores do edital foram conferidos
manualmente e registrados no manifesto; as demais referências de extração seguem
pendentes de congelamento.

Não executado: testes Python (o interpretador disponível não tem pytest e parte
das dependências do projeto), pipeline real, OCR Docling, chamadas OpenRouter,
integração chat/CLI, acurácia e extração. Não instalar/subir infraestrutura nova.

Para concluir a verificação do ambiente na Fase A e a integração posterior,
precisamos de acesso à configuração real dos serviços e ao modelo/endpoint de
chat efetivamente utilizados. O endereço e a versão do OpenWebUI estão confirmados. Credenciais
devem ser configuradas no ambiente local, sem serem publicadas no relatório.
