"""Sequential authentic probes; no cached or fabricated provider responses."""
import argparse
import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend.providers import Settings,GLMAnalyzer,ROOT
from backend.service import AttentionService
from backend.store import Store

async def run(args):
    settings=Settings.from_env();settings.glm_thinking=args.thinking;settings.glm_max_tokens=args.tokens
    source=Store(ROOT/'runtime/attention.sqlite')
    target=Store(ROOT/f'runtime/verification/glm-budget-{args.thinking}.sqlite')
    target.seed()
    service=AttentionService(target,GLMAnalyzer(settings))
    path=ROOT/f'reports/glm-budget-probe-{args.thinking}.json'
    results=json.loads(path.read_text(encoding='utf-8')).get('results',[]) if path.exists() else []
    for tid in args.threads:
        # Account samples and source fixtures are identical in the probe store.
        if source.thread(tid)['messages']!=target.thread(tid)['messages']:
            raise ValueError('Probe requires unchanged source-defined demo messages.')
        view=await service.analyze(tid,datetime.fromisoformat(args.as_of),force=True)
        row={'thread_id':tid,'status':view['status'],'error':view['error'],
             'attention':view['attention'],'assessment':view['assessment'],
             'responses':getattr(service.analyzer,'response_diagnostics',[])}
        results.append(row)
        path.write_text(json.dumps({'origin':'actual-model-runs','thinking':args.thinking,
            'max_output_tokens':args.tokens,'results':results},indent=2),encoding='utf-8')
        print(json.dumps({'thread_id':tid,'status':row['status'],'error':row['error'],
            'tier':(row['attention'] or {}).get('tier'),'responses':row['responses']}),flush=True)

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--thinking',choices=['enabled','disabled'],required=True)
    parser.add_argument('--tokens',type=int,default=16384)
    parser.add_argument('--as-of',default='2026-10-09T18:00:00+05:30')
    parser.add_argument('threads',nargs='+')
    asyncio.run(run(parser.parse_args()))
