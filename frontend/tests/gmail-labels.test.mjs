import test from 'node:test'
import assert from 'node:assert/strict'
import {GMAIL_SEARCHES,includesSpamTrash,matchesGmailLabel,gmailBadges} from '../src/gmailLabels.ts'

test('a mixed thread belongs to each source category without choosing one',()=>{
 const thread={gmail_label_ids:['CATEGORY_SOCIAL','CATEGORY_PROMOTIONS','UNREAD'],gmail_labels_complete:true}
 assert.equal(matchesGmailLabel(thread,'CATEGORY_SOCIAL'),true)
 assert.equal(matchesGmailLabel(thread,'CATEGORY_PROMOTIONS'),true)
 assert.equal(matchesGmailLabel(thread,'SPAM'),false)
 assert.deepEqual(gmailBadges(thread.gmail_label_ids).map(v=>v.name),['Social','Promotions','Unread'])
})
test('old mail is explicitly unknown and is never assumed Primary',()=>{
 assert.equal(matchesGmailLabel({},'unknown'),true)
 assert.equal(matchesGmailLabel({},'CATEGORY_PERSONAL'),false)
 assert.equal(matchesGmailLabel({gmail_label_ids:[],gmail_labels_complete:true},'unknown'),false)
 assert.deepEqual(gmailBadges(['Label_123']),[])
})
test('spam and trash presets request inclusion explicitly; ordinary scopes exclude them',()=>{
 assert.equal(GMAIL_SEARCHES.spam,'in:spam')
 assert.equal(GMAIL_SEARCHES.trash,'in:trash')
 assert.equal(includesSpamTrash('spam'),true)
 assert.equal(includesSpamTrash('trash'),true)
 assert.equal(includesSpamTrash('allmail'),false)
 assert.equal(includesSpamTrash('promotions'),false)
})
