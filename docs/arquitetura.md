# Arquitetura

O WebSensors-RAG recebe documentos por três entradas (OpenWebUI, API e CLI) e
processa todos com **o mesmo pipeline**. O resultado é o tipo do documento, os
dados extraídos em JSON e o texto pronto para busca.

## 1. Visão geral

```mermaid
flowchart LR
    E[OpenWebUI · API · CLI] --> P[[Pipeline do WebSensors-RAG]]
    P <--> D[Docling<br/>PDF para texto]
    P <--> L[Gemini e Qwen<br/>via OpenRouter]
    P --> M[(MinIO<br/>arquivos)]
    P --> ES[(Elasticsearch<br/>busca e dados)]
    P -.-> ML[MLflow<br/>monitoramento]
```

| Componente | Papel |
| --- | --- |
| **Docling** (local) | Converte o PDF em texto (Markdown) e estrutura (JSON), inclusive com OCR. |
| **Gemini** (OpenRouter) | Classifica o tipo do documento e extrai os dados. |
| **Qwen Embedding** (OpenRouter) | Gera os vetores usados na busca semântica. |
| **MinIO** | Guarda o PDF original (Bronze) e os resultados (Silver). |
| **Elasticsearch** | Guarda os trechos para busca e os dados extraídos por tipo. |
| **MLflow** | Registra cada execução: etapas, tempos e métricas. |

## 2. Fluxo pelo OpenWebUI

O uso pelo chat acontece em **dois momentos**:

```mermaid
flowchart LR
    subgraph P1["① Ao anexar o PDF"]
        direction TB
        A1([Usuário anexa o PDF]) --> A2[API RAG guarda o original<br/>no Bronze]
        A2 --> A3[Docling converte<br/>uma única vez]
        A3 --> A4[(Conversão guardada<br/>em cache no Silver)]
        A3 --> A5[Texto vai para o chat]
    end

    subgraph P2["② Ao pedir o processamento"]
        direction TB
        B1([Usuário pede no chat]) --> B2[Tool envia o PDF original<br/>para a API RAG]
        B2 --> B3[Pipeline reaproveita a conversão,<br/>classifica e extrai com o Gemini]
        B3 --> B4[(Resultados no Silver<br/>e no Elasticsearch)]
        B3 --> B5[Resultado aparece no chat]
    end

    A4 -. reaproveitado .-> B3
```

1. **Ao anexar:** o OpenWebUI envia o PDF para a nossa API, que guarda o original e
   faz a conversão com o Docling. O resultado fica em cache e o texto vai para o chat.
2. **Ao pedir o processamento:** a Tool busca o PDF original e o envia para a API.
   O pipeline usa a conversão já feita (o Docling não roda de novo), classifica o
   documento, extrai os dados, salva tudo e devolve o resultado ao chat.

Pela **CLI** só existe o segundo momento: o comando envia o arquivo direto ao mesmo
pipeline e, se não houver cache, converte uma vez.

## 3. O pipeline

```mermaid
flowchart LR
    A[1. Ler o original] --> B{2. Mudou algo?}
    B -->|não| Z([Devolve o resultado já salvo])
    B -->|sim| C[3. Converter<br/>Docling ou cache]
    C --> D[4. Classificar<br/>tipo do documento]
    D --> E[5. Extrair dados<br/>com o schema do tipo]
    E --> F[6. Salvar no Silver]
    F --> G[7. Preparar busca<br/>trechos + vetores]
    G --> H[8. Validar e publicar]
```

- **Mudou algo?** Compara o arquivo e a configuração (modelos, prompts, schemas)
  com o que já foi processado. Se nada mudou, não chama o Docling nem o Gemini.
- **Classificar:** o Gemini escolhe uma das categorias do projeto (edital, ficha
  de inscrição, CNH...). Se não reconhecer, usa `outro` e não faz extração.
- **Extrair:** cada tipo tem seu prompt e seu schema. Todo valor precisa de um
  trecho do documento como evidência; o modelo não pode inventar dados.
- **Validar e publicar:** a versão nova só passa a valer depois de conferida. Se
  algo falhar no meio, a versão anterior continua valendo.

No código, essas 8 etapas correspondem a 12 steps do WebSensors-Flow.

## 4. Onde os dados ficam

```mermaid
flowchart LR
    PDF[PDF enviado] --> BR[(MinIO Bronze<br/>original)]
    BR --> SI[(MinIO Silver<br/>texto, JSON, tipo,<br/>dados extraídos)]
    SI --> T[(Elasticsearch<br/>trechos para busca)]
    SI --> X[(Elasticsearch<br/>dados por tipo)]
```

| Local | Conteúdo |
| --- | --- |
| `rag-bronze` | O PDF original, exatamente como foi enviado. |
| `rag-silver` | Por versão do documento: `document.md`, `document.json`, `classification.json`, `extraction.json` e `manifest.json`; além do cache da conversão do Docling. |
| `websensors-rag-chunks` | Trechos do texto com vetores, usados nas buscas BM25, semântica e híbrida. |
| `websensors-rag-documents` | Uma ficha por documento, apontando para a versão ativa. |
| `rag-estruturado-fai-<tipo>` | Os dados extraídos, um índice por tipo de documento (ex.: `rag-estruturado-fai-edital`). |

## 5. Versões do documento

Cada processamento que muda algo cria uma **nova versão** (revisão). Ela é
montada desativada e só é ativada depois de validada; nesse momento a versão
anterior é desativada. Se houver erro na troca, o sistema volta para a versão
anterior. Assim, a busca e os dados por tipo nunca ficam pela metade.

Mudar o arquivo, o modelo, um prompt ou um schema gera nova versão. A conversão
do Docling é reaproveitada sempre que o PDF é o mesmo.

## 6. Monitoramento

Cada execução aparece no MLflow (experimento `websensors-flow-rag`) com o tempo de
cada etapa, os modelos usados e métricas como acerto do JSON, número de campos
extraídos e conversões do Docling. Textos dos documentos, dados pessoais e chaves
não são gravados no MLflow.

## 7. Onde fica cada coisa no código

| Responsabilidade | Local |
| --- | --- |
| API (rotas HTTP) | `src/websensors_flow_rag/api.py` |
| Serviço comum (API e CLI) | `src/websensors_flow_rag/services/process_document.py` |
| Etapas do pipeline | `src/websensors_flow_rag/indexing/`, `classification/`, `extraction/`, `structured/` |
| Categorias, prompts e schemas | `projects/<projeto>/` ([como adicionar um tipo](novos_tipos_documentais.md)) |
| Tool do OpenWebUI | `integrations/openwebui/process_document_tool.py` |

Mais detalhes: [classificação](../resources/11_classificacao.md),
[extração](../resources/12_extracao.md) e
[índices por tipo](../resources/13_indices_estruturados.md).
