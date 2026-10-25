import {test} from 'node:test';
import assert from 'node:assert/strict';
import {BoundedSpeechCapture} from './bounded-speech-capture.mjs';

test('a long utterance is captured losslessly before its beginning leaves a short ring',async()=>{
 const source=Buffer.alloc(32000*32);for(let i=0;i<source.length;i++)source[i]=i%251;
 let clock=0;const windows=[];
 const capture=new BoundedSpeechCapture({startMs:0,take:async w=>{
  assert.ok(w.start_ms>=clock-20000);assert.ok(w.end_ms-w.start_ms<=8000);windows.push(w);
  return source.subarray(w.start_ms*32,w.end_ms*32).toString('base64');}});
 for(clock=1000;clock<=32000;clock+=1000)await capture.snapshot(clock);
 const joined=await capture.snapshot(32000,true);
 assert.deepEqual(Buffer.from(joined,'base64'),source);
 assert.equal(windows.length,4);
});

test('oversized turns and incomplete snapshots fail without provider use',async()=>{
 const capture=new BoundedSpeechCapture({startMs:0,take:async()=>Buffer.alloc(10).toString('base64')});
 await assert.rejects(capture.snapshot(8000),/incomplete/);
 await assert.rejects(capture.snapshot(40001),/bounded/);
});
