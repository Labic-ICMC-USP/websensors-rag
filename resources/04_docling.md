# Docling Serve

O Docling centraliza o processamento documental. PDFs, imagens e demais formatos suportados seguem pela mesma API. O `websensors-flow-rag` solicita Markdown e JSON para cada conversão.

## Contêiner CPU

```bash
docker run -d \
  --name docling \
  --network websensors-rag \
  -p 5001:5001 \
  -e DOCLING_SERVE_ENABLE_UI=1 \
  quay.io/docling-project/docling-serve
```

## Instalação Python

```bash
python -m venv .venv-docling
source .venv-docling/bin/activate
pip install 'docling-serve[ui]'
docling-serve run --enable-ui
```

## Endpoints

```text
API       http://localhost:5001
Swagger   http://localhost:5001/docs
UI        http://localhost:5001/ui
Health    http://localhost:5001/health
Readiness http://localhost:5001/ready
```

Valide disponibilidade:

```bash
curl -i http://localhost:5001/health
curl -i http://localhost:5001/ready
```

`/ready` pode responder 503 enquanto modelos ainda estão carregando.

O endpoint `/version` pode ser desabilitado pelo administrador e não deve ser usado como readiness probe.

## Capacidades

Quando habilitado:

```bash
curl http://localhost:5001/v1/capabilities | python -m json.tool
```

Use esse endpoint para confirmar presets de OCR, descrição de imagens, formatos de entrada e formatos de saída aceitos pelo deployment.

## Conversão de arquivo

O pacote utiliza:

```text
POST /v1/convert/file/async
GET  /v1/status/poll/{task_id}
GET  /v1/result/{task_id}
```

As saídas esperadas são `md` e `json`.

## Configuração do RAG

```yaml
services:
  docling:
    endpoint: "http://docling:5001"
    api_key: null
    timeout_seconds: 600
    poll_interval_seconds: 1
    options:
      from_formats:
        - pdf
        - image
        - docx
        - pptx
        - html
        - md
        - xlsx
      image_export_mode: placeholder
      do_ocr: true
      force_ocr: false
      pdf_backend: dlparse_v4
      table_mode: accurate
      ocr_preset: rapidocr
      pipeline: standard
      abort_on_error: false
      do_table_structure: true
      do_picture_description: true
      picture_description_preset: labic_vision
      do_picture_classification: true
```

`ocr_preset` seleciona o preset de OCR utilizado pelo Docling.

## Descrição de imagens

O RAG informa somente o nome do preset:

```yaml
picture_description_preset: labic_vision
```

O preset é administrado no Docling Serve. Quando ele usa um serviço remoto, habilite conexões remotas:

```text
DOCLING_SERVE_ENABLE_REMOTE_SERVICES=true
```

Controles disponíveis no Docling Serve:

```text
DOCLING_SERVE_DEFAULT_PICTURE_DESCRIPTION_PRESET
DOCLING_SERVE_ALLOWED_PICTURE_DESCRIPTION_PRESETS
DOCLING_SERVE_CUSTOM_PICTURE_DESCRIPTION_PRESETS
DOCLING_SERVE_ALLOWED_PICTURE_DESCRIPTION_ENGINES
DOCLING_SERVE_ALLOW_CUSTOM_PICTURE_DESCRIPTION_CONFIG
```

Para configurações complexas, use um arquivo de configuração do Docling Serve:

```text
DOCLING_SERVE_CONFIG_FILE=/caminho/config.yaml
```

Depois do restart, confirme o preset em `/v1/capabilities`.

## VLM remoto

O VLM pode ser hospedado por vLLM ou acessado por um gateway como LiteLLM. O endereço, cabeçalhos, modelo e parâmetros pertencem ao preset do Docling.

Exemplo de endpoint OpenAI compatível:

```text
http://vlm:8101/v1/chat/completions
```

A configuração do VLM fica integralmente no Docling Serve.

## Teste com imagem

Coloque uma imagem no MinIO e indexe pelo RAG ou faça uma conversão direta pelo Docling. Depois confirme a presença da descrição no Markdown ou no JSON retornado.

Referências oficiais:

```text
https://docling.org/install/docker/
https://github.com/docling-project/docling-serve/blob/main/docs/usage.md
https://github.com/docling-project/docling-serve/blob/main/docs/configuration.md
```
