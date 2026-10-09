import {useEffect,useRef,useState} from 'react'
import {IconLoader2,IconX} from '@tabler/icons-react'
import {request} from './api'
import {GMAIL_SEARCHES as SEARCHES,includesSpamTrash} from './gmailLabels'
interface ImportResult {id:string;status:string;phase?:string;fetched:number;total_threads?:number;selected?:number;imported:number;skipped:number;thread_ids:string[];errors:{thread_id:string;error:string}[];error?:string;capped?:boolean}
interface Status {connected:boolean;connecting:boolean;credentials_present:boolean;account:string|null;accounts?:{id:string;email:string;active:boolean}[];error:string|null;importing?:boolean;last_import?:ImportResult|null}
export default function GmailPanel({open,onClose,onImported,keepDemos,onKeepDemos}:{open:boolean;onClose:()=>void;onImported:()=>void;keepDemos:boolean;onKeepDemos:(value:boolean)=>void}){
 const dialog=useRef<HTMLDialogElement>(null)
 const [status,setStatus]=useState<Status|null>(null),[query,setQuery]=useState('in:inbox'),[scope,setScope]=useState('inbox')
 const [includeSpamTrash,setIncludeSpamTrash]=useState(false)
 const [limit,setLimit]=useState(20),[all,setAll]=useState(false),[selection,setSelection]=useState<'threads'|'messages'>('threads')
 const [working,setWorking]=useState(false),[error,setError]=useState(''),[notice,setNotice]=useState('')
 const busy=working||!!status?.importing||!!status?.connecting,last=status?.last_import
 useEffect(()=>{
  if(!open){dialog.current?.close();return}
  dialog.current?.showModal();let cancelled=false
  const refresh=()=>request<Status>('/gmail/status').then(v=>{if(!cancelled)setStatus(v)}).catch(e=>{if(!cancelled)setError(e.message)})
  void refresh();const timer=window.setInterval(()=>void refresh(),1500)
  return()=>{cancelled=true;clearInterval(timer)}
 },[open])
 async function act(action:'connect'|'import'|'disconnect'|'sync'){
  setWorking(true);setError('');setNotice('')
  try{
   if(action==='sync'){const r=await request<ImportResult & {unchanged:number}>('/gmail/sync',{method:'POST',body:JSON.stringify({keep_demos:keepDemos})});setNotice(`${r.fetched} checked; ${r.imported} updated; ${r.unchanged} unchanged; ${r.skipped} skipped. Analyze updated conversations separately.`);setStatus(await request<Status>('/gmail/status'));onImported()}else if(action==='import'){
    const r=await request<ImportResult>('/gmail/import',{method:'POST',body:JSON.stringify({query,limit:all?null:limit,selection:all?'threads':selection,include_spam_trash:includeSpamTrash,keep_demos:keepDemos})})
    setNotice(`Imported ${r.imported} complete conversations${r.skipped?`; ${r.skipped} skipped`:''}. Analysis has not started.${r.capped?' The 5,000-thread limit was reached; narrow the search to continue.':''}`)
    setStatus(await request<Status>('/gmail/status'));onImported()
   }else{
    setStatus(await request<Status>(`/gmail/${action}`,{method:'POST'}))
    if(action==='connect'){setNotice('Account connected. Choose a search scope and import conversations.');onImported()}
    if(action==='disconnect'){setNotice('Connection and imported Gmail data cleared locally.');onImported()}
   }
  }catch(e){setError(e instanceof Error?e.message:'Gmail operation failed.')}finally{setWorking(false)}
 }
 async function selectAccount(account_id:string){
  setWorking(true);setError('');setNotice('')
  try{const next=await request<Status>('/gmail/account',{method:'POST',body:JSON.stringify({account_id})});setStatus(next);setNotice(`Switched to ${next.account}. Choose a scope and import, or sync this account's saved batch.`);onImported()}
  catch(e){setError(e instanceof Error?e.message:'Could not switch Gmail account.')}
  finally{setWorking(false)}
 }
 return <dialog ref={dialog} className="help-dialog gmail-dialog" onCancel={e=>{if(busy)e.preventDefault();else onClose()}}>
  <div className="dialog-header"><h2>Your Gmail inbox</h2><button className="icon-button" aria-label="Close Gmail settings" disabled={busy} onClick={onClose}><IconX size={20}/></button></div>
  <p>Read selected conversations from a real or test account. Inbox Desk cannot send, modify, or delete anything in Gmail.</p>
  {!status?.connected&&<ol className="gmail-setup"><li>Enable Gmail API and configure OAuth consent.</li><li>Add your Gmail address as a test user.</li><li>Save a Desktop OAuth client as <code>runtime/gmail/credentials.json</code>.</li><li>Connect and approve the read-only permission.</li></ol>}
  <div className="gmail-status">{status?.connected?`Connected · ${status.account||'Gmail'}`:status?.credentials_present?'OAuth client file found. Ready to connect.':'Waiting for Desktop OAuth client JSON.'}</div>
  {!!status?.accounts?.length&&<div className="gmail-import-controls"><label>Connected account<select aria-label="Connected Gmail account" value={status.accounts.find(a=>a.active)?.id||''} disabled={busy} onChange={e=>void selectAccount(e.target.value)}>{!status.accounts.some(a=>a.active)&&<option value="" disabled>Select a connected account</option>}{status.accounts.map(a=><option key={a.id} value={a.id}>{a.email}</option>)}</select></label></div>}
  {status?.connected&&status.accounts!==undefined&&<div className="dialog-tools"><button className="text-button" disabled={busy||!status.credentials_present} onClick={()=>void act('connect')}>Add or change Gmail account</button><span>Google opens an account chooser. Existing connections and mail are retained.</span></div>}
  {error&&<p className="gmail-error" role="alert">{error}</p>}{status?.error&&<p className="gmail-error">{status.error}</p>}{notice&&<p role="status">{notice}</p>}
  {!status?.connected?<div className="dialog-tools"><button className="text-button" disabled={busy} onClick={()=>void request<Status>('/gmail/status').then(setStatus).catch(e=>setError(e.message))}>Refresh settings</button><button className="primary-button" disabled={busy||!status?.credentials_present} onClick={()=>void act('connect')}>{busy?'Authorize in your browser…':'Connect Gmail'}</button></div>:<>
   <div className="gmail-import-controls">
    <label>Search scope<select aria-label="Gmail import scope" value={scope} disabled={busy} onChange={e=>{setScope(e.target.value);setIncludeSpamTrash(includesSpamTrash(e.target.value));if(SEARCHES[e.target.value])setQuery(SEARCHES[e.target.value])}}><option value="inbox">Inbox · all categories</option><option value="primary">Primary inbox</option><option value="social">Social</option><option value="promotions">Promotions</option><option value="updates">Updates</option><option value="forums">Forums</option><option value="spam">Spam</option><option value="trash">Trash</option><option value="allmail">All mail · excluding Spam and Trash</option><option value="week">Inbox · last 7 days</option><option value="month">Inbox · last 30 days</option><option value="quarter">Inbox · last 90 days</option><option value="label">Test label</option><option value="custom">Custom search</option></select></label>
    <label>Gmail search<input aria-label="Gmail search query" value={query} disabled={busy} onChange={e=>{setQuery(e.target.value);setScope('custom')}}/></label>
    <div className="gmail-count-controls"><label>Match<select aria-label="Gmail import selection" value={all?'threads':selection} disabled={busy||all} onChange={e=>setSelection(e.target.value as 'threads'|'messages')}><option value="threads">Full conversations</option><option value="messages">Messages → full conversations</option></select></label><label>{selection==='messages'&&!all?'Messages to match':'Conversations to match'}<input type="number" aria-label="Gmail import count" min={1} max={500} value={limit} disabled={busy||all} onChange={e=>setLimit(Number(e.target.value))}/></label></div>
<label className="gmail-all"><input type="checkbox" aria-label="Keep samples after Gmail import or sync" checked={keepDemos} disabled={busy} onChange={e=>onKeepDemos(e.target.checked)}/>Keep demo conversations after import or sync</label><p className="dialog-note">Uncheck to clear sample inboxes from this workspace after a successful import or sync. The sample code and saved runs are retained; Restore samples in the info menu brings them back.</p>
    <label className="gmail-all"><input type="checkbox" aria-label="Include Spam and Trash" checked={includeSpamTrash} disabled={busy} onChange={e=>setIncludeSpamTrash(e.target.checked)}/>Include Spam and Trash in search results</label>
    <label className="gmail-all"><input type="checkbox" aria-label="Import all matching conversations" checked={all} disabled={busy} onChange={e=>setAll(e.target.checked)}/>All matching conversations <span>Up to 5,000</span></label>
   </div>
   <p className="dialog-note">Category presets use Gmail’s own labels. They select matching messages or threads; the complete conversation is downloaded, including replies in other categories. Spam and Trash are excluded unless enabled. Count selects Gmail search results. Complete histories can include more messages or older dates. Matching several messages in one conversation downloads it once. Imported text stays local until you choose Analyze.</p>
   <p className="quota-note">Google's current default: 6,000 quota units/user/minute; 40 units per full thread. Imports are paced below that rate and retry temporary errors. Project limits may differ. <a href="https://developers.google.com/workspace/gmail/api/reference/quota" target="_blank" rel="noreferrer">Google's quotas ↗</a></p>
   {last?.status==='running'&&<div className="import-progress" role="status"><IconLoader2 className="spin" size={16}/><span>{last.phase==='fetching'?`Downloading ${last.fetched} / ${last.total_threads} conversations`:last.phase==='listing'?`Finding conversations · ${last.selected||0} selected`:'Preparing import…'}{last.skipped?` · ${last.skipped} skipped`:''}</span></div>}
   {last&&['error','interrupted'].includes(last.status)&&<p className="gmail-error">{last.error}</p>}
   {!!last?.errors?.length&&<details className="import-errors"><summary>Skipped conversations ({last.errors.length})</summary>{last.errors.slice(0,10).map((e,i)=><p key={i}>{e.error}</p>)}{last.errors.length>10&&<p>Full details are retained in the local import record.</p>}</details>}
   <div className="dialog-tools"><button className="text-button" disabled={busy||!last?.thread_ids?.length} onClick={()=>void act('sync')}>Sync current batch</button><button className="text-button" disabled={busy} onClick={()=>void act('disconnect')}>Disconnect all & clear local mail</button><button className="primary-button" disabled={busy||!query.trim()||(!all&&(!Number.isInteger(limit)||limit<1||limit>500))} onClick={()=>void act('import')}>{busy&&<IconLoader2 className="spin" size={16}/>} {busy?'Working…':all?'Import all matches':'Import conversations'}</button></div>
  </>}
  <a className="gmail-doc-link" href="https://developers.google.com/workspace/gmail/api/quickstart/python" target="_blank" rel="noreferrer">Google's Gmail OAuth setup guide ↗</a>
 </dialog>
}
