# WebSensors Flow RAG

O serviço organiza uma pipeline de ingestão documental e três modalidades de recuperação no Elasticsearch.

A indexação recebe objetos armazenados no MinIO. O Docling produz Markdown e JSON estrutural. O Markdown alimenta o chunking e a recuperação textual. O JSON preserva informações estruturais úteis para páginas, tabelas, figuras e proveniência.

A recuperação pode ser lexical com BM25, semântica com kNN ou híbrida com BM25 e kNN combinados por RRF na aplicação.

## Caminho recomendado

1. Configurar os serviços em `config/rag.local.yaml`
2. Validar a infraestrutura com `websensors-flow-rag-health`
3. Iniciar a API com `websensors-flow-rag-api`
4. Indexar documentos existentes no bucket Bronze
5. Acompanhar a execução em `/indexing/{token}`
6. Consultar BM25, semântica e híbrida
7. Avaliar os rankings com consultas representativas do domínio

## Tutoriais

A documentação contém tutoriais independentes para indexação, BM25, busca semântica, busca híbrida, observabilidade e uso via Jupyter Notebook.
