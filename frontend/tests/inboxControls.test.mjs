import test from 'node:test'
import assert from 'node:assert/strict'
import {visibleThreads} from '../src/inboxControls.ts'
import * as controls from '../src/inboxControls.ts'
const row=(id,status,tier,date,due=null)=>({id,status,company:id,subject:id,contact:'A',messages:[{sent_at:date}],assessment:null,attention:tier?{tier,open_items:due?[{due_at:due}]:[]}:null})
const rows=[row('old','analyzed','T1','2026-01-01'),row('new','analyzed','T3','2026-01-03','2026-01-05'),row('failed','error',null,'2026-01-02'),row('fresh','unassessed',null,'2026-01-04'),row('future','not_started',null,'2026-01-06')]
test('errors and unassessed are independent filters; future mail stays hidden',()=>{assert.deepEqual(visibleThreads(rows,'error','','attention').map(t=>t.id),['failed']);assert.deepEqual(visibleThreads(rows,'unassessed','','attention').map(t=>t.id),['fresh']);assert.equal(visibleThreads(rows,'all','','attention').length,4)})
test('newest and deadline sort place missing dates last, search works',()=>{assert.equal(visibleThreads(rows,'all','','newest')[0].id,'fresh');assert.equal(visibleThreads(rows,'all','','deadline')[0].id,'new');assert.deepEqual(visibleThreads(rows,'all',' OLD ','attention').map(t=>t.id),['old'])})
test('selection survives sorting while the conversation is still visible',()=>{
 assert.equal(controls.selectedThreadId(visibleThreads(rows,'all','','newest'),'old'),'old')
})
test('a filter or search hiding the selection selects its first visible result',()=>{
 assert.equal(controls.selectedThreadId(visibleThreads(rows,'T3','','attention'),'old'),'new')
 assert.equal(controls.selectedThreadId(visibleThreads(rows,'all','failed','attention'),'old'),'failed')
})
test('empty results clear the detail selection and a new source selects a visible conversation',()=>{
 assert.equal(controls.selectedThreadId(visibleThreads(rows,'all','no match','attention'),'old'),'')
 assert.equal(controls.selectedThreadId([rows[1]],'other-account-thread'),'new')
})
