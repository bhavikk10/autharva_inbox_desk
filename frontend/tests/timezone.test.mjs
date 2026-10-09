import test from 'node:test';
import assert from 'node:assert/strict';
import {localClock,isoClock} from '../src/api.ts';
import * as clock from '../src/api.ts';

test('Today and Tomorrow use the selected local date, including year rollover',()=>{
 assert.equal(typeof clock.relativeDayInput,'function');
 const now=new Date('2026-12-31T23:15:00Z');
 assert.equal(clock.relativeDayInput(0,'Pacific/Auckland',now),'2027-01-01T12:15');
 assert.equal(clock.relativeDayInput(1,'Pacific/Auckland',now),'2027-01-02T12:15');
 assert.equal(clock.relativeDayInput(1,'America/New_York',now),'2027-01-01T18:15');
});

test('Tomorrow preserves local clock time across daylight saving rather than adding 24 hours',()=>{
 assert.equal(typeof clock.relativeDayInput,'function');
 const beforeSpring=new Date('2026-03-07T15:30:00Z');
 assert.equal(isoClock(clock.relativeDayInput(1,'America/New_York',beforeSpring),'America/New_York'),'2026-03-08T14:30:00.000Z');
 const beforeFall=new Date('2026-10-31T14:30:00Z');
 assert.equal(isoClock(clock.relativeDayInput(1,'America/New_York',beforeFall),'America/New_York'),'2026-11-01T15:30:00.000Z');
 const beforeGap=new Date('2026-03-07T07:30:00Z');
 assert.throws(()=>isoClock(clock.relativeDayInput(1,'America/New_York',beforeGap),'America/New_York'),/does not exist/);
});

test('local wall clocks convert through their IANA daylight-saving rules',()=>{
 assert.equal(localClock('2026-10-09T19:00:00+05:30','America/New_York'),'2026-10-09T09:30');
 assert.equal(isoClock('2026-10-09T09:30','America/New_York'),'2026-10-09T13:30:00.000Z');
 assert.equal(isoClock('2026-12-09T09:30','America/New_York'),'2026-12-09T14:30:00.000Z');
 assert.equal(isoClock('2026-10-09T19:00','Asia/Kolkata'),'2026-10-09T13:30:00.000Z');
});
test('invalid dates and daylight-saving gaps or overlaps are not guessed',()=>{
 assert.throws(()=>isoClock('2026-03-08T02:30','America/New_York'),/does not exist/);
 assert.throws(()=>isoClock('2026-11-01T01:30','America/New_York'),/occurs twice/);
 assert.throws(()=>isoClock('2026-02-30T10:00','UTC'),/valid/);
});


test('invalid saved timezone falls back to the detected browser zone',async()=>{
  globalThis.localStorage={getItem:()=> 'Invalid/Zone'}
  const {detectedTimezone}=await import('../src/api.ts')
  assert.doesNotThrow(()=>new Intl.DateTimeFormat('en',{timeZone:detectedTimezone()}))
  delete globalThis.localStorage
})
