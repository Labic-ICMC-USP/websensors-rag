# Tutorial Jupyter

O notebook assume que a API, o MinIO, o Elasticsearch, o Docling e o serviço de embeddings já estão em execução.

Não há etapas de instalação ou inicialização de infraestrutura dentro do notebook.

## Arquivo

```text
notebooks/tutorial_completo.ipynb
```

## Sequência didática

O notebook segue esta ordem.

1. Configurar os endereços de acesso
2. Criar documentos de exemplo
3. Enviar os arquivos ao MinIO Bronze
4. Solicitar a indexação
5. Acompanhar os tokens até a conclusão
6. Consultar o catálogo de documentos
7. Inspecionar Markdown e JSON no MinIO Silver
8. Executar busca BM25
9. Executar busca semântica
10. Executar busca híbrida com RRF
11. Comparar os rankings
12. Aplicar filtros por metadados
13. Atualizar metadados
14. Atualizar conteúdo
15. Indexar PDF e imagem
16. Avaliar MRR e nDCG em um exemplo didático

## Dependências do notebook

```bash
pip install -e '.[notebook]'
```

Depois abra o arquivo com JupyterLab ou outro ambiente compatível com notebooks.
