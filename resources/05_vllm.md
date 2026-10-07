# vLLM

O vLLM pode disponibilizar modelos usados pelo Docling ou pelo serviço de embeddings.

O `websensors-flow-rag` não chama um VLM diretamente.

## VLM usado pelo Docling

O Docling pode apontar seu preset de descrição de imagens para um endpoint compatível com OpenAI.

A configuração desse endpoint pertence ao Docling.

No YAML do RAG aparece apenas o preset selecionado.

```yaml
services:
  docling:
    options:
      do_picture_description: true
      picture_description_preset: labic_vision
```

## Embeddings

Quando o backend de embeddings oferece contrato compatível com OpenAI, o RAG pode apontar diretamente para ele ou para um gateway LiteLLM.

Exemplo de configuração do RAG.

```yaml
services:
  embeddings:
    endpoint: "http://localhost:4000/v1"
    path: /embeddings
    model: inpi-text-embedding
    dimensions: 1024
```

## Validação

Consulte o catálogo do endpoint e execute uma inferência antes de iniciar o RAG.
