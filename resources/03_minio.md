# MinIO

O MinIO armazena os arquivos originais e as representações derivadas.

Buckets padrão:

```text
rag-bronze
rag-silver
```

## Usar uma implantação existente

O endpoint precisa expor a API S3 e permitir leitura no Bronze e leitura e escrita no Silver.

```yaml
services:
  minio:
    endpoint: "http://minio:9000"
    access_key: "rag"
    secret_key: "ALTERE_AQUI"
    secure: false
    region: null
    bronze_bucket: rag-bronze
    silver_bucket: rag-silver
    silver_prefix: documentos
```

## MinIO AIStor em contêiner

A implantação atual do MinIO AIStor utiliza licença. Existe modalidade gratuita disponibilizada pelo fornecedor.

Prepare diretórios e o arquivo de licença:

```bash
mkdir -p $HOME/minio/data $HOME/minio/certs
```

Salve a licença em:

```text
$HOME/minio/minio.license
```

Execute:

```bash
docker run -dt \
  -p 9000:9000 \
  -p 9001:9001 \
  -v $HOME/minio/data:/mnt/data \
  -v $HOME/minio/minio.license:/minio.license \
  -v $HOME/minio/certs:/etc/minio/certs \
  --name aistor-server \
  quay.io/minio/aistor/minio:latest \
  minio server /mnt/data --license /minio.license
```

Console:

```text
http://localhost:9001
```


## MinIO Community

A edição comunitária do MinIO é distribuída atualmente como código fonte. Para uma implantação comunitária atualizada, compile a partir do repositório oficial ou construa a imagem Docker a partir do código fonte. Os binários comunitários históricos continuam disponíveis, mas não recebem manutenção.

Para o `websensors-flow-rag`, qualquer implantação MinIO ou armazenamento S3 compatível funciona desde que ofereça as operações utilizadas pelo cliente e as credenciais tenham acesso aos buckets configurados.

## Cliente mc

Depois de instalar `mc`:

```bash
mc alias set rag http://localhost:9000 USUARIO SENHA
```

Crie os buckets:

```bash
mc mb rag/rag-bronze
mc mb rag/rag-silver
```

Se eles já existirem, apenas valide:

```bash
mc stat rag/rag-bronze
mc stat rag/rag-silver
```

## Teste

```bash
echo 'teste' > /tmp/websensors-rag.txt
mc cp /tmp/websensors-rag.txt rag/rag-bronze/teste/websensors-rag.txt
mc stat rag/rag-bronze/teste/websensors-rag.txt
```

## Organização

```text
rag-bronze/
    documentos/
        relatorio.pdf

rag-silver/
    documentos/
        <document_id>/
            <revision_id>/
                document.md
                document.json
                manifest.json
```

Referência oficial:

```text
https://docs.min.io/aistor/installation/container/install/
https://github.com/minio/minio
```
