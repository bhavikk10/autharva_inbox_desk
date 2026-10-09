import json
import sqlite3
from datetime import datetime, timezone
from contextlib import contextmanager
from pathlib import Path
from typing import Protocol
from .fixtures import seed_threads


class EmailProvider(Protocol):
    def list_threads(self) -> list[dict]: ...
    def get_thread(self,thread_id:str) -> dict: ...


class FakeEmailProvider:
    def list_threads(self): return seed_threads()
    def get_thread(self,thread_id):
        return next(t for t in self.list_threads() if t['id']==thread_id)


class Store:
    def __init__(self,path):
        self.path=Path(path); self.path.parent.mkdir(parents=True,exist_ok=True)
        with self.connection() as db:
            db.executescript('''
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS analysis_operations (id TEXT PRIMARY KEY, kind TEXT NOT NULL, cache_key TEXT, state_json TEXT NOT NULL, updated_at TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS operations_lookup ON analysis_operations(kind, cache_key, updated_at);
                CREATE TABLE IF NOT EXISTS threads (id TEXT PRIMARY KEY, company TEXT NOT NULL, subject TEXT NOT NULL, contact TEXT NOT NULL, deal_value INTEGER);
                CREATE TABLE IF NOT EXISTS messages (id TEXT PRIMARY KEY, thread_id TEXT NOT NULL REFERENCES threads(id), payload TEXT NOT NULL, simulated INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS analysis_snapshots (cache_key TEXT PRIMARY KEY, thread_id TEXT NOT NULL REFERENCES threads(id), provider TEXT NOT NULL, model TEXT NOT NULL, assessment_json TEXT NOT NULL, raw_json TEXT NOT NULL, created_at TEXT NOT NULL, duration_ms INTEGER NOT NULL);
            ''')
    @contextmanager
    def connection(self):
        db=sqlite3.connect(self.path,timeout=15); db.row_factory=sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        try:
            with db: yield db
        finally: db.close()
    def seed(self,provider:EmailProvider|None=None):
        rows=(provider or FakeEmailProvider()).list_threads()
        if provider is None:
            from .account_samples import account_sample_threads
            rows=rows+account_sample_threads()
        with self.connection() as db:
            for t in rows:
                db.execute('INSERT OR IGNORE INTO threads VALUES (?,?,?,?,?)',(t['id'],t['company'],t['subject'],t['contact'],t['deal_value']))
                for m in t['messages']:
                    db.execute('INSERT OR IGNORE INTO messages VALUES (?,?,?,0)',(m['id'],t['id'],json.dumps(m)))
    def threads(self):
        with self.connection() as db: ids=[r[0] for r in db.execute('SELECT id FROM threads ORDER BY rowid')]
        return [self.thread(tid) for tid in ids]
    def import_threads(self,rows):
        # A re-import replaces each successfully fetched complete Gmail thread.
        # Validate the entire batch before changing the database.
        from .domain import Message
        for t in rows:
            if not t['id'].startswith('gmail-'):raise ValueError('Only Gmail threads may be replaced by an import.')
            for m in t['messages']:Message.model_validate(m)
        with self.connection() as db:
            for t in rows:
                db.execute('INSERT INTO threads VALUES (?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET company=excluded.company,subject=excluded.subject,contact=excluded.contact,deal_value=excluded.deal_value',
                           (t['id'],t['company'],t['subject'],t['contact'],t['deal_value']))
                db.execute('DELETE FROM messages WHERE thread_id=?',(t['id'],))
                for m in t['messages']:db.execute('INSERT INTO messages VALUES (?,?,?,0)',(m['id'],t['id'],json.dumps(m)))
    def thread(self,tid):
        with self.connection() as db:
            row=db.execute('SELECT * FROM threads WHERE id=?',(tid,)).fetchone()
            if not row: raise KeyError(tid)
            messages=[json.loads(r[0]) for r in db.execute('SELECT payload FROM messages WHERE thread_id=?',(tid,))]
        return {**dict(row),'messages':messages}
    def snapshot(self,key):
        with self.connection() as db:
            row=db.execute('SELECT * FROM analysis_snapshots WHERE cache_key=?',(key,)).fetchone()
        return dict(row) if row else None
    def save_snapshot(self,key,tid,provider,model,data,raw,created_at,duration,run_context=None):
        from uuid import uuid4
        with self.connection() as db:
            old=db.execute('SELECT * FROM analysis_snapshots WHERE cache_key=?',(key,)).fetchone()
            if old and old['created_at']==created_at and old['raw_json']==raw:return  # Importing the same authentic replay is not another model run.
            if old:
                archived=db.execute("SELECT 1 FROM analysis_operations WHERE kind='run' AND cache_key=? AND json_extract(state_json,'$.created_at')=?",(key,old['created_at'])).fetchone()
                if not archived:
                    legacy={**dict(old),'source':'gmail' if tid.startswith('gmail-') else 'demo','run_context':None}
                    db.execute('INSERT INTO analysis_operations VALUES (?,?,?,?,?)',(self.legacy_run_id(key,old['created_at']),'run',key,json.dumps(legacy),old['created_at']))
            run={'thread_id':tid,'source':'gmail' if tid.startswith('gmail-') else 'demo','provider':provider,'model':model,
                 'assessment_json':data.model_dump_json(),'raw_json':raw,'created_at':created_at,'duration_ms':duration,'run_context':run_context}
            db.execute('INSERT INTO analysis_operations VALUES (?,?,?,?,?)',(uuid4().hex,'run',key,json.dumps(run),created_at))
            db.execute('INSERT OR REPLACE INTO analysis_snapshots VALUES (?,?,?,?,?,?,?,?)',
                       (key,tid,provider,model,data.model_dump_json(),raw,created_at,duration))

    @staticmethod
    def legacy_run_id(key,created_at):
        import hashlib
        return 'legacy-'+hashlib.sha256((key+created_at).encode()).hexdigest()

    def history(self,tid):
        self.thread(tid)
        unique={}
        with self.connection() as db:
            records=db.execute("SELECT * FROM analysis_operations WHERE kind='run' AND json_extract(state_json,'$.thread_id')=? ORDER BY updated_at",(tid,)).fetchall()
        for row in records:
            r={**json.loads(row['state_json']),'id':row['id'],'cache_key':row['cache_key'],'updated_at':row['updated_at']}
            unique.setdefault((r['cache_key'],r['created_at'],r['raw_json']),r)
        runs=list(unique.values())
        with self.connection() as db:
            snapshots=[dict(r) for r in db.execute('SELECT * FROM analysis_snapshots WHERE thread_id=?',(tid,))]
        seen={(r['cache_key'],r['created_at']) for r in runs}
        for r in snapshots:
            if (r['cache_key'],r['created_at']) not in seen:
                import hashlib
                runs.append({**r,'id':self.legacy_run_id(r['cache_key'],r['created_at']),'run_context':None})
        return sorted(runs,key=lambda r:r['created_at'],reverse=True)

    def reviews(self,tid):
        return [r for r in self.operations('review') if r['thread_id']==tid]

    def add_review(self,tid,run_id,expected_tier,note):
        from uuid import uuid4
        run=next((r for r in self.history(tid) if r['id']==run_id),None)
        if not run:raise ValueError('Choose an actual analysis run from this conversation.')
        if expected_tier not in [None,'T1','T2','T3','T4']:raise ValueError('Invalid review tier.')
        if not note.strip() or len(note)>3000:raise ValueError('Explain the correction in 1 to 3,000 characters.')
        return self.save_operation(uuid4().hex,'review',{'thread_id':tid,'source':'gmail' if tid.startswith('gmail-') else 'demo',
            'run_id':run_id,'expected_tier':expected_tier,'note':note.strip()},run['cache_key'])

    def append(self,tid,message):
        self.thread(tid)
        with self.connection() as db:
            db.execute('INSERT INTO messages VALUES (?,?,?,1)',(message.id,tid,message.model_dump_json()))
    def reset(self):
        with self.connection() as db: db.execute('DELETE FROM messages WHERE simulated=1')
    def snapshot_count(self):
        with self.connection() as db: return db.execute('SELECT count(*) FROM analysis_snapshots').fetchone()[0]

    def save_operation(self,oid,kind,state,cache_key=None):
        updated=datetime.now(timezone.utc).isoformat()
        with self.connection() as db:
            db.execute('INSERT OR REPLACE INTO analysis_operations VALUES (?,?,?,?,?)',
                       (oid,kind,cache_key,json.dumps(state),updated))
        return {**state,'id':oid,'updated_at':updated}

    def enqueue_job(self,oid,state):
        updated=datetime.now(timezone.utc).isoformat()
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            sequence=db.execute("SELECT COALESCE(MAX(CAST(json_extract(state_json,'$.queue_sequence') AS INTEGER)),0)+1 FROM analysis_operations WHERE kind='job'").fetchone()[0]
            state={**state,'queue_sequence':sequence}
            db.execute('INSERT OR REPLACE INTO analysis_operations VALUES (?,?,?,?,?)',(oid,'job',None,json.dumps(state),updated))
        return {**state,'id':oid,'updated_at':updated}

    def operation(self,oid):
        with self.connection() as db: row=db.execute('SELECT * FROM analysis_operations WHERE id=?',(oid,)).fetchone()
        if not row: raise KeyError(oid)
        return {**json.loads(row['state_json']),'id':row['id'],'cache_key':row['cache_key'],'updated_at':row['updated_at']}

    def operations(self,kind):
        with self.connection() as db: rows=db.execute('SELECT * FROM analysis_operations WHERE kind=? ORDER BY updated_at',(kind,)).fetchall()
        return [{**json.loads(r['state_json']),'id':r['id'],'cache_key':r['cache_key'],'updated_at':r['updated_at']} for r in rows]

    def latest_attempt(self,key):
        with self.connection() as db:
            row=db.execute("SELECT * FROM analysis_operations WHERE kind='attempt' AND cache_key=? ORDER BY updated_at DESC LIMIT 1",(key,)).fetchone()
        return {**json.loads(row['state_json']),'id':row['id'],'cache_key':row['cache_key'],'updated_at':row['updated_at']} if row else None

    def latest_snapshot(self,tid,provider,model):
        with self.connection() as db:
            row=db.execute('SELECT * FROM analysis_snapshots WHERE thread_id=? AND provider=? AND model=? ORDER BY created_at DESC LIMIT 1',(tid,provider,model)).fetchone()
        return dict(row) if row else None

    def demos_visible(self):
        try:return self.operation('demo-workspace')['visible']
        except KeyError:return True

    def set_demos_visible(self,visible):
        return self.save_operation('demo-workspace','workspace',{'visible':bool(visible)})
