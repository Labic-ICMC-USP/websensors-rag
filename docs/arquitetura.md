# Arquitetura

## Visão geral

```text
Entrada documental
       |
       v
MinIO Bronze
       |
       v
WebSensors Flow RAG
       |
       v
Docling Serve
       |
       +--> Markdown
       +--> JSON
       |
       v
MinIO Silver
       |
       v
Chunking estrutural
       |
       v
Embeddings
       |
       v
Elasticsearch
       |
       +--> BM25
       +--> kNN
       +--> RRF
```

## MinIO Bronze

O bucket Bronze mantém o arquivo original. A chave do objeto pode ser usada diretamente pela API de indexação.

## Docling

Todo processamento documental passa pelo Docling. O mesmo serviço recebe PDF, imagem e demais formatos suportados pela configuração.

O resultado principal contém Markdown e JSON.

O Markdown é a representação textual canônica para chunking e indexação.

O JSON preserva estrutura documental e metadados derivados.

## MinIO Silver

Cada revisão possui uma pasta própria.

```text
documentos/
  DOCUMENT_ID/
    REVISION_ID/
      document.md
      document.json
      manifest.json
```

## Elasticsearch

O índice de documentos armazena uma entrada por documento lógico.

O índice de chunks armazena passagens pesquisáveis e seus vetores.

As buscas usam aliases para desacoplar a aplicação dos nomes físicos dos índices.

## Revisões

Uma nova revisão é criada quando muda o arquivo de origem, a configuração de processamento ou quando a reindexação é forçada.

Os novos chunks são gravados como inativos. A publicação ocorre somente depois da validação da revisão.

## Recuperação

BM25 executa a recuperação lexical.

kNN utiliza o vetor da consulta para recuperar chunks semanticamente próximos.

RRF combina os dois rankings usando a posição dos candidatos.

A busca híbrida executa BM25 e kNN no Elasticsearch e combina os dois rankings por RRF na aplicação.
