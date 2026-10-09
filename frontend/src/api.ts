export async function request<T>(path:string, init?:RequestInit):Promise<T> {
  const response=await fetch(`/api${path}`,{...init,headers:{'Content-Type':'application/json',...init?.headers}})
  if(!response.ok){let detail='Request failed';try {detail=(await response.json()).detail || detail} catch {detail=`Request failed (${response.status})`} throw new Error(typeof detail==='string'?detail:JSON.stringify(detail))}
  return response.json()
}
let displayTimezone=Intl.DateTimeFormat().resolvedOptions().timeZone||'UTC'
export function detectedTimezone(){
  try{const saved=localStorage.getItem('autharva.timezone');if(saved){new Intl.DateTimeFormat('en',{timeZone:saved}).format(new Date());return saved}}catch{}
  return displayTimezone
}
export function setDisplayTimezone(zone:string){
  new Intl.DateTimeFormat('en',{timeZone:zone}).format(new Date())
  displayTimezone=zone
}
function clockParts(value:Date,zone:string){
  return Object.fromEntries(new Intl.DateTimeFormat('en-CA',{timeZone:zone,year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit',hourCycle:'h23'}).formatToParts(value).map(p=>[p.type,p.value]))
}
export function localClock(value:string,zone=displayTimezone){
  const parts=clockParts(new Date(value),zone)
  return `${parts.year}-${parts.month}-${parts.day}T${parts.hour}:${parts.minute}`
}
export function relativeDayInput(days:0|1,zone=displayTimezone,now=new Date()){
  const local=localClock(now.toISOString(),zone)
  const [year,month,day]=local.slice(0,10).split('-').map(Number)
  const date=new Date(Date.UTC(year,month-1,day+days)).toISOString().slice(0,10)
  return date+local.slice(10)
}
export function isoClock(value:string,zone=displayTimezone){
  const match=/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})(?::(\d{2}))?$/.exec(value)
  if(!match)throw new Error('Enter a valid date and time.')
  const [y,m,d,h,min,sec]=match.slice(1).map(v=>Number(v||0))
  const wall=Date.UTC(y,m-1,d,h,min,sec),check=new Date(wall)
  if(check.getUTCFullYear()!==y||check.getUTCMonth()!==m-1||check.getUTCDate()!==d||h>23||min>59||sec>59)throw new Error('Enter a valid date and time.')
  const offsets=new Set<number>()
  for(const shift of [-36,0,36]){
    const sample=new Date(wall+shift*3600000),p=clockParts(sample,zone)
    offsets.add(Date.UTC(+p.year,+p.month-1,+p.day,+p.hour,+p.minute,+p.second)-sample.getTime())
  }
  const candidates=[...offsets].map(offset=>new Date(wall-offset)).filter(candidate=>localClock(candidate.toISOString(),zone)===value.slice(0,16))
  if(candidates.length===0)throw new Error('This local clock time does not exist because of daylight saving. Choose another time.')
  if(candidates.length>1)throw new Error('This local clock time occurs twice because of daylight saving. Choose an unambiguous time.')
  return candidates[0].toISOString()
}
export function formatTime(value:string,full=false){return new Intl.DateTimeFormat('en-IN',{timeZone:displayTimezone,day:'numeric',month:'short',...(full?{year:'numeric' as const}:{}),hour:'numeric',minute:'2-digit'}).format(new Date(value))}
export function shortDate(value:string){return new Intl.DateTimeFormat('en-IN',{timeZone:displayTimezone,day:'numeric',month:'short'}).format(new Date(value))}
