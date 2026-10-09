"""Explicit model evaluation, with label freeze verified before any inference."""
import argparse
import asyncio
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from .domain import PROMPT_VERSION, SCHEMA_VERSION
from .providers import Settings, make_analyzer, ROOT
from .service import AttentionService
from .store import Store


def freeze_labels(labels,benchmark='original'):
    payload=json.dumps({'cases':labels['cases'],'clock_checks':labels['clock_checks'],'as_of':labels['as_of']},sort_keys=True).encode()
    digest=hashlib.sha256(payload).hexdigest()
    lock=ROOT/'reports'/('labels.lock.json' if benchmark=='original' else f'labels-{benchmark}.lock.json'); lock.parent.mkdir(exist_ok=True)
    if lock.exists():
        if json.loads(lock.read_text())['sha256']!=digest:
            raise ValueError('Expected labels changed after freezing. Preserve the old benchmark and create a new version explicitly.')
    else: lock.write_text(json.dumps({'sha256':digest,'frozen_at':datetime.now(timezone.utc).isoformat(),'note':'Frozen before inference; human review tracked separately.'},indent=2))
    return digest


async def run(args):
    benchmark=args.benchmark
    labels=json.loads((ROOT/'data'/('expected_labels.json' if benchmark=='original' else f'expected_labels_{benchmark}.json')).read_text())
    digest=freeze_labels(labels,benchmark)
    if args.split=='held_out' and not labels.get('human_reviewed',False):
        raise ValueError('Human review of held-out expectations is required before model evaluation. Record the review in the benchmark label file.')
    settings=Settings.from_env()
    if args.provider: settings.provider=args.provider
    if args.model:
        if settings.provider=='ollama': settings.ollama_model=args.model
        elif settings.provider=='glm': settings.glm_model=args.model
        else: settings.gemini_model=args.model
    store=Store(ROOT/'runtime'/'attention.sqlite'); store.seed()
    service=AttentionService(store,make_analyzer(settings))
    cases=[c for c in labels['cases'] if c['split']==args.split]
    if args.ids: cases=[c for c in cases if c['id'] in args.ids.split(',')]
    results=[]
    for case in cases:
        result=await service.analyze(case['id'],datetime.fromisoformat(labels['as_of']),args.force)
        predicted=result['attention']['tier'] if result['attention'] else None
        results.append({**case,'predicted':predicted,'status':result['status'],'error':result['error'],'provenance':result['provenance'],'assessment':result['assessment'],'reason_word_count':len(result['assessment']['reason'].split()) if result['assessment'] and result['assessment'].get('reason') else None})
        print(f"{case['id']}: expected {case['tier']}, actual {predicted or result['status']}",flush=True)
        if result['error']: print(result['error'],flush=True)
    t1=[r for r in results if r['tier']=='T1']
    report={'provider':service.analyzer.provider,'model':service.analyzer.model,'benchmark':benchmark,'split':args.split,'as_of':labels['as_of'],
            'output_contract':service.context(store.thread(cases[0]['id'])).get('output_contract') if cases else None,
            'run_at':datetime.now(timezone.utc).isoformat(),'prompt_version':PROMPT_VERSION,'schema_version':SCHEMA_VERSION,
            'labels_sha256':digest,'human_reviewed':args.split=='held_out' and labels['human_reviewed'],'interpretation':'Policy consistency on synthetic scenarios; not production accuracy.',
            'total':len(results),'agreement_count':sum(r['predicted']==r['tier'] for r in results),
            'critical_misses':sum(r['predicted']!='T1' for r in t1),'true_t1_count':len(t1),
            'false_t1_count':sum(r['predicted']=='T1' and r['tier']!='T1' for r in results),
            'error_count':sum(r['status']=='error' for r in results),'results':results}
    suffix='-subset-'+hashlib.sha256(','.join(c['id'] for c in cases).encode()).hexdigest()[:6] if args.ids else ''
    benchmark_suffix='' if benchmark=='original' else '-'+benchmark
    filename=f"{settings.provider}-{service.analyzer.model.replace(':','-').replace('/','-')}-v{PROMPT_VERSION}{benchmark_suffix}-{args.split}{suffix}.json"
    (ROOT/'reports'/filename).write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k not in ['results']},indent=2),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--benchmark',choices=['original','expansion','long','long_edge'],default='original')
    parser.add_argument('--split',choices=['development','held_out'],default='development')
    parser.add_argument('--provider',choices=['ollama','gemini','glm'])
    parser.add_argument('--model')
    parser.add_argument('--ids')
    parser.add_argument('--force',action='store_true')
    asyncio.run(run(parser.parse_args()))
