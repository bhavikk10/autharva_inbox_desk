"""Export and restore validated actual runs. Never generate or author model outputs."""
import argparse
import json
from datetime import datetime
from pathlib import Path
from .domain import Assessment, ExtractionAssessment, GeneralExtractionAssessment, GENERAL_EXTRACTION_CONTRACT, EXTRACTION_CONTRACT, Message, PROMPT_VERSION, SCHEMA_VERSION, content_hash, validate_evidence
from .providers import ROOT, Settings, make_analyzer
from .fixtures import DEFAULT_AS_OF
from .service import AttentionService
from .store import Store


def export_replay(service:AttentionService,path:Path) -> int:
    runs=[]; seen=set()
    if service.analyzer.provider not in ['ollama','gemini','glm']:
        raise ValueError('Replay requires an actual supported model provider, not test doubles.')
    for thread in service.store.threads():
        # Personal inbox data is never exported into shareable demo artifacts.
        if thread['id'].startswith('gmail-'): continue
        # Include saved prefixes as well as the current thread, so resetting a
        # simulated reply still has the authentic original assessment available.
        cutoffs={m['sent_at'] for m in thread['messages']}
        cutoffs.add(DEFAULT_AS_OF)
        for cutoff in sorted(cutoffs):
            _,messages,key=service.prepared(thread['id'],datetime.fromisoformat(cutoff))
            snapshot=service.store.snapshot(key)
            if not snapshot or key in seen: continue
            seen.add(key)
            runs.append({**snapshot,'input_messages':[m.model_dump(mode='json') for m in messages],
                         'context':service.context(thread)})
    document={'origin':'actual-model-runs','prompt_version':PROMPT_VERSION,'schema_version':SCHEMA_VERSION,'runs':runs}
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(document,indent=2,ensure_ascii=False),encoding='utf-8')
    return len(runs)


def import_replay(store:Store,path:Path) -> int:
    document=json.loads(path.read_text(encoding='utf-8'))
    if document.get('origin')!='actual-model-runs': raise ValueError('Replay must contain actual model runs.')
    if document.get('prompt_version')!=PROMPT_VERSION or document.get('schema_version')!=SCHEMA_VERSION:
        raise ValueError('Replay prompt/schema version does not match this build.')
    checked=[]
    for entry in document['runs']:
        if entry['provider'] not in ['ollama','gemini','glm']: raise ValueError('Unsupported replay provider.')
        thread=store.thread(entry['thread_id'])
        context={k:thread[k] for k in ['company','subject','deal_value']}
        if thread['id'].startswith('sample-'):context['prompt_variant']=GENERAL_EXTRACTION_CONTRACT
        if entry['provider']=='glm':
            contract=entry['context'].get('output_contract')
            if contract not in ['glm-json-contract-v1','glm-json-contract-v2-reason','glm-json-contract-v3-reason','glm-json-contract-v4-obligations','glm-json-contract-v5-grounded','glm-json-contract-v6-ledger','glm-json-contract-v7-ledger-template','glm-json-contract-v8-resolution-review','glm-json-contract-v9-thinking-resolution','glm-json-contract-v10-evidence-regeneration','glm-json-contract-v11-bounded-reasoning-recovery']:
                raise ValueError('Unsupported GLM replay output contract.')
            context['output_contract']=contract
            generation=entry['context'].get('generation_config')
            if generation is not None:
                if not isinstance(generation,dict) or set(generation) not in [{'thinking','max_output_tokens'},{'thinking','max_output_tokens','reasoning_exhaustion_recovery'}] or generation['thinking'] not in ['enabled','disabled'] or not isinstance(generation['max_output_tokens'],int) or not 1<=generation['max_output_tokens']<=131072 or ('reasoning_exhaustion_recovery' in generation and not isinstance(generation['reasoning_exhaustion_recovery'],bool)):
                    raise ValueError('Invalid GLM replay generation configuration.')
                context['generation_config']=generation
        if 'extraction_contract' in entry['context']:
            if entry['context']['extraction_contract'] not in ['grounded-obligations-v1',EXTRACTION_CONTRACT]: raise ValueError('Unsupported extraction contract.')
            context['extraction_contract']=entry['context']['extraction_contract']
        if context!=entry['context']: raise ValueError('Replay input context does not match the thread.')
        messages=[Message(**m) for m in entry['input_messages']]
        expected_key=content_hash(messages,entry['provider'],entry['model'],context)
        if entry['cache_key']!=expected_key: raise ValueError('Replay input hash mismatch.')
        data=Assessment.model_validate_json(entry['assessment_json'])
        raw_data=Assessment.model_validate_json(entry['raw_json'])
        if raw_data!=data: raise ValueError('Replay assessment does not match the original raw model response.')
        grounded='extraction_contract' in context
        if context.get('extraction_contract')==EXTRACTION_CONTRACT:
            (GeneralExtractionAssessment if thread['id'].startswith('sample-') else ExtractionAssessment).model_validate_json(entry['raw_json'])
        validate_evidence(data,messages,require_grounded=grounded)
        if datetime.fromisoformat(entry['created_at']).tzinfo is None: raise ValueError('Replay run timestamp requires a timezone.')
        if not isinstance(entry['duration_ms'],int) or entry['duration_ms']<0: raise ValueError('Invalid replay duration.')
        checked.append((entry,data))
    for entry,data in checked:
        existing=store.snapshot(entry['cache_key'])
        if existing and datetime.fromisoformat(existing['created_at'])>=datetime.fromisoformat(entry['created_at']):
            continue
        store.save_snapshot(entry['cache_key'],entry['thread_id'],entry['provider'],entry['model'],data,
                            entry['raw_json'],entry['created_at'],entry['duration_ms'])
    return len(checked)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--provider',choices=['ollama','gemini','glm']);parser.add_argument('--model');parser.add_argument('--output')
    args=parser.parse_args();settings=Settings.from_env()
    if args.provider: settings.provider=args.provider
    if args.model:
        if settings.provider=='ollama':settings.ollama_model=args.model
        elif settings.provider=='glm':settings.glm_model=args.model
        else:settings.gemini_model=args.model
    store=Store(ROOT/'runtime'/'attention.sqlite');store.seed()
    service=AttentionService(store,make_analyzer(settings))
    filename=f"replay-{service.analyzer.provider}-{service.analyzer.model.replace(':','-').replace('/','-')}.json"
    path=Path(args.output) if args.output else ROOT/'reports'/filename
    count=export_replay(service,path)
    print(f'Exported {count} actual runs to {path}')
