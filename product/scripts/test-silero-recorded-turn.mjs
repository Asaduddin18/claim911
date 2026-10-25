import {readFile} from 'node:fs/promises';
import assert from 'node:assert/strict';
import {createSileroVad} from './silero-vad-worker.mjs';

const path=process.env.CLAIM911_CAPTURED_PCM;
if(!path)throw new Error('An existing synthetic PCM recording is required.');
const pcm=await readFile(path);assert.ok(pcm.length>32000&&pcm.length<=640000);
const worker=await createSileroVad();
try{
 const result=await worker.analyze(pcm.toString('base64'));
 const speaking=result.events.findIndex(event=>event.state==='SPEAKING');
 const ended=result.events.slice(speaking+1).find(event=>event.state==='QUIET');
 assert.ok(speaking>=0&&ended,'The recorded assistant must have a detected completed speech turn.');
 assert.ok(ended.audio_ms<8000,'The opening must finish before the comfort-noise tail or later reprompt.');
 console.log(JSON.stringify({passed:true,...worker.provenance,first_turn_end_ms:ended.audio_ms,events:result.events}));
}finally{await worker.close();}
