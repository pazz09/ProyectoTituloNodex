"""Observación lateral del RAG: devuelve los mismos objetos y argumentos.

No añade campos al estado de LangGraph ni hace consultas adicionales. Registra
el límite real de consulta y el límite de envío del SDK; no infiere causalidad.
"""
from __future__ import annotations
import hashlib
import inspect
import json
import threading
from contextvars import ContextVar
from datetime import datetime, timezone
from functools import wraps
from unittest.mock import patch


def fingerprint(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def contains_document(prompt, document):
    return json.dumps(document, ensure_ascii=False) in prompt


class RagObserver:
    def __init__(self, path, identity):
        self.path, self.identity = path, identity
        self.lock = threading.RLock()
        self.current = ContextVar('observed_rag_query', default=None)
        self.documents, self.patches = [], []
        self.sequence = 0

    def emit(self, event, **data):
        with self.lock:
            self.sequence += 1
            row = dict(self.identity, event=event, event_index=self.sequence,
                       utc=datetime.now(timezone.utc).isoformat(), **data)
            with self.path.open('a', encoding='utf-8', newline='\n') as stream:
                stream.write(json.dumps(row, ensure_ascii=False, allow_nan=False) + '\n')
        return row

    def install(self):
        import importlib
        rag = importlib.import_module('src.tools.tool_consultar_rag')
        from src.memory import LongTermMemory
        import src.llm as llm
        original_query = LongTermMemory._query
        original_tool = rag.tool_consultar_rag
        original_generate = llm.client.models.generate_content
        observer = self

        @wraps(original_query)
        def query(memory, col, text, *args, **kwargs):
            native = []
            original_native = col.query
            def capture(*a, **kw):
                result = original_native(*a, **kw)
                native.append(result)
                return result
            with patch.object(col, 'query', capture):
                result = original_query(memory, col, text, *args, **kwargs)
            candidates = []
            for response in native:
                for rank, (vid, doc, meta, distance) in enumerate(zip(response['ids'][0], response['documents'][0],
                        response['metadatas'][0], response['distances'][0]), 1):
                    delivered = any(x['texto'] == doc and x['meta'] == (meta or {})
                                    and x['similitud'] == round(1-distance, 3) for x in result)
                    candidates.append(dict(vector_id=vid, rank=rank, distance=float(distance), similarity=1-float(distance),
                        returned_by_memory=delivered, text=doc, metadata=meta or {},
                        knowledge_type=('historical' if (meta or {}).get('knowledge_origin') == 'historical_development'
                                        else 'mitre_static' if col.name == 'attack_techniques' else 'dynamic_memory')))
            ties = any(abs(a['distance']-b['distance']) <= 1e-12 for i,a in enumerate(candidates) for b in candidates[i+1:])
            observer.emit('memory_query', query_id=observer.current.get(), collection=col.name,
                          query_text=text, returned_documents=len(result), candidates=candidates,
                          ties_among_top_k=ties, ties_scope='solo candidatos observados dentro del top-k')
            return result

        @wraps(original_tool)
        def tool(state):
            query_id = f"rag-query-{observer.sequence + 1}"
            token = observer.current.set(query_id)
            observer.emit('rag_requested', query_id=query_id, signature=state['firma'])
            try:
                result = original_tool(state)
                for field in ('contexto_rag', 'tecnicas_mitre'):
                    for document in result.get(field) or []:
                        observer.documents.append((query_id, field, document))
                observer.emit('rag_returned', query_id=query_id, result=result)
                return result
            except Exception as error:
                observer.emit('rag_error', query_id=query_id, error_type=type(error).__name__)
                raise
            finally:
                observer.current.reset(token)

        @wraps(original_generate)
        def generate(*args, **kwargs):
            content = kwargs.get('contents')
            prompt = content if isinstance(content, str) else str(content)
            frame = inspect.currentframe()
            agent = None
            while frame:
                module = frame.f_globals.get('__name__', '')
                if module.startswith('src.agents.'):
                    agent = module
                    break
                frame = frame.f_back
            del frame
            delivered = []
            for query_id, field, doc in observer.documents:
                if contains_document(prompt, doc):
                    meta = doc.get('meta') or {}
                    delivered.append(dict(query_id=query_id, field=field,
                        vector_id=meta.get('vector_id'), historical_case_id=meta.get('historical_case_id'),
                        technique_id=meta.get('technique_id'),
                        knowledge_type='historical' if meta.get('historical_case_id') else 'mitre_static',
                        document_json_sha256=fingerprint(json.dumps(doc, ensure_ascii=False))))
            request = observer.emit('llm_sdk_request', agent=agent, model=kwargs.get('model'),
                                    prompt_sha256=fingerprint(prompt), documents_in_payload=delivered)
            try:
                response = original_generate(*args, **kwargs)
                observer.emit('llm_sdk_response', request_event_index=request['event_index'],
                              model_version=getattr(response, 'model_version', None), success=True)
                return response
            except Exception as error:
                observer.emit('llm_sdk_response', request_event_index=request['event_index'],
                              success=False, error_type=type(error).__name__, provider_receipt='unknown')
                raise

        self.patches = [patch.object(LongTermMemory, '_query', query),
                        patch.object(rag, 'tool_consultar_rag', tool),
                        patch.object(llm.client.models, 'generate_content', generate)]
        for p in self.patches:
            p.start()
        self.emit('observer_installed', functional_state_modified=False, extra_queries=False,
                  influence_observable=False)

    def close(self):
        for p in reversed(self.patches):
            p.stop()
