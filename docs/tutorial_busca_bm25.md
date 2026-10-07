# Tutorial de busca BM25

BM25 é a modalidade lexical.

Ela funciona melhor quando a consulta contém termos que aparecem explicitamente nos documentos, como siglas, códigos, nomes próprios e expressões técnicas.

## Consulta básica

```bash
curl -X POST http://localhost:8000/search/bm25 \
  -H 'Content-Type: application/json' \
  -d '{
    "query": "RPM sensores temperatura",
    "top_k": 5
  }'
```

## Campos pesquisados

A configuração padrão usa os seguintes pesos.

```yaml
search:
  lexical:
    fields:
      - title^3
      - heading_text^2.5
      - section^2
      - content
```

O título recebe maior peso.

A hierarquia de títulos e a seção também influenciam o ranking.

O corpo do chunk completa a evidência lexical.

## Busca com filtro

```bash
curl -X POST http://localhost:8000/search/bm25 \
  -H 'Content-Type: application/json' \
  -d '{
    "query": "compensação térmica",
    "top_k": 10,
    "filters": {
      "empresa": "ROMI",
      "ano": 2026
    }
  }'
```

Chaves desconhecidas são interpretadas como campos de `metadata`.

## Quando usar BM25

BM25 é uma boa escolha para buscas por identificadores, palavras raras, nomes de equipamentos, referências normativas e termos que precisam aparecer literalmente.

## Limitação principal

BM25 não entende paráfrases da mesma forma que um modelo de embeddings.

Uma consulta semanticamente equivalente pode ter baixa recuperação quando usa palavras muito diferentes das presentes no texto.
