from __future__ import annotations

import json
from time import perf_counter

from websensors_flow import PipelineStep, StepResult
from websensors_flow_rag.clients.llm_client import LLMClient
from websensors_flow_rag.extraction.service import extract_structured_data
from websensors_flow_rag.utils import classification_projects_dir, load_context_settings


def page_furniture_text(docling_json: dict) -> str:
    """Cabeçalhos e rodapés que a exportação Markdown do Docling omite (camada furniture).

    Rodapés costumam conter códigos de autenticidade, validades e emissores; sem eles
    a extração perderia conteúdo silenciosamente.
    """
    lines: list[str] = []
    for item in docling_json.get('texts', []) if isinstance(docling_json, dict) else []:
        text = (item.get('text') or '').strip()
        if item.get('content_layer') == 'furniture' and item.get('label') in {'page_header', 'page_footer'} and text and text not in lines:
            lines.append(text)
    return '\n'.join(lines)


def extraction_input(work, settings) -> str:
    if not settings.extraction.include_page_furniture:
        return work.markdown
    furniture = page_furniture_text(work.docling_json)
    if not furniture:
        return work.markdown
    return f"{work.markdown.rstrip()}\n\n## Cabeçalhos e rodapés do documento (Docling)\n\n{furniture}\n"


class ExtractStructuredDataStep(PipelineStep):
    def execute(self, input, context):
        work = input
        settings = load_context_settings(context)
        if not work.request.project:
            return StepResult(output=work,has_output=True,text='Extração dispensada para indexação legada sem projeto.',metrics={'extraction_skipped':1})
        if work.noop or work.metadata_only:
            work.extraction = (work.existing_document or {}).get('extraction')
            work.extraction_metadata = (work.existing_document or {}).get('extraction_metadata') or {}
            return StepResult(output=work,has_output=True,text='Extração persistida reutilizada.',metrics={'extraction_reused':1})
        if work.classification is None:
            raise ValueError('Extração exige classificação válida.')
        kind = work.classification['document_type']
        started = perf_counter()
        config = settings.services.llm
        result = {'document_id':work.document_id,'revision_id':work.revision_id,'document_type':kind,'status':'not_applicable','data':None,'sources':[],'warnings':[]}
        metadata = {'model':None,'retry_count':0,'correction_count':0,'fields_count':0,'needs_review':False}
        called = False
        if kind == 'outro':
            result['warnings'] = ['Tipo outro: extração especializada não aplicável.']
        elif not (text := extraction_input(work, settings)).strip() or len(text) > settings.extraction.max_input_chars:
            result.update(status='needs_review',warnings=['Conteúdo vazio ou acima do limite de extração; revisão necessária, sem truncamento silencioso.'])
            metadata['needs_review'] = True
        else:
            if config is None: raise ValueError('Configuração LLM ausente.')
            context.register_model(config.model,provider='openrouter',role='structured_extraction',endpoint=config.endpoint)
            values = config.model_dump(exclude={'structured_output'})
            values['max_tokens'] = settings.extraction.max_output_tokens
            client = LLMClient(**values)
            pages = {int(key) for key in work.docling_json.get('pages',{}) if str(key).isdigit()}
            try:
                with context.trace('extracao_estruturada',metadata={'document_type':kind}):
                    data, metadata = extract_structured_data(client,markdown=text,document_type=kind,
                        projects_dir=classification_projects_dir(settings),project=work.request.project,
                        valid_pages=pages,structured_output=config.structured_output if settings.extraction.structured_output is None else settings.extraction.structured_output)
            except Exception:
                context.logger.error('Extração falhou; nova revisão não será publicada.',metrics={'extraction_success':0,'extraction_json_valid':0,'extraction_duration_seconds':perf_counter()-started})
                raise
            finally: client.close()
            called = True
            metadata['model'] = config.model
            if work.classification['needs_review']:
                data['warnings'].append('Classificação requer revisão humana.')
                metadata['needs_review'] = True
            result.update(data)
            result['status'] = 'needs_review' if metadata['needs_review'] else 'success'
        work.extraction = result
        work.extraction_metadata = metadata
        return StepResult(output=work,has_output=True,text='Extração estruturada concluída ou encaminhada explicitamente para revisão.',metrics={
            'extraction_duration_seconds':perf_counter()-started,'extraction_success':int(called),
            'extraction_json_valid':int(called),'extraction_retry_count':metadata['retry_count'],
            'extraction_correction_count':metadata['correction_count'],'extraction_fields_count':metadata['fields_count'],
            'extraction_output_bytes':len(json.dumps(result,ensure_ascii=False).encode()),
            'extraction_needs_review':int(metadata['needs_review']),'extraction_skipped':int(not called),
            **{f'extraction_{k}':v for k,v in metadata.get('usage',{}).items()}},
            params={'extraction_document_type':kind,'extraction_model':config.model if called else 'none',
                'extraction_prompt_version':metadata.get('prompt_version','none'),'extraction_schema_version':metadata.get('schema_version','none')})
