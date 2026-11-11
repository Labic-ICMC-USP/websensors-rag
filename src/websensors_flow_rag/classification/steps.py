from time import perf_counter

from websensors_flow import PipelineStep, StepResult
from websensors_flow_rag.clients.llm_client import LLMClient
from websensors_flow_rag.classification.service import classify_document, load_classification_resources
from websensors_flow_rag.utils import classification_projects_dir, load_context_settings


class ClassifyDocumentTypeStep(PipelineStep):
    def execute(self, input, context):
        work = input
        settings = load_context_settings(context)
        if not work.request.project:
            return StepResult(output=work, has_output=True, text="Classificação dispensada para indexação legada sem projeto.", metrics={"classification_skipped":1})
        if work.noop or work.metadata_only:
            work.classification = (work.existing_document or {}).get('classification')
            work.classification_metadata = (work.existing_document or {}).get('classification_metadata') or {}
            return StepResult(output=work, has_output=True, text="Classificação persistida reutilizada.", metrics={"classification_reused":1})
        config = settings.services.llm
        if config is None:
            raise ValueError('Configuração LLM ausente.')
        directory = classification_projects_dir(settings)
        started = perf_counter()
        if work.request.document_type:
            categories, _, _, version = load_classification_resources(directory,work.request.project)
            if work.request.document_type not in categories:
                raise ValueError('Tipo declarado não pertence ao projeto.')
            classification = {'document_type':work.request.document_type,'reason':'Tipo informado explicitamente pelo solicitante; não houve predição LLM.','needs_review':work.request.document_type=='outro'}
            metadata = {'prompt_version':version,'retry_count':0,'llm_called':False,'source':'declared'}
        else:
            context.register_model(config.model,provider='openrouter',role='document_classification',endpoint=config.endpoint)
            client = LLMClient(**config.model_dump(exclude={'structured_output'}))
            try:
                with context.trace('classificacao_documental',metadata={'project':work.request.project}):
                    classification, metadata = classify_document(client, markdown=work.markdown, filename=work.filename,
                        projects_dir=directory,project=work.request.project,max_input_chars=settings.classification.max_input_chars,
                        structured_output=config.structured_output)
            except Exception:
                context.logger.error("Classificação falhou; nova revisão não será publicada.", metrics={"classification_success":0,"classification_duration_seconds":perf_counter()-started})
                raise
            finally: client.close()
            metadata['source']='llm' if metadata['llm_called'] else 'review_guard'
        work.classification = classification
        work.classification_metadata = {**metadata,'model':config.model if metadata['llm_called'] else None}
        return StepResult(output=work,has_output=True,text="Tipo documental identificado; resultado completo preservado nos artefatos.",metrics={
            'classification_duration_seconds':perf_counter()-started,'classification_success':1,
            'classification_unknown':int(classification['document_type']=='outro'),
            'classification_retry_count':metadata['retry_count'],
            'classification_needs_review':int(classification['needs_review']),
            **{f'classification_{key}':value for key,value in metadata.get('usage',{}).items()}},
            params={'classification_model':config.model,'classification_document_type':classification['document_type'],'classification_prompt_version':metadata['prompt_version']})
