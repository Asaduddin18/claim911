import test from 'node:test';
import assert from 'node:assert/strict';
import {createBackgroundAudioPump} from './background-audio-pump.mjs';
const delay=ms=>new Promise(resolve=>setTimeout(resolve,ms));

test('capture continues while a separate consumer waits, without concurrent drains',async()=>{
 let captured=0,active=0,maximum=0;
 const pump=createBackgroundAudioPump(async()=>{active++;maximum=Math.max(maximum,active);await delay(20);captured++;active--;},{intervalMs:5});
 await delay(160);pump.check();await pump.stop();
 assert.ok(captured>=2);assert.equal(maximum,1);
 const before=captured;await delay(30);assert.equal(captured,before);
});
test('capture errors are surfaced and never silently retried',async()=>{
 let calls=0;const pump=createBackgroundAudioPump(async()=>{calls++;throw new Error('Capture unavailable');},{intervalMs:5});
 await delay(30);assert.throws(()=>pump.check(),/Capture unavailable/);await pump.stop();assert.equal(calls,1);
});
