export const GMAIL_LABELS = [
  {id:'CATEGORY_PERSONAL',name:'Primary'}, {id:'CATEGORY_SOCIAL',name:'Social'},
  {id:'CATEGORY_PROMOTIONS',name:'Promotions'}, {id:'CATEGORY_UPDATES',name:'Updates'},
  {id:'CATEGORY_FORUMS',name:'Forums'}, {id:'SPAM',name:'Spam'}, {id:'TRASH',name:'Trash'},
  {id:'INBOX',name:'Inbox'}, {id:'UNREAD',name:'Unread'}, {id:'STARRED',name:'Starred'},
  {id:'IMPORTANT',name:'Important'}, {id:'SENT',name:'Sent'}, {id:'DRAFT',name:'Draft'},
] as const
export const GMAIL_SEARCHES:Record<string,string> = {
  inbox:'in:inbox',week:'in:inbox newer_than:7d',month:'in:inbox newer_than:30d',quarter:'in:inbox newer_than:90d',
  primary:'in:inbox category:primary',social:'category:social',promotions:'category:promotions',
  updates:'category:updates',forums:'category:forums',spam:'in:spam',trash:'in:trash',
  allmail:'-in:spam -in:trash',label:'label:autharva-test',
}
export const includesSpamTrash = (scope:string) => scope==='spam'||scope==='trash'
export function matchesGmailLabel(thread:{gmail_label_ids?:string[]|null;gmail_labels_complete?:boolean},filter:string){
  return filter==='all'||(filter==='unknown'?!thread.gmail_labels_complete:(thread.gmail_label_ids||[]).includes(filter))
}
export function gmailBadges(ids?:string[]|null){
  return GMAIL_LABELS.filter(label=>ids?.includes(label.id))
}
