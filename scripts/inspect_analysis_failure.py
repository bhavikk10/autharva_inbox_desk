import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend.store import Store
from backend.providers import ROOT
store=Store(ROOT/'runtime/attention.sqlite')
tid=sys.argv[1]
provider=sys.argv[2] if len(sys.argv)>2 else 'glm'
attempts=[a for a in store.operations('attempt') if a.get('thread_id')==tid and a.get('status')=='error' and a.get('provider')==provider]
attempt=attempts[-1]
snapshot=store.latest_snapshot(tid,attempt['provider'],attempt['model'])
path=ROOT/'runtime/rejected'/f"{attempt['cache_key']}.json"
def ledger(raw):
    data=json.loads(raw)
    rows=data.get('obligations') or [*data.get('open_items',[]),*data.get('resolved_items',[])]
    return [{k:r.get(k) for k in ['description','owner','status','evidence_message_ids','action_evidence','ownership_evidence','resolution_evidence']} for r in rows]
print(json.dumps({'error':attempt.get('error'),'prior':ledger(snapshot['raw_json']) if snapshot else None,
    'rejected':ledger(path.read_text(encoding='utf-8')) if path.exists() else None},indent=2))
