import {useEffect,useMemo,useRef,useState} from 'react'
import {IconArrowRight,IconArrowUpRight,IconCheck,IconChevronLeft,IconClock,IconInbox,IconInfoCircle,IconLoader2,IconMail,IconPaperclip,IconPlayerPlay,IconRefresh,IconSearch,IconSend,IconShieldCheck,IconX} from '@tabler/icons-react'
import type {AnalysisJob,Config,Message,Obligation,Thread,Tier} from './types'
import {detectedTimezone,setDisplayTimezone,formatTime,isoClock,localClock,relativeDayInput,request,shortDate} from './api'
import GmailPanel from './GmailPanel'
import SavedRunsPanel from './SavedRunsPanel'
import QueuePanel from './QueuePanel'
import ReviewTools from './ReviewTools'
import {selectedThreadId,visibleThreads,type InboxFilter,type InboxSort} from './inboxControls'
import {GMAIL_LABELS,matchesGmailLabel,gmailBadges} from './gmailLabels'

const SAMPLE_MAILBOX_NAME='Bhavik'
const TIERS:Record<Tier,{label:string;short:string}>={T1:{label:'Immediate attention',short:'Immediate'},T2:{label:'Action required',short:'Action'},T3:{label:'Monitor',short:'Monitor'},T4:{label:'No attention',short:'Quiet'}}
const initials=(name:string)=>name.split(' ').map(p=>p[0]).slice(0,2).join('')
const errorText=(error:unknown)=>error instanceof Error?error.message:'Something went wrong. Please retry.'

function TierBadge({tier}:{tier:Tier}){return <span className={`tier-badge ${tier.toLowerCase()}`}><span className="status-dot"/>{tier} <span>{TIERS[tier].short}</span></span>}

