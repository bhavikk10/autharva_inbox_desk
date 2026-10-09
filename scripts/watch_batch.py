"""Observe a local FIFO job and report frozen-label agreement separately."""
import argparse
import json
import time
from collections import Counter
from pathlib import Path
import httpx

ROOT=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser()
parser.add_argument('job_id')
parser.add_argument('--retry-job',help='Observe one retry, then summarize the original batch with its retried outcomes.')
args=parser.parse_args()
last=None
with httpx.Client(base_url='http://127.0.0.1:8000',timeout=30) as client:
    while True:
        response=client.get('/api/analysis/jobs/'+(args.retry_job or args.job_id));response.raise_for_status();job=response.json()
        counts=dict(Counter(i['status'] for i in job['items']))
        state=(job['status'],job['completed'],counts)
        (ROOT/'reports/batch78-progress.json').write_text(json.dumps(job,indent=2),encoding='utf-8')
        if state!=last:
            print(json.dumps({'status':job['status'],'completed':job['completed'],'total':job['total'],'counts':counts}),flush=True)
            last=state
        if job['status'] not in ['queued','running']:break
        time.sleep(15)
    retry_job=job if args.retry_job else None
    if retry_job:
        response=client.get('/api/analysis/jobs/'+args.job_id);response.raise_for_status();job=response.json()
    response=client.get('/api/threads',params={'as_of':job['as_of'],'source':'demo','timezone':job.get('timezone') or 'Asia/Calcutta'})
    response.raise_for_status();views={t['id']:t for t in response.json()['threads']}
    expectations={}
    for name in ['expected_labels.json','expected_labels_expansion.json','expected_labels_long.json','expected_labels_long_edge.json']:
        document=json.loads((ROOT/'data'/name).read_text(encoding='utf-8'))
        benchmark=name.removeprefix('expected_labels').removesuffix('.json').strip('_') or 'original'
        for row in document['cases']:expectations[row['id']]={**row,'benchmark':benchmark}
    results=[]
    for item in job['items']:
        view=views.get(item['thread_id'],{})
        retried=bool(retry_job and item['thread_id'] in retry_job['thread_ids'])
        expected=expectations.get(item['thread_id'])
        responses=(view.get('attempt') or {}).get('provider_responses',[])
        complete=[r for r in responses if r.get('finish_reason')=='stop']
        results.append({'thread_id':item['thread_id'],'status':view['status'] if retried else item['status'],
            'first_pass_status':item['status'],'error':view.get('error') if retried else item.get('error'),
            'tier':(view.get('attention') or {}).get('tier'),'expected':expected['tier'] if expected else None,
            'actual_provider':(view.get('provenance') or {}).get('provider'),
            'actual_model':(view.get('provenance') or {}).get('model'),
            'fallback':(view.get('provenance') or {}).get('fallback'),
            'split':f"{expected['benchmark']}.{expected['split']}" if expected else 'unlabelled_samples',
            'provider_responses':responses,
            'reasoning_recovery':any(r.get('recovery')=='reasoning_exhaustion' for r in responses),
            'final_thinking':complete[-1].get('thinking') if complete and item['status']=='analyzed' and (view.get('provenance') or {}).get('provider')=='glm' else None})
    counts=dict(Counter(r['status'] for r in results))
    metrics={}
    for split in sorted({r['split'] for r in results}):
        rows=[r for r in results if r['split']==split];labelled=[r for r in rows if r['expected']]
        accepted=[r for r in labelled if r['status']=='analyzed']
        metrics[split]={'total':len(rows),'accepted':sum(r['status']=='analyzed' for r in rows),
            'labelled':len(labelled),'agreement':sum(r['tier']==r['expected'] for r in accepted),
            'agreement_denominator':len(accepted),
            'critical_misses':sum(r['expected']=='T1' and r['tier']!='T1' for r in accepted),
            'unassessed_true_T1':sum(r['expected']=='T1' and r['status']!='analyzed' for r in labelled),
            'false_T1':sum(r['expected']!='T1' and r['tier']=='T1' for r in accepted)}
    provider_metrics={}
    for provider in sorted({r['actual_provider'] for r in results if r['actual_provider']}):
        rows=[r for r in results if r['actual_provider']==provider and r['status']=='analyzed']
        provider_metrics[provider]={}
        for split in sorted({r['split'] for r in rows}):
            group=[r for r in rows if r['split']==split];labelled=[r for r in group if r['expected']]
            provider_metrics[provider][split]={'accepted':len(group),'labelled':len(labelled),
                'agreement':sum(r['tier']==r['expected'] for r in labelled),
                'critical_misses':sum(r['expected']=='T1' and r['tier']!='T1' for r in labelled),
                'false_T1':sum(r['expected']!='T1' and r['tier']=='T1' for r in labelled)}
    report={'origin':'actual-model-runs','job_id':job['id'],'as_of':job['as_of'],'force':job['force'],
        'retry_job_id':retry_job['id'] if retry_job else None,'retry_status':retry_job['status'] if retry_job else None,
        'status':job['status'],'identity':job['identity'],'counts':counts,'failures_by_reason':dict(Counter(r['error'] for r in results if r['status']=='error')),
        'reasoning_recoveries_attempted':sum(r['reasoning_recovery'] for r in results),
        'reasoning_recoveries_accepted':sum(r['reasoning_recovery'] and r['status']=='analyzed' and r['actual_provider']=='glm' for r in results),
        'accepted_thinking_modes':dict(Counter(r['final_thinking'] for r in results if r['status']=='analyzed' and r['actual_provider']=='glm')),
        'actual_providers':dict(Counter(r['actual_provider'] for r in results if r['status']=='analyzed')),
        'fallback_accepted':sum(bool(r['fallback']) and r['status']=='analyzed' for r in results),
        'provider_metrics':provider_metrics,
        'metrics':metrics,'label_note':'Five original held-out labels were user-reviewed. The other 58 labels, including the five expansion held-out labels, are implementer-authored frozen policy checks. The 15 new samples have no frozen labels. force=false reuses valid actual saved assessments.',
        'results':results}
    (ROOT/'reports/batch78-evaluation.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k!='results'}),flush=True)
