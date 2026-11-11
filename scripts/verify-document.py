"""Confere um documento persistido, sem inferência, conversão ou alteração de dados."""
from __future__ import annotations

import argparse
import hashlib
import json
from urllib.parse import urlparse

from websensors_flow_rag.clients.elasticsearch_client import ElasticsearchClient
from websensors_flow_rag.clients.minio_client import MinIOClient
from websensors_flow_rag.config import load_rag_settings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', default='config/rag.local.yaml')
    parser.add_argument('--document-id', required=True)
    args = parser.parse_args()
    settings = load_rag_settings(args.config)
    es = ElasticsearchClient(settings.services.elasticsearch, settings.services.embeddings.dimensions)
    minio = MinIOClient(settings.services.minio)
    blobs = {}

    def read(bucket, key):
        if (bucket, key) not in blobs:
            blobs[bucket, key] = minio.get_bytes(bucket, key)
        return blobs[bucket, key]

    try:
        document = es.get_document(args.document_id)
        if not document:
            raise SystemExit('Documento não encontrado.')
        source, silver = document['source'], document['silver']
        original = read(source['bucket'], source['key'])
        source_ok = hashlib.sha256(original).hexdigest() == source['sha256']
        artifacts, manifest = {}, {}
        for name, uri in silver.items():
            parsed = urlparse(uri)
            if parsed.scheme != 's3':
                raise SystemExit('Referência Silver inválida.')
            data = read(parsed.netloc, parsed.path.lstrip('/'))
            artifacts[name] = {'uri': uri, 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
            if name == 'manifest':
                manifest = json.loads(data)
        checks = []
        for name, reference in manifest.get('artifacts', {}).items():
            checks.append(name in artifacts and artifacts[name]['sha256'] == reference['sha256'])
        silver_hashes_ok = bool(checks) and len(checks) == len(artifacts) - 1 and all(checks)
        filters = [{'term': {'document_id': args.document_id}}, {'term': {'revision_id': document['active_revision']}}, {'term': {'active': True}}]
        alias = settings.services.elasticsearch.aliases.chunks

        def count(extra=(), excluded=()):
            body = {'query': {'bool': {'filter': filters + list(extra), 'must_not': list(excluded)}}}
            response = es.client.post(f'/{alias}/_count', json=body)
            response.raise_for_status()
            return response.json()['count']

        chunks = count()
        with_vectors = count([{'exists': {'field': 'embedding'}}])
        empty_text = count(excluded=[{'exists': {'field': 'content'}}])
        response = es.client.post(f'/{alias}/_search', json={
            'size': 1, '_source': ['chunk_id', 'content'], 'query': {'bool': {'filter': filters}},
            'script_fields': {
                'embedding_dims': {'script': {'source': "doc['embedding'].vectorValue.length"}},
                'embedding_sample': {'script': {'source': "def v = doc['embedding'].vectorValue; return [v[0], v[1], v[2], v[3]];"}},
            },
        })
        response.raise_for_status()
        hits = response.json()['hits']['hits']
        sample = hits[0] if hits else {}
        fields = sample.get('fields', {})
        dimensions = fields.get('embedding_dims', [None])[0]
        report = {
            'document_id': args.document_id, 'revision_id': document['active_revision'],
            'bronze': {'uri': f"s3://{source['bucket']}/{source['key']}", 'bytes': len(original), 'sha256_matches_source': source_ok},
            'silver': artifacts, 'silver_hashes_match_manifest': silver_hashes_ok,
            'classification': (document.get('classification') or {}).get('document_type'),
            'extraction_status': (document.get('extraction') or {}).get('status'),
            'elasticsearch': {'active_chunks': chunks, 'active_chunks_with_embedding': with_vectors,
                'chunks_missing_content': empty_text, 'embedding_dimensions_sample': dimensions,
                'embedding_first_four_values': fields.get('embedding_sample', []),
                'sample_chunk_text_characters': len(sample.get('_source', {}).get('content', ''))},
            'configured_embedding_model': settings.services.embeddings.model,
        }
        report['ok'] = source_ok and silver_hashes_ok and chunks > 0 and chunks == with_vectors and empty_text == 0 and dimensions == settings.services.embeddings.dimensions
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report['ok'] else 1
    finally:
        es.close()


if __name__ == '__main__':
    raise SystemExit(main())