export default function App(){
  const [timezone,setTimezone]=useState(()=>{const zone=detectedTimezone();setDisplayTimezone(zone);return zone})
  const zones=useMemo(()=>Array.from(new Set([timezone,'UTC',...Intl.supportedValuesOf('timeZone')])),[timezone])
  const [config,setConfig]=useState<Config|null>(null)
  const [threads,setThreads]=useState<Thread[]>([])
  const [selected,setSelected]=useState('northstar')
  const [asOf,setAsOf]=useState('2026-10-09T18:00:00+05:30')
  const [filter,setFilter]=useState<InboxFilter>('all')
  const [gmailFilter,setGmailFilter]=useState('all')
  const [search,setSearch]=useState('')
  const [error,setError]=useState('')
  const [loading,setLoading]=useState(true)
  const [busy,setBusy]=useState(false)
  const [progress,setProgress]=useState({completed:0,total:0})
  const [mobileDetail,setMobileDetail]=useState(false)
  const [help,setHelp]=useState(false)
  const [composer,setComposer]=useState(false)
  const [reply,setReply]=useState('')
  const [direction,setDirection]=useState<'inbound'|'outbound'>('outbound')
  const [attachments,setAttachments]=useState('')
  const [highlight,setHighlight]=useState<string[]>([])
  const [replay,setReplay]=useState(false)
  const [jobId,setJobId]=useState<string|null>(null)
  const [jobPhase,setJobPhase]=useState('')
  const [recovery,setRecovery]=useState<AnalysisJob|null>(null)
  const [source,setSource]=useState<'demo'|'long'|'gmail'>('demo')
  const [gmailOpen,setGmailOpen]=useState(false)
  const [queueOpen,setQueueOpen]=useState(false),[sort,setSort]=useState<InboxSort>('attention'),[checked,setChecked]=useState<string[]>([]),[syncing,setSyncing]=useState(false),[syncNotice,setSyncNotice]=useState('')
  const loadCounter=useRef(0)
  const controller=useRef<AbortController|null>(null)
  const helpRef=useRef<HTMLDialogElement>(null)
  const detailScrollRef=useRef<HTMLDivElement>(null)
  const inboxListRef=useRef<HTMLDivElement>(null)
  const selectedRowRef=useRef<HTMLButtonElement>(null)
  const [savedOpen,setSavedOpen]=useState(false),[savedRunId,setSavedRunId]=useState<string|null>(null),[savedView,setSavedView]=useState<Thread|null>(null),[keepDemos,setKeepDemos]=useState(true)
  const categoryThreads=useMemo(()=>source==='gmail'?threads.filter(t=>matchesGmailLabel(t,gmailFilter)):threads,[threads,source,gmailFilter])
  const analyzed=categoryThreads.filter(t=>t.status==='analyzed').length
  const counts=Object.fromEntries(Object.keys(TIERS).map(tier=>[tier,categoryThreads.filter(t=>t.attention?.tier===tier).length])) as Record<Tier,number>
  const filtered=useMemo(()=>visibleThreads(categoryThreads,filter,search,sort),[categoryThreads,filter,search,sort])
  const visibleSelection=selectedThreadId(filtered,selected)
  const current=savedView||filtered.find(t=>t.id===visibleSelection)
  useEffect(()=>{
    if(savedRunId||selected===visibleSelection)return
    setSelected(visibleSelection);setHighlight([]);setComposer(false);setReply('');setAttachments('')
    if(!visibleSelection)setMobileDetail(false)
  },[visibleSelection,savedRunId,selected])
  useEffect(()=>{
    if(savedRunId)return
    const list=inboxListRef.current,row=selectedRowRef.current
    if(!list||!row)return
    const revealSelected=()=>{
      if(!list.clientHeight)return
      const pane=list.getBoundingClientRect(),item=row.getBoundingClientRect()
      if(item.top<pane.top||item.height>pane.height)list.scrollTop+=item.top-pane.top
      else if(item.bottom>pane.bottom)list.scrollTop+=item.bottom-pane.bottom
    }
    revealSelected()
    const observer=new ResizeObserver(revealSelected)
    observer.observe(list);observer.observe(row)
    return()=>observer.disconnect()
  },[visibleSelection,filtered,savedRunId])
  useEffect(()=>{setChecked(old=>old.filter(id=>threads.some(t=>t.id===id)))},[threads])

  useEffect(()=>{if(config?.demo_workspace_visible!==undefined)setKeepDemos(config.demo_workspace_visible)},[config?.demo_workspace_visible])

  async function load(time:string,mailSource=source){
    const serial=++loadCounter.current
    try {const result=await request<{threads:Thread[]}>(`/threads?as_of=${encodeURIComponent(time)}&source=${mailSource}&timezone=${encodeURIComponent(timezone)}`);if(serial===loadCounter.current){setThreads(result.threads);setSelected(old=>result.threads.some(t=>t.id===old)?old:result.threads[0]?.id||'');setError('')}}
    catch(e){if(serial===loadCounter.current)setError(errorText(e))}
    finally{if(serial===loadCounter.current)setLoading(false)}
  }
  useEffect(()=>{
    request<Config>('/config').then(setConfig).catch(e=>setError(errorText(e)))
    request<{jobs:AnalysisJob[]}>('/analysis/jobs').then(({jobs})=>{
      const active=jobs.filter(j=>j.task!=='draft'&&(j.status==='running'||j.status==='queued')).at(-1)
      if(active)beginJob(active)
      else {const interrupted=jobs.filter(j=>j.task!=='draft'&&j.status==='interrupted').at(-1);if(interrupted)setRecovery(interrupted)}
    }).catch(e=>setError(errorText(e)))
    return()=>controller.current?.abort()
  },[])
  useEffect(()=>{
    if(!jobId)return
    const abort=new AbortController();controller.current=abort;let count=-1
    async function track(){
      try{
        while(!abort.signal.aborted){
          const job=await request<AnalysisJob>(`/analysis/jobs/${jobId}`,{signal:abort.signal})
          setProgress({completed:job.completed,total:job.total});setJobPhase(job.status)
          if(job.completed!==count){count=job.completed;await load(job.as_of,job.source)}
          if(job.status==='interrupted'){setRecovery(job);setError('Analysis was interrupted. Wait for the earlier provider request to finish, then resume the remaining work.');break}
          if(job.status==='completed'||job.status==='cancelled')break
          await new Promise<void>(resolve=>{const done=()=>{clearTimeout(timer);abort.signal.removeEventListener('abort',done);resolve()};const timer=window.setTimeout(done,1250);abort.signal.addEventListener('abort',done,{once:true})})
        }
        if(!abort.signal.aborted)setConfig(await request<Config>('/config'))
      }catch(e){if(!abort.signal.aborted)setError(errorText(e))}
      finally{if(!abort.signal.aborted){setBusy(false);setJobId(null);controller.current=null}}
    }
    void track()
    return()=>abort.abort()
  },[jobId])
  useEffect(()=>{setLoading(true);setHighlight([]);setComposer(false);void load(asOf)},[asOf,source,timezone])
  useEffect(()=>{if(help)helpRef.current?.showModal();else helpRef.current?.close()},[help])
  useEffect(()=>{detailScrollRef.current?.scrollTo({top:0});},[current?.id,asOf,savedRunId])

  useEffect(()=>{if(!savedRunId)return;let live=true
    request<Thread>(`/saved-runs/${savedRunId}?as_of=${encodeURIComponent(asOf)}&timezone=${encodeURIComponent(timezone)}`).then(t=>{if(live)setSavedView(t)}).catch(e=>{if(live){setError(e.message);setSavedView(old=>old?{...old,messages:[],assessment:null,attention:null,provenance:null,resolved_items:[],status:'error',error:e.message,as_of:asOf}:null)}})
    return()=>{live=false}
  },[savedRunId,asOf,timezone])
  async function openSavedRun(id:string){
    const t=await request<Thread>(`/saved-runs/${id}?as_of=${encodeURIComponent(asOf)}&timezone=${encodeURIComponent(timezone)}`)
    setSavedView(t);setSelected(t.id);setSavedRunId(id);setReplay(true);setComposer(false);setHighlight([]);setMobileDetail(true);setError('')
  }
  async function restoreDemos(id?:string){
    await request('/demo/visibility',{method:'POST',body:JSON.stringify({visible:true})});setConfig(await request<Config>('/config'))
    setSavedView(null);setSavedRunId(null);setReplay(false);setSource('demo');setFilter('all');setSearch('');setGmailFilter('all');setChecked([])
    const time=config?.default_as_of||asOf;setAsOf(time);await load(time,'demo');if(id){setSelected(id);setMobileDetail(true)}
  }
  function leaveSaved(){setSavedView(null);setSavedRunId(null);setReplay(false);setError('')}
  function update(thread:Thread){setThreads(old=>old.map(t=>t.id===thread.id?thread:t))}
  function beginJob(job:AnalysisJob){
    setRecovery(null);setSource(job.source);setAsOf(job.as_of);setReplay(job.replay)
    if(job.timezone){setDisplayTimezone(job.timezone);setTimezone(job.timezone)}
    setBusy(true);setProgress({completed:job.completed,total:job.total});setJobPhase(job.status);setJobId(job.id)
  }
  async function analyze(ids?:string[],force=false){
    if(busy||savedRunId)return
    const targetIds=ids??filtered.map(t=>t.id)
    if(!targetIds.length)return
    setBusy(true);setError('')
    try{
      const job=await request<AnalysisJob>('/analysis/jobs',{method:'POST',body:JSON.stringify({as_of:asOf,thread_ids:targetIds,force,replay,source,timezone})})
      beginJob(job)
    }catch(e){setError(errorText(e));setBusy(false)}
  }
  async function recover(dismiss=false){
    if(!recovery||busy)return
    try{
      const job=await request<AnalysisJob>(`/analysis/jobs/${recovery.id}/${dismiss?'dismiss':'resume'}`,{method:'POST'})
      setError('');if(dismiss)setRecovery(null);else beginJob(job)
    }catch(e){setError(errorText(e))}
  }
  function changeClock(value:string){if(!busy&&value)setAsOf(value)}
  function chooseDay(days:0|1){
    if(busy)return
    try{const now=new Date();changeClock(days===0?now.toISOString():isoClock(relativeDayInput(days,timezone,now),timezone));setError('')}
    catch(e){setError(errorText(e))}
  }
  function changeTimezone(zone:string){
    if(busy)return
    try{setDisplayTimezone(zone);setTimezone(zone);setError('');try{localStorage.setItem('autharva.timezone',zone)}catch{}}
    catch(e){setError(errorText(e))}
  }
  function editClock(value:string){
    if(!value||busy)return
    try{changeClock(isoClock(value,timezone));setError('')}catch(e){setError(errorText(e))}
  }
  function changeSource(value:'demo'|'long'|'gmail'){leaveSaved();setChecked([]);setSyncNotice('');setThreads([]);setSelected('');setLoading(true);setSource(value);setFilter('all');setGmailFilter('all');setSearch('');setMobileDetail(false);if(value==='gmail'){setReplay(false);setAsOf(new Date().toISOString())}else if(source==='gmail')setAsOf(config?.default_as_of||'2026-10-09T18:00:00+05:30')}
  async function reset(){
    if(busy)return
    setBusy(true)
    try{const result=await request<{as_of:string}>('/demo/reset',{method:'POST'});setAsOf(result.as_of);setReply('');setComposer(false);setHighlight([]);await load(result.as_of)}catch(e){setError(errorText(e))}finally{setBusy(false)}
  }
  async function send(){
    if(!current||savedRunId||!reply.trim()||busy)return
    setBusy(true);setError('')
    try{const result=await request<{thread:Thread}>(`/threads/${current.id}/messages`,{method:'POST',body:JSON.stringify({direction,body:reply.trim(),sent_at:asOf,attachments:attachments.split(',').map(s=>s.trim()).filter(Boolean)})});update(result.thread);setReply('');setAttachments('');setComposer(false)}
    catch(e){setError(errorText(e))}finally{setBusy(false)}
  }
  function showEvidence(ids:string[]){setHighlight(ids);setTimeout(()=>document.getElementById(`message-${ids[0]}`)?.scrollIntoView({behavior:window.matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth',block:'center'}),0)}
  async function syncLatest(){
    setSyncing(true);setError('');setSyncNotice('')
    try{const r=await request<{fetched:number;imported:number;unchanged:number;skipped:number}>('/gmail/sync',{method:'POST',body:JSON.stringify({keep_demos:keepDemos})});setSyncNotice(`${r.fetched} checked; ${r.imported} updated; ${r.unchanged} unchanged; ${r.skipped} skipped. Analyze updated conversations when ready.`);setConfig(await request<Config>('/config'));setAsOf(new Date().toISOString());await load(new Date().toISOString(),'gmail')}
    catch(e){setError(errorText(e))}finally{setSyncing(false)}
  }
  function choose(id:string){leaveSaved();setSelected(id);setHighlight([]);setComposer(false);setReply('');setAttachments('');setMobileDetail(true)}

  return <div className="app-shell">
    <main>
      <header className="topbar"><div className="wordmark">Inbox Desk<span>{source==='gmail'?'Mail workspace':'Sales workspace'}</span></div><nav className="topbar-right" aria-label="Workspace controls"><span className={`connection ${config?.ready?'connected':''}`} aria-label="Configured analysis provider" title="Provider for new analysis. The selected assessment shows its actual model below."><span className="status-dot"/>{savedView?.provenance?`${savedView.provenance.model} / saved`:config?.model||'Connecting…'}</span><button className="text-button" onClick={()=>setQueueOpen(true)}>Queue</button><button className="text-button mailbox-settings" disabled={busy} onClick={()=>setGmailOpen(true)}>Gmail settings</button><button className="icon-button topbar-settings" aria-label="Information and settings" onClick={()=>setHelp(true)}><IconInfoCircle size={18}/></button></nav></header>
      <section className="command-bar" aria-label="Sales attention and time controls"><h1>{source==='gmail'?'Inbox attention':'Sales attention'}</h1><div className="clock-controls"><label className="clock-input"><IconClock size={16}/><span className="sr-only">Evaluation date and time</span><input aria-label="Evaluation date and time" type="datetime-local" value={localClock(asOf,timezone)} disabled={busy} onChange={e=>editClock(e.target.value)}/></label><label className="timezone-control"><span className="sr-only">Attention timezone</span><select aria-label="Attention timezone" title="Detected from your browser; you can override it. Explicit email zones take precedence." value={timezone} disabled={busy} onChange={e=>changeTimezone(e.target.value)}>{zones.map(zone=><option key={zone} value={zone}>{zone.replaceAll('_',' ')}</option>)}</select></label><div className="presets">{([0,1] as const).map(days=><button key={days} className={localClock(asOf,timezone).slice(0,10)===relativeDayInput(days,timezone).slice(0,10)?'selected':''} title={days===0?'Evaluate at the current time in your selected timezone':'Evaluate tomorrow at the same local time'} disabled={busy} onClick={()=>chooseDay(days)}>{days===0?'Today':'Tomorrow'}</button>)}</div></div><button className="primary-button" title={savedRunId?'Return to the inbox to request new analysis':replay?'Load matching saved assessments without model requests':'Analyze visible conversations, reusing matching results. Use Analyze again on a conversation for a fresh model request.'} disabled={busy||syncing||!!savedRunId||loading||!filtered.length||(!config?.ready&&!replay)} onClick={()=>void analyze()}>{busy?<IconLoader2 className="spin" size={18}/>:<IconPlayerPlay size={18}/>} {busy?(jobPhase==='queued'?'Queued':`${progress.completed} / ${progress.total} assessed`):savedRunId?'Viewing saved run':`${replay?'Load saved':'Analyze visible'} (${filtered.length})`}</button></section>
      {savedRunId&&<div className="notice-banner" role="status"><span>Saved run · no model requests. {savedView?.provenance?.input_is_current===false?'Its original messages differ from the current conversation. ':''}The clock recomputes attention on those saved inputs.</span><button className="text-button" onClick={leaveSaved}>Return to live inbox</button><button className="text-button" onClick={()=>setSavedOpen(true)}>Browse saved runs</button></div>}
      {syncNotice&&<div className="notice-banner" role="status">{syncNotice}</div>}
      {error&&<div className="error-banner" role="alert"><IconInfoCircle size={18}/><span>{error}</span><button aria-label="Dismiss error" onClick={()=>setError('')}><IconX size={16}/></button></div>}
      {recovery&&<div className="notice-banner recovery-banner" role="status"><IconInfoCircle size={18}/><span>Saved analysis: {recovery.completed} of {recovery.total} complete. Pending work needs an explicit resume.</span><button className="text-button" disabled={busy} onClick={()=>void recover()}>Resume pending</button><button className="text-button" disabled={busy} onClick={()=>void recover(true)}>Dismiss</button></div>}
      {config&&!config.ready&&<div className="notice-banner"><IconInfoCircle size={18}/><span>{config.error} Saved assessments remain available.</span><button className="text-button" onClick={()=>setSavedOpen(true)}>Browse saved runs</button></div>}
      <div className="tier-strip" role="group" aria-label="Filter attention tiers"><button className={`tier-tab all ${filter==='all'?'active':''}`} onClick={()=>setFilter('all')}><span>All conversations</span><strong>{categoryThreads.filter(t=>t.status!=='not_started').length}</strong></button>{(Object.keys(TIERS) as Tier[]).map(tier=><button key={tier} onClick={()=>setFilter(tier)} className={`tier-tab ${tier.toLowerCase()} ${filter===tier?'active':''}`}><span><span className="status-dot"/>{TIERS[tier].label}</span><strong>{counts[tier]}</strong></button>)}</div>
      <div className={`workspace ${mobileDetail?'detail-open':''}`}>
        <section className="inbox-pane" aria-label="Conversations"><div className="inbox-toolbar"><div className="inbox-source"><select aria-label="Inbox source" value={source} disabled={busy} onChange={e=>changeSource(e.target.value as typeof source)}><option value="demo">Demo inbox</option><option value="long">Long conversations</option><option value="gmail">Gmail inbox</option></select><span>{analyzed} assessed</span></div>{source==='gmail'&&<button className="text-button" disabled={busy||syncing} onClick={()=>void syncLatest()}>{syncing?'Syncing...':'Sync replies'}</button>}<button className="icon-button" aria-label="Refresh inbox" disabled={busy} onClick={()=>void load(asOf)}><IconRefresh size={16}/></button></div><label className="search-box"><IconSearch size={17}/><input placeholder="Search conversations" aria-label="Search conversations" value={search} onChange={e=>setSearch(e.target.value)}/>{search&&<button aria-label="Clear search" onClick={()=>setSearch('')}><IconX size={15}/></button>}</label>
          {source==='gmail'&&<label className="sync-demo-choice"><input type="checkbox" aria-label="Keep demo conversations after sync" checked={keepDemos} disabled={busy||syncing} onChange={e=>setKeepDemos(e.target.checked)}/>Keep demo conversations after sync</label>}
          {source==='gmail'&&<div className="gmail-category-control"><label>Gmail label<select aria-label="Filter Gmail labels" value={gmailFilter} onChange={e=>{const value=e.target.value;setGmailFilter(value);setSelected(threads.find(t=>t.status!=='not_started'&&matchesGmailLabel(t,value))?.id||'');setMobileDetail(false)}}><option value="all">All imported · {threads.filter(t=>t.status!=='not_started').length}</option>{GMAIL_LABELS.map(label=><option key={label.id} value={label.id}>{label.name} · {threads.filter(t=>t.status!=='not_started'&&matchesGmailLabel(t,label.id)).length}</option>)}<option value="unknown">Labels not imported · {threads.filter(t=>t.status!=='not_started'&&!t.gmail_labels_complete).length}</option></select></label>{threads.some(t=>t.status!=='not_started'&&!t.gmail_labels_complete)&&<p>Re-import these conversations to load Gmail labels.</p>}<span>Filters this downloaded batch. Categories may overlap.</span></div>}
          <div className="inbox-controls"><label><span className="sr-only">Assessment filter</span><select aria-label="Assessment filter" value={filter} onChange={e=>setFilter(e.target.value as InboxFilter)}><option value="all">All assessments</option><option value="unassessed">Not assessed</option><option value="error">Analysis failed</option>{(Object.keys(TIERS) as Tier[]).map(t=><option key={t} value={t}>{t} / {TIERS[t].short}</option>)}</select></label><label><span className="sr-only">Sort conversations</span><select aria-label="Sort conversations" value={sort} onChange={e=>setSort(e.target.value as InboxSort)}><option value="attention">Attention first</option><option value="newest">Newest first</option><option value="deadline">Earliest deadline</option></select></label></div><div className="selection-controls"><label><input type="checkbox" aria-label="Select visible conversations" checked={!!filtered.length&&filtered.every(t=>checked.includes(t.id))} onChange={e=>setChecked(old=>e.target.checked?Array.from(new Set([...old,...filtered.map(t=>t.id)])):old.filter(id=>!filtered.some(t=>t.id===id)))}/>Select visible</label>{checked.length>0&&<><button className="text-button" onClick={()=>setChecked([])}>Clear</button><button className="text-button" disabled={busy||syncing||!!savedRunId||(!config?.ready&&!replay)} onClick={()=>void analyze(checked)}>Analyze {checked.length} selected</button></>}</div>
          {loading?<div className="pane-empty"><IconLoader2 className="spin"/><p>Reading the inbox…</p></div>:filtered.length===0?<div className="pane-empty"><IconInbox size={32}/><h3>No conversations here</h3><p>{config?.demo_workspace_visible===false&&source!=='gmail'?'Sample inboxes were cleared from the workspace. Their definitions and saved runs remain available.':'Try another filter, search, or evaluation time.'}</p>{config?.demo_workspace_visible===false&&source!=='gmail'&&<button className="text-button" onClick={()=>void restoreDemos().catch(e=>setError(e.message))}>Restore sample inboxes</button>}<button className="text-button" onClick={()=>{setFilter('all');setGmailFilter('all');setSearch('')}}>Clear filters</button></div>:<div className="thread-list" ref={inboxListRef} tabIndex={0} role="region" aria-label="Scrollable inbox">{filtered.map(thread=><div className="thread-entry" key={thread.id}><input className="thread-select" type="checkbox" aria-label={`Select ${thread.subject}`} checked={checked.includes(thread.id)} onChange={e=>setChecked(old=>e.target.checked?[...old,thread.id]:old.filter(id=>id!==thread.id))}/><button ref={!savedRunId&&visibleSelection===thread.id?selectedRowRef:undefined} className={`thread-row ${!savedRunId&&visibleSelection===thread.id?'selected':''}`} onClick={()=>choose(thread.id)} aria-pressed={!savedRunId&&visibleSelection===thread.id}><div className="company-avatar">{initials(thread.company)}</div><div className="thread-preview"><div className="thread-row-top"><strong>{thread.company}</strong><time>{thread.messages.length?shortDate(thread.messages.at(-1)!.sent_at):''}</time></div><div className="thread-subject">{thread.subject}</div>{source==='gmail'&&<GmailBadges ids={thread.gmail_label_ids} compact/>}<p>{thread.assessment?.summary||'Ready for a conversation assessment.'}</p><div className="thread-row-bottom">{thread.attention?<TierBadge tier={thread.attention.tier}/>:<span className={`unassessed ${thread.status==='error'?'failed':''}`}>{thread.status==='error'?'Analysis failed':'Not assessed'}</span>}{thread.attention&&<span className="owner-label">{thread.attention.open_items.some(i=>i.owner==='us')?'We owe a reply':thread.attention.saturated?'Pause outreach':thread.attention.open_items.length?'Waiting on them':'No open asks'}</span>}</div></div></button></div>)}</div>}
          <div className="inbox-footer"><IconShieldCheck size={15}/><span>Evidence grounded. Human decides.</span></div>
        </section>
        <section className="detail-pane" aria-label="Selected conversation">
          {current?<><div className="detail-header"><button className="mobile-back text-button" onClick={()=>setMobileDetail(false)}><IconChevronLeft size={17}/>Inbox</button><div className="detail-company"><div><div className="company-line">{current.company}</div><h2>{current.subject}</h2><p>{current.contact} <span>↔</span> {current.id.startsWith('gmail-')?'Our mailbox':SAMPLE_MAILBOX_NAME} <span>·</span> {current.messages.length} messages</p>{source==='gmail'&&<GmailBadges ids={current.gmail_label_ids}/>}{(current.ingestion_source==='sample'||current.id.startsWith('gmail-'))&&<span className="source-provenance">{current.ingestion_source==='sample'?'Simulated account-to-account sample':'Imported from Gmail'}</span>}</div></div>{current.provenance&&<div className="assessment-context" aria-label="Assessment source"><div><span className="assessment-origin">{savedRunId?'Saved run · read-only':'Saved assessment'}</span><span>{current.provenance.model}</span><time dateTime={current.provenance.created_at}>Run {formatTime(current.provenance.created_at,true)}</time></div>{!savedRunId&&<button className="text-button" aria-label="Analyze this conversation again" title={replay?'Load a matching saved result without calling a model':'Request a fresh model assessment for the visible conversation'} disabled={busy||current.status==='not_started'||(!config?.ready&&!replay)} onClick={()=>void analyze([current.id],!replay)}><IconRefresh size={14}/>{replay?'Reload saved':'Analyze again'}</button>}</div>}</div>
          <div className="detail-scroll" ref={detailScrollRef} tabIndex={0} role="region" aria-label="Scrollable assessment and conversation">
            {current.status==='not_started'?<div className="pane-empty"><IconClock size={32}/><h3>This conversation hasn't started yet</h3><p>Move the evaluation time forward to see its messages.</p></div>:<>
            {current.provenance?.fallback&&<details className="fallback-notice"><summary><IconInfoCircle size={16}/><span>Analyzed with {current.provenance.model}</span><span className="fallback-toggle">Fallback details</span></summary><div><p>{current.provenance.fallback.from_model} could not produce an accepted assessment: {current.provenance.fallback.reason}</p><p>The local fallback passed the same evidence checks. The primary failure remains in analysis history.</p></div></details>}
            {current.attention&&current.assessment?<section className={`assessment-panel ${current.attention.tier.toLowerCase()}`}><div className="assessment-heading"><TierBadge tier={current.attention.tier}/><span className="assessment-state">{current.assessment.lifecycle} · {current.assessment.buyer_intent} intent</span></div><h3>{TIERS[current.attention.tier].label}</h3><p className="assessment-summary">{current.assessment.summary}</p>{current.assessment.reason&&<details className="model-reason"><summary>Model explanation</summary><p>{current.assessment.reason}</p></details>}<div className="why-block"><h4>Why this attention level</h4>{current.attention.reasons.map((reason,i)=><p key={i}><span className="reason-dot"/>{reason}</p>)}{current.attention.evidence_message_ids.length>0&&<button className="evidence-link" onClick={()=>showEvidence(current.attention!.evidence_message_ids)}>View supporting messages <IconArrowUpRight size={15}/></button>}</div><div className="next-action"><span className="action-icon"><IconArrowRight size={18}/></span><div><h4>Next move</h4><p>{current.attention.next_action}</p></div></div></section>:<section className="assessment-empty"><div className="empty-intelligence"><IconMail size={27}/></div><div><h3>{current.status==='error'?'Assessment needs a retry':'Start with the conversation'}</h3><p>{current.error||'Read the full thread, uncover open obligations, and see what needs attention.'}</p><button className="text-button" disabled={busy||!!savedRunId||(!config?.ready&&!replay)} onClick={()=>void analyze([current.id])}>{busy?'Assessing…':'Analyze this conversation'}<IconArrowRight size={16}/></button></div></section>}
            {current.attention&&current.attention.open_items.length>0&&<section className="open-items"><div className="section-label"><h3>Open obligations</h3><span>{current.attention.open_items.length}</span></div>{current.attention.open_items.map((item,i)=><div className="obligation-row" key={i}><div className={`obligation-marker ${item.overdue?'overdue':''}`}><IconClock size={16}/></div><div><strong>{item.description}</strong><p>{item.owner==='us'?'Our side':'Prospect'}{item.due_at?` · ${item.overdue?'Overdue since':item.due_today?'Expected today:':'Due'} ${formatTime(item.due_at)}`:item.deadline?' · Date needs clarification':' · No explicit deadline'}</p>{item.deadline&&<span className="raw-date">“{item.deadline.expression}” · {item.due_at?'resolved from source message':'needs date clarification'}</span>}<EvidenceSupport item={item} onEvidence={showEvidence}/></div><button className="evidence-icon icon-button" aria-label={`Show evidence for ${item.description}`} onClick={()=>showEvidence(item.evidence_message_ids)}><IconArrowUpRight size={17}/></button></div>)}</section>}
            {current.resolved_items?.length>0&&<details className="resolved-history"><summary>Resolved obligations <span>{current.resolved_items.length}</span></summary>{current.resolved_items.map((item,i)=><div className="resolved-entry" key={item.obligation_id||i}><strong>{item.description}</strong><p className="resolution-label">{item.resolution_status==='fulfilled'?'Fulfilled':'Cancelled'} · {item.owner==='us'?'Our side':'Prospect'}</p><blockquote>{item.resolution_evidence.quote}</blockquote><button className="text-button" onClick={()=>showEvidence([item.resolution_evidence.message_id])}>View resolution email <IconArrowUpRight size={15}/></button><EvidenceSupport item={item} onEvidence={showEvidence}/></div>)}</details>}
            {current.assessment&&current.assessment.recommendations.length>0&&<section className="recommendations"><div className="section-label"><h3>Worth considering</h3><span className="advisory-label">Advisory</span></div>{current.assessment.recommendations.map((rec,i)=><div key={i} className="advisory-row"><IconArrowRight size={16}/><p>{rec.description}</p><button className="icon-button" aria-label={`Show recommendation evidence ${i+1}`} onClick={()=>showEvidence(rec.evidence_message_ids)}><IconArrowUpRight size={16}/></button></div>)}</section>}
            {current.attention&&current.attention.notes.length>0&&<details className="assumptions"><summary><IconInfoCircle size={15}/>Assumptions and ambiguity ({current.attention.notes.length})</summary>{current.attention.notes.map((note,i)=><p key={i}>{note}</p>)}</details>}
            <ReviewTools key={`${current.id}:${savedRunId||'live'}`} thread={current} asOf={asOf} timezone={timezone} onEvidence={showEvidence}/>
            <section className="conversation"><div className="section-label"><h3>Conversation</h3><span>Chronological · {timezone}</span></div>{current.messages.map(message=><MessageView key={message.id} message={message} mailboxAlias={current.id.startsWith('gmail-')?undefined:SAMPLE_MAILBOX_NAME} highlighted={highlight.includes(message.id)}/> )}</section>
            {composer?<section className="composer"><div className="composer-heading"><h3>Simulate a message</h3><button className="icon-button" aria-label="Close composer" onClick={()=>setComposer(false)}><IconX size={18}/></button></div><div className="segmented"><button className={direction==='outbound'?'selected':''} onClick={()=>setDirection('outbound')}>From us</button><button className={direction==='inbound'?'selected':''} onClick={()=>setDirection('inbound')}>From prospect</button></div><label><span className="sr-only">Simulated message body</span><textarea aria-label="Simulated message body" placeholder={direction==='outbound'?'Answer the missing question or deliver the promised item…':'Add a prospect response…'} value={reply} onChange={e=>setReply(e.target.value)} autoFocus rows={4}/></label><input className="attachment-input" aria-label="Attachment names separated by commas" placeholder="Attachment names, separated by commas (optional)" value={attachments} onChange={e=>setAttachments(e.target.value)}/><div className="composer-footer"><span>Added at {formatTime(asOf)}. Demo only.</span><button className="primary-button small" disabled={!reply.trim()||busy} onClick={()=>void send()}><IconSend size={16}/>Add message</button></div></section>:!savedRunId&&!current.id.startsWith('gmail-')&&<button className="simulate-button" disabled={busy||replay} onClick={()=>setComposer(true)}><IconSend size={17}/>Simulate a reply<span>See how the assessment changes</span><IconArrowRight size={17}/></button>}
            {current.provenance&&<div className="provenance"><IconCheck size={14}/><span>{savedRunId||replay?'Saved actual run':'Actual model run'} · {current.provenance.model}{current.provenance.fallback?' · fallback':''} · {formatTime(current.provenance.created_at,true)} · {(current.provenance.duration_ms/1000).toFixed(1)}s</span></div>}
            </>}
          </div></>:<div className="pane-empty"><IconInbox size={32}/><h3>{filtered.length?'Select a conversation':'No matching conversation'}</h3><p>{filtered.length?'Its assessment and supporting messages appear here.':'Clear the inbox filters or change your search to see a conversation.'}</p></div>}
        </section>
      </div>
      {busy&&progress.total>0&&<div className="progress-track" role="progressbar" aria-valuenow={progress.completed} aria-valuemax={progress.total} aria-valuemin={0} aria-label="Inbox analysis progress"><div style={{width:`${progress.completed/progress.total*100}%`}}/></div>}
    </main>
    <dialog ref={helpRef} className="help-dialog" onCancel={()=>setHelp(false)}><div className="dialog-header"><h2>Meaning from the model.<br/>Timing from code.</h2><button className="icon-button" aria-label="Close explanation" onClick={()=>setHelp(false)}><IconX size={20}/></button></div><p>This demo reads full conversations, finds unresolved asks and promises, and uses a small deterministic policy to decide what needs attention.</p><ol><li><strong>Read.</strong> The configured model extracts obligations with source message IDs.</li><li><strong>Resolve.</strong> Code interprets raw date phrases from the timestamp of the source email.</li><li><strong>Prioritize.</strong> Timing, ownership, and explicit business signals determine T1–T4.</li><li><strong>Inspect.</strong> Follow each flag back to its message. Advice stays separate from obligations.</li></ol><p>Today uses the current time in your selected timezone; Tomorrow uses the same local time on the next date. The calendar accepts any date and time. For Northstar’s fixed example, compare October 8 at 15:00 with October 9 at 10:00 and 18:00 in Asia/Kolkata. Add a simulated message, then analyze again to test a reply.</p><div className="dialog-note">Dates display in {timezone}. Date-only promises are due at 17:00; contact pauses end at 09:00 in the stated or source zone. Missing sender zones use your selected fallback. Replay is available only for actual saved model outputs. No email is sent.</div><div className="dialog-tools"><label className="replay-control"><input type="checkbox" checked={replay} disabled={busy||(!replay&&!config?.replay_available)} onChange={e=>{if(e.target.checked){setHelp(false);setSavedOpen(true)}else leaveSaved()}}/>Use saved runs</label><button className="text-button" disabled={busy} onClick={()=>{setHelp(false);setSavedOpen(true)}}>Browse demos & saved runs</button><button className="text-button" disabled={busy} onClick={()=>void restoreDemos().then(()=>setHelp(false)).catch(e=>setError(e.message))}>Restore samples</button><button className="text-button" disabled={busy||source==='gmail'} onClick={()=>void reset()}>Reset demo</button></div></dialog><SavedRunsPanel open={savedOpen} onClose={()=>setSavedOpen(false)} onRun={openSavedRun} onDemo={restoreDemos}/><QueuePanel open={queueOpen} onClose={()=>setQueueOpen(false)} onJob={job=>{if(job.task!=='draft')beginJob(job)}} threads={threads}/><GmailPanel keepDemos={keepDemos} onKeepDemos={setKeepDemos} open={gmailOpen} onClose={()=>setGmailOpen(false)} onImported={()=>{changeSource('gmail');void load(new Date().toISOString(),'gmail');void request<Config>('/config').then(setConfig).catch(e=>setError(e.message))}}/>
  </div>
}

function MessageView({message,highlighted,mailboxAlias}:{message:Message;highlighted:boolean;mailboxAlias?:string}){
  const sender=message.direction==='outbound'&&mailboxAlias?mailboxAlias:message.sender
  return <article id={`message-${message.id}`} className={`message ${message.direction} ${highlighted?'highlighted':''}`}><div className="message-header"><div className={`message-avatar ${message.direction==='outbound'?'seller':''}`}>{initials(sender)}</div><div className="message-author"><strong>{sender}</strong><span>{message.direction==='outbound'?'Our side':message.direction==='internal'?'Internal':'External contact'}{message.simulated?' · Simulated':''}</span></div><time dateTime={message.sent_at}>{formatTime(message.sent_at)}</time></div>{message.recipients?.length&&<div className="message-recipients">To: {message.recipients.join(', ')}</div>}<p>{message.body}</p>{message.attachments.length>0&&<div className="attachments">{message.attachments.map(name=><span key={name}><IconPaperclip size={14}/>{name}</span>)}</div>}{highlighted&&<div className="source-label"><IconCheck size={13}/>Supporting evidence</div>}</article>
}

function EvidenceSupport({item,onEvidence}:{item:Obligation;onEvidence:(ids:string[])=>void}){
  if(!item.action_evidence&&!item.ownership_evidence)return null
  const evidence=[['Original action',item.action_evidence],['Ownership',item.ownership_evidence],['Explicit urgency',item.urgency_evidence]] as const
  return <details className="evidence-support"><summary>Source wording</summary>{evidence.map(([label,quote])=>quote&&<div key={label}><span>{label}</span><blockquote>{quote.quote}</blockquote><button className="text-button" onClick={()=>onEvidence([quote.message_id])}>View source email <IconArrowUpRight size={14}/></button></div>)}</details>
}

function GmailBadges({ids,compact=false}:{ids?:string[]|null;compact?:boolean}){
 const labels=gmailBadges(ids)
 if(!labels.length)return null
 return <div className="gmail-source-tags" aria-label="Gmail source labels" title={`Gmail labels: ${labels.map(l=>l.name).join(', ')}`}>
  {(compact?labels.slice(0,2):labels).map(label=><span key={label.id}>{label.name}</span>)}
  {compact&&labels.length>2&&<span>+{labels.length-2}</span>}
 </div>
}
