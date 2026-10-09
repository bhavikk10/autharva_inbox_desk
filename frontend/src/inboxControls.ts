import type {Thread,Tier} from './types.ts'
export type InboxFilter=Tier|'all'|'unassessed'|'error'
export type InboxSort='attention'|'newest'|'deadline'
export function selectedThreadId(rows:Pick<Thread,'id'>[],selected:string):string{
 return rows.some(t=>t.id===selected)?selected:rows[0]?.id||''
}
export function visibleThreads(rows:Thread[],filter:InboxFilter,search:string,sort:InboxSort):Thread[]{
 const query=search.trim().toLowerCase()
 const newest=(t:Thread)=>Math.max(0,...t.messages.map(m=>Date.parse(m.sent_at)))
 const due=(t:Thread)=>Math.min(Infinity,...(t.attention?.open_items||[]).filter(i=>i.due_at).map(i=>Date.parse(i.due_at!)))
 return rows.filter(t=>t.status!=='not_started'&&(filter==='all'||(filter==='unassessed'&&t.status==='unassessed')||(filter==='error'&&t.status==='error')||t.attention?.tier===filter)&&`${t.company} ${t.subject} ${t.contact} ${t.assessment?.summary||''}`.toLowerCase().includes(query))
 .sort((a,b)=>{
  const primary=sort==='newest'?newest(b)-newest(a):sort==='deadline'?(due(a)===due(b)?0:due(a)<due(b)?-1:1):(a.attention?.tier||'T0').localeCompare(b.attention?.tier||'T0')
  return primary||newest(b)-newest(a)||a.id.localeCompare(b.id)
 })
}
