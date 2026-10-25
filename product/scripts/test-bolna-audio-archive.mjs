import test from 'node:test';
import assert from 'node:assert/strict';
import {appendBolnaArchiveAudio,bolnaAssistantTextAtTurn} from './bolna-audio-archive.mjs';

test('consecutive assistant audio bouts form one archived spoken turn',()=>{
 const archive=[];
 appendBolnaArchiveAudio(archive,'assistant',Buffer.alloc(8,1).toString('base64'));
 appendBolnaArchiveAudio(archive,'assistant',Buffer.alloc(10,2).toString('base64'));
 assert.equal(archive.length,1);
 const pcm=Buffer.from(archive[0].pcm_base64,'base64');
 assert.equal(pcm.length,8+1600+10);
 assert.deepEqual([...pcm.subarray(0,8)],[1,1,1,1,1,1,1,1]);
 assert.ok(pcm.subarray(8,1608).every(sample=>sample===0));
 assert.deepEqual([...pcm.subarray(1608)],[2,2,2,2,2,2,2,2,2,2]);
});

test('participant audio keeps the next assistant turn separate',()=>{
 const archive=[];
 appendBolnaArchiveAudio(archive,'assistant',Buffer.alloc(8,1).toString('base64'));
 appendBolnaArchiveAudio(archive,'participant',Buffer.alloc(8,2).toString('base64'));
 appendBolnaArchiveAudio(archive,'assistant',Buffer.alloc(8,3).toString('base64'));
 assert.deepEqual(archive.map(turn=>turn.speaker),['assistant','participant','assistant']);
});

test('provider transcript assistant turns stay aligned without assigning a later closing early',()=>{
 const transcript='assistant: Hi, I am Claim911. What is holding things up?\nuser: Insurance is pending.\nassistant: Let me check the case record.\nassistant: Thanks, I understand. Claim911 will check with the hospital and insurer, then show you what they confirm.';
 assert.equal(bolnaAssistantTextAtTurn(transcript,0),'Hi, I am Claim911. What is holding things up?');
 assert.equal(bolnaAssistantTextAtTurn(transcript,1),'Let me check the case record.');
 assert.match(bolnaAssistantTextAtTurn(transcript,2),/^Thanks, I understand/);
 assert.equal(bolnaAssistantTextAtTurn(transcript,-1),null);
});
