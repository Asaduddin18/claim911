import {chromium} from 'playwright';
import {spawn} from 'node:child_process';
import {createInterface} from 'node:readline';
import {createHash} from 'node:crypto';
import {chmod,mkdir,readFile,writeFile} from 'node:fs/promises';
import {dirname,resolve} from 'node:path';
import {installBolnaRemoteAudioTap} from './bolna-remote-audio-tap.mjs';
import {evaluateBolnaDialogue,parseBolnaTranscript,providerQuestionAtReply} from './bolna-dialogue-evaluation.mjs';
import {participantForRun} from './bolna-run-role.mjs';
import {appendBolnaArchiveAudio} from './bolna-audio-archive.mjs';
import {createSileroVad} from './silero-vad-worker.mjs';
import {createBackgroundAudioPump} from './background-audio-pump.mjs';
import {BoundedSpeechCapture} from './bounded-speech-capture.mjs';

const appUrl=process.env.CLAIM911_SANDBOX_BROWSER_URL||'http://127.0.0.1:3130/';
const sandboxProfilePath=process.env.CLAIM911_SANDBOX_PROFILE;
const providerProfilePath=process.env.CLAIM911_PROVIDER_PROFILE;
const reportPath=process.env.CLAIM911_REPORT_PATH;
const recordPath=process.env.CLAIM911_PARTICIPANT_RECORD;
let role=process.env.CLAIM911_PARTICIPANT_ROLE||'caregiver';
const requestedRunId=process.env.CLAIM911_RUN_ID||'';
const participantMode=process.env.CLAIM911_PARTICIPANT_MODE||'adaptive';
const parentRpc=process.env.CLAIM911_PARTICIPANT_RPC==='1';
const harnessCredential=process.env.CLAIM911_SANDBOX_HARNESS_TOKEN||'';
const archivePath=process.env.CLAIM911_ARCHIVE_PATH||'';
if(!['scenario-scripted','adaptive'].includes(participantMode))throw new Error('Unknown participant test mode.');
const icePolicy=process.env.CLAIM911_TEST_ICE_POLICY||'all';
if(!['all','relay'].includes(icePolicy))throw new Error('Unknown WebRTC test connection policy.');
const python=process.env.CLAIM911_PYTHON;
const chromePath=process.env.CLAIM911_CHROME_PATH||'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const participantTurnPath=new URL('../../scripts/bolna_participant_turn.py',import.meta.url).pathname;
const maxTurns=Math.min(12,Math.max(1,Number(process.env.CLAIM911_MAX_PARTICIPANT_TURNS||2)));
if(!sandboxProfilePath||!reportPath||(!parentRpc&&(!providerProfilePath||!python)))throw new Error('Private sandbox, report, and participant provider paths are required.');
if(parentRpc&&(!requestedRunId||!archivePath||!harnessCredential))throw new Error('Workflow RPC requires a selected run, scoped sandbox session and archive path.');
if(requestedRunId&&!/^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(requestedRunId))throw new Error('A valid sandbox run ID is required.');
const sandboxProfile=JSON.parse(await readFile(sandboxProfilePath,'utf8'));
if(sandboxProfile.environment!=='sandbox'||sandboxProfile.live_calls_enabled||sandboxProfile.bolna_api_key){
 throw new Error('Participant harness requires the isolated key-free, phone-disabled sandbox profile.');
}
let participantRecord=parentRpc?{synthetic:true,role:'caregiver'}:recordPath?JSON.parse(await readFile(recordPath,'utf8')):{synthetic:true,role:'caregiver',patient_id:'DEMO-PATIENT-84',
 known_facts:['medically cleared','deposit paid','hospital says insurance pending'],documents:[{kind:'deposit_receipt',ready:true}],deposit_inr:30000};
const rpcLines=parentRpc?createInterface({input:process.stdin,crlfDelay:Infinity}):null;
const rpcIterator=rpcLines?.[Symbol.asyncIterator]();
const result={provenance:'BOLNA_WEBRTC_ROLE_PARTICIPANT_HARNESS',participant_mode:participantMode,ice_transport_policy:icePolicy,synthetic:true,phone_dispatch:false,
 assistant:'Bolna',participant_role:role,participant_turn_limit:maxTurns,connected:false,ended:false,workflow_write_by_participant:false,
 checkpoint_eligible_from_participant:false,turns:[],errors:[]};
let browser,page,vad,audioPump,currentVolumeBout=null,sessionDeadline=Infinity;
const archiveAudio=[];
const bolnaVolumeBouts=[];
async function pumpSpeechBoundaries(){
 const pcm=await page.evaluate(()=>window.__claim911DrainVadPcm?.());
 if(pcm){
  const analysis=await vad.analyze(pcm);
  for(const event of analysis.events){
   if(event.state==='SPEAKING'){
    if(!currentVolumeBout){
     const start=Math.max(0,event.audio_ms-300);
     currentVolumeBout={started_at:event.audio_ms,detector:'SILERO_PIPECAT',capture:new BoundedSpeechCapture({startMs:start,
      take:w=>page.evaluate(window=>globalThis.__claim911TakeRemotePcm?.(window),w)})};
    }
    currentVolumeBout.quiet_since=null;
   }
   if(event.state==='QUIET'&&currentVolumeBout&&!currentVolumeBout.quiet_since){
    currentVolumeBout.quiet_since=Date.now();currentVolumeBout.quiet_audio_ms=event.audio_ms;
   }
  }
 }
 if(currentVolumeBout){
  const clock=await page.evaluate(()=>window.__claim911RemoteAudioClockMs?.());
  await currentVolumeBout.capture.snapshot(currentVolumeBout.quiet_audio_ms&&currentVolumeBout.quiet_since?currentVolumeBout.quiet_audio_ms:clock);
 }
 // Silero emits QUIET after 700 ms. Wait through short sentence pauses before
 // treating speech as a completed assistant turn.
 if(currentVolumeBout?.quiet_since&&Date.now()-currentVolumeBout.quiet_since>=1600){
  const bout={...currentVolumeBout,
   start_ms:Math.max(0,currentVolumeBout.started_at-300),end_ms:currentVolumeBout.quiet_audio_ms,
   duration_ms:currentVolumeBout.quiet_audio_ms-currentVolumeBout.started_at};
  bout.pcm_base64=await currentVolumeBout.capture.snapshot(bout.end_ms,true);
  delete bout.capture;
  if(!bout.pcm_base64||bolnaVolumeBouts.length>=40)throw new Error('Bounded assistant audio queue is unavailable.');
  bolnaVolumeBouts.push(bout);
  currentVolumeBout=null;
 }
}
function executeParticipant(args,{input,timeout,maxBuffer}){
 return new Promise((resolve,reject)=>{
  const child=spawn(python,args,{stdio:['pipe','pipe','pipe']});let stdout='',stderr='',settled=false;
  const finish=(error)=>{if(settled)return;settled=true;clearTimeout(timer);error?reject(error):resolve(stdout);};
  const timer=setTimeout(()=>{child.kill();finish(new Error('Participant process exceeded its time bound.'));},timeout);
  child.stdout.on('data',data=>{stdout+=data;if(Buffer.byteLength(stdout)>maxBuffer){child.kill();finish(new Error('Participant output exceeded its bound.'));}});
  child.stderr.on('data',data=>{if(stderr.length<8000)stderr+=data;});
  child.on('error',finish);child.on('close',code=>{if(code){const error=new Error('Participant process failed.');error.stderr=stderr;finish(error);}else finish();});
  child.stdin.on('error',()=>{});child.stdin.end(input);
 });
}
async function participantTurn(pcmBase64,history){
 const input=JSON.stringify({role,record:participantRecord,history,pcm_base64:pcmBase64})+'\n';
 const args=[participantTurnPath,'--provider-config',providerProfilePath];
 if(participantMode==='adaptive')args.push('--natural-response','--sandbox-config',sandboxProfilePath,'--run-id',result.run_id);
 try{
  const output=await executeParticipant(args,{
   input,encoding:'utf8',timeout:90000,maxBuffer:3_000_000,stdio:['pipe','pipe','pipe']
  });
  return JSON.parse(output);
 }catch(error){
  const safe=String(error?.stderr||'').match(/"safe_code"\s*:\s*"([A-Z_]+)"/)?.[1];
  throw new Error(safe||'Synthetic participant could not understand the assistant audio.');
 }
}
async function participantTurnFromParent(pcmBase64,turnIndex,assistantText){
 process.stdout.write(JSON.stringify({type:'assistant_audio',turn:turnIndex+1,role,pcm_base64:pcmBase64,
  ...(assistantText?{assistant_text:assistantText,assistant_text_source:'bolna_provider_transcript'}:{})})+'\n');
 let timeout;
 const next=await Promise.race([rpcIterator.next(),new Promise((_,reject)=>{
  timeout=setTimeout(()=>reject(new Error('The bounded synthetic voice session timed out.')),Math.max(1,sessionDeadline-Date.now()));
 })]).finally(()=>clearTimeout(timeout));
 if(next.done)throw new Error('The trusted workflow actor disconnected before replying.');
 let response;
 try{response=JSON.parse(next.value);}catch{throw new Error('The trusted workflow actor returned invalid data.');}
 if(response.type==='abort'&&response.role===role)
  throw new Error('The trusted participant stopped this conversation for review.');
 if(response.type==='continue_audio'&&response.role===role&&response.turn===turnIndex+1)return response;
 if(response.type==='end_call'&&response.role===role&&response.turn===turnIndex+1
  &&response.close_confirmed===true&&typeof response.report_saved==='boolean'
  &&typeof response.assistant_text==='string'&&response.assistant_text.trim())
  return response;
 if(response.type!=='participant_audio'||response.role!==role||!Number.isInteger(response.turn)||response.turn!==turnIndex+1
  ||!['live_audio_transcription','bolna_provider_transcript'].includes(response.question_source)
  ||typeof response.assistant_text!=='string'||!response.assistant_text.trim()
  ||typeof response.participant_text!=='string'||!response.participant_text.trim()
  ||typeof response.pcm_base64!=='string'||response.pcm_base64.length>4_266_668)
  throw new Error('The trusted workflow actor response did not match the active turn.');
 return response;
}
async function transcribeAssistant(pcmBase64,history){
 const input=JSON.stringify({role,record:participantRecord,history,pcm_base64:pcmBase64})+'\n';
 try{
  const output=await executeParticipant([participantTurnPath,'--provider-config',providerProfilePath,'--transcribe-only'],{
   input,encoding:'utf8',timeout:45000,maxBuffer:300_000,stdio:['pipe','pipe','pipe']
  });
  return JSON.parse(output);
 }catch(error){
  const safe=String(error?.stderr||'').match(/"safe_code"\s*:\s*"([A-Z_]+)"/)?.[1];
  throw new Error(safe||'Bolna assistant audio could not be transcribed.');
 }
}
async function preserveCapturedAssistantPcm(pcmBase64,turnIndex){
 const buffer=Buffer.from(pcmBase64,'base64'),samples=new Int16Array(buffer.buffer,buffer.byteOffset,buffer.byteLength/2);
 let sum=0,peak=0,activeWindows=0;
 for(let offset=0;offset<samples.length;offset+=320){
  const end=Math.min(samples.length,offset+320);let windowPower=0;
  for(let index=offset;index<end;index++){const sample=samples[index],absolute=Math.abs(sample);sum+=sample*sample;windowPower+=sample*sample;peak=Math.max(peak,absolute);}
  if(Math.sqrt(windowPower/Math.max(1,end-offset))/32768>0.003)activeWindows++;
 }
 const diagnosticPath=`${reportPath}.assistant-turn-${turnIndex+1}.pcm`;
 await writeFile(diagnosticPath,buffer,{mode:0o600});await chmod(diagnosticPath,0o600);
  return {sample_count:samples.length,duration_ms:Math.round(samples.length/16),
  rms:Number(Math.sqrt(sum/Math.max(1,samples.length))/32768).toFixed(5),
  peak:Number((peak/32768).toFixed(5)),active_20ms_windows:activeWindows,
  capture_source:result.assistant_audio_source||'unknown',diagnostic_path:diagnosticPath};
}
async function appRequest(path,method='GET',body,timeoutMs=15000){
 return page.evaluate(async({path,method,body,timeoutMs})=>{
  const response=await fetch(path,{method,headers:{'Content-Type':'application/json'},...(body===undefined?{}:{body:JSON.stringify(body)}),cache:'no-store',signal:AbortSignal.timeout(timeoutMs)});
  const value=await response.json().catch(()=>null);
  return {ok:response.ok,status:response.status,value};
 },{path,method,body,timeoutMs});
}
async function brokerExecution(runId,callId,executionId){
 if(!runId||!callId||!executionId)return null;
 const response=await appRequest(`/api/sandbox/runs/${runId}/conversations/${callId}/provider-execution`,'POST',{},4000);
 if(!response.ok)return null;
 const value=response.value;
 if(value.execution_id!==executionId||typeof value.status!=='string'||typeof value.transcript!=='string')return null;
 return value;
}
async function liveAudioStats(){
 return page.evaluate(async()=>{
  const rows=[];
  for(const [peer,pc] of (window.__claim911PeerConnections||[]).entries()){
   try{for(const stat of (await pc.getStats()).values()){
    if(['inbound-rtp','outbound-rtp'].includes(stat.type)&&stat.kind==='audio')rows.push({peer,type:stat.type,
     packets_received:stat.packetsReceived,packets_sent:stat.packetsSent,packets_lost:stat.packetsLost,
     bytes_received:stat.bytesReceived,bytes_sent:stat.bytesSent,total_samples:stat.totalSamplesReceived,
     concealed_samples:stat.concealedSamples,jitter:stat.jitter,audio_level:stat.audioLevel});
   }}catch{}
  }
  return rows;
 });
}
try{
 vad=await createSileroVad();result.turn_detector=vad.provenance;
 // Bolna owns the assistant. For each actual spoken turn, the role actor
 // transcribes that audio and answers from its synthetic role record. It never
 // selects a reply from a guessed or prewritten question category.
 browser=await chromium.launch({headless:true,executablePath:chromePath,args:[
  '--use-fake-ui-for-media-stream','--use-fake-device-for-media-stream','--autoplay-policy=no-user-gesture-required'
 ]});
 const context=await browser.newContext({permissions:['microphone'],serviceWorkers:'block',
  viewport:{width:1440,height:900},recordVideo:{dir:reportPath+'.video',size:{width:1440,height:900}}});
 page=await context.newPage();page.setDefaultTimeout(25000);
 result.screen_recording=await page.video().path();
 await page.addInitScript(policy=>{window.__claim911TestIcePolicy=policy;},icePolicy);
 await page.addInitScript(installBolnaRemoteAudioTap);
 page.on('response',async response=>{
  const pathname=new URL(response.url()).pathname;
  if(response.request().method()!=='POST')return;
  if(pathname.endsWith('/voice-session')){
   result.session_status=response.status();
   try{const body=await response.json();result.call_id=body?.call_id;result.provider_execution_id=body?.session?.run_id;result.transport=body?.transport;
    result.synthetic=body?.synthetic===true;result.phone_dispatch=body?.phone_dispatch;}
   catch{}
  }
 });
 await page.goto(appUrl,{waitUntil:'networkidle'});
 await page.getByRole('heading',{name:'A safe place to prove it.'}).waitFor();
 const login=await page.evaluate(async({credential,runId})=>{
  const response=await fetch('/api/sessions',{method:'POST',headers:{'Content-Type':'application/json'},
   body:JSON.stringify({role:'sandbox_harness',credential,run_id:runId}),cache:'no-store'});
  return {ok:response.ok,status:response.status};
 },{credential:harnessCredential,runId:requestedRunId});
 if(!login.ok)throw new Error('Sandbox session could not be created.');
 await page.reload({waitUntil:'networkidle'});
 const sandboxStatus=await appRequest('/api/sandbox/status');
 if(!sandboxStatus.ok)throw new Error('Sandbox sign-in did not grant sandbox-only access.');
 let run;
 if(requestedRunId){
  const selectedUrl=new URL(appUrl);selectedUrl.searchParams.set('run',requestedRunId);
  await page.goto(selectedUrl.toString(),{waitUntil:'networkidle'});
  const selected=await appRequest('/api/sandbox/runs/'+requestedRunId);
  if(!selected.ok||selected.value.id!==requestedRunId)
   throw new Error('The selected sandbox run is not ready for a Bolna conversation.');
  run=selected.value;result.run_selection='existing_sandbox_run';
  const expectedRole=participantForRun(run);
  if(process.env.CLAIM911_PARTICIPANT_ROLE&&process.env.CLAIM911_PARTICIPANT_ROLE!==expectedRole)
   throw new Error('The requested synthetic participant role does not match the selected checkpoint.');
  role=expectedRole;
  if(role!=='caregiver'&&!recordPath&&!parentRpc)throw new Error('A synthetic record scoped to the selected institution desk is required.');
  if(recordPath)participantRecord=JSON.parse(await readFile(recordPath,'utf8'));
 }else{
  const preparedResponse=page.waitForResponse(response=>response.request().method()==='POST'&&new URL(response.url()).pathname.endsWith('/api/sandbox/runs'),{timeout:15000});
  await page.getByRole('button',{name:'Prepare a scenario'}).click();
  const prepared=await preparedResponse;
  if(!prepared.ok())throw new Error('Fresh synthetic run could not be prepared.');
  run=await prepared.json();result.run_selection='new_smoke_run';
  await page.waitForFunction(()=>{
   const button=[...document.querySelectorAll('button')].find(item=>item.textContent.includes('Prepare a scenario'));
   return button&&!button.disabled&&document.querySelector('.run-detail');
  },null,{timeout:45000});
 }
 if(!requestedRunId&&role!=='caregiver')throw new Error('A new smoke run can contain only the caregiver intake role.');
 if(!parentRpc&&participantRecord.role!==role)throw new Error('The selected synthetic record belongs to a different participant role.');
 result.run_id=run.id;result.participant_role=role;
 const voice=page.getByRole('region',{name:'Bolna browser voice check'});await voice.waitFor({state:'visible'});
 await page.evaluate(()=>{
  const element=document.createElement('audio');element.autoplay=true;element.dataset.claim911SandboxAssistant='true';
  document.body.appendChild(element);window.__claim911BolnaAudioElement=element;
 });
 await voice.getByLabel('I agree to record this synthetic browser conversation.').check();
 await voice.getByRole('button',{name:'Start Bolna voice check'}).click();
 await page.waitForFunction(()=>document.querySelector('.sandbox-bolna [aria-live="polite"]')?.textContent?.includes('Connected to the Bolna assistant.'),null,{timeout:60000});
 result.connected=true;
 result.audio_capture_setup=await page.evaluate(()=>window.__claim911CaptureRenderedAssistantAudio?.()||null);
 await page.evaluate(()=>window.__claim911ResumeAudioTap?.());
 result.connected_at=Date.now();
 // Match the reviewed provider session ceiling. Reply-count and per-turn
 // audio bounds independently limit work; do not assume every turn takes 20 s.
 sessionDeadline=result.connected_at+300000;
 audioPump=createBackgroundAudioPump(pumpSpeechBoundaries);
 const history=[];
 for(let turnIndex=0;turnIndex<(parentRpc?maxTurns*3+2:maxTurns);turnIndex++){
  if(Date.now()>=sessionDeadline)throw new Error('The bounded synthetic voice session timed out.');
  let pcmBase64=null;
  const deadline=Math.min(Date.now()+45000,sessionDeadline);
  while(Date.now()<deadline&&!pcmBase64){
   await page.waitForTimeout(100);
   audioPump.check();
  if(bolnaVolumeBouts.length){
    const bout=bolnaVolumeBouts.shift();
    const remote=bout.pcm_base64;
    if(remote){pcmBase64=remote;result.assistant_audio_source=await page.evaluate(()=>window.__claim911RemoteAudioSource||'unknown');
     result.assistant_audio_bouts??=[];result.assistant_audio_bouts.push({duration_ms:bout.duration_ms,detector:bout.detector});}
   }
  }
  if(!pcmBase64){
   result.audio_capture_diagnostic=await page.evaluate(()=>{
     const levels=window.__claim911BolnaVolumeEvents||[];
     const tracks=window.__claim911RemoteAudioTracks||[];
     return {volume_sample_count:levels.length,volume_peak:Math.max(0,...levels.map(sample=>sample?.level||0)),
     frame_count:window.__claim911RemotePcmFrames?.length||0,
     pcm_samples:(window.__claim911RemotePcmFrames||[]).reduce((n,frame)=>n+frame.length,0),
     track_count:tracks.length,
     remote_tracks:tracks.map(track=>({readyState:track.readyState,muted:track.muted,enabled:track.enabled})),
     remote_audio_source:window.__claim911RemoteAudioSource||null,
     audio_element:window.__claim911RemoteAudioElementState||null,
     tap_context_state:window.__claim911ResumeAudioTap?'ready':'missing'};
   });
   let providerState=null;
   try{
    const evidence=await brokerExecution(result.run_id,result.call_id,result.provider_execution_id);
    if(evidence){providerState=evidence.status;result.provider_execution_status=evidence.status;
     result.provider_transcript=evidence.transcript;result.provider_conversation_duration=evidence.conversation_duration;}
   }catch(error){result.provider_transcript_error=error?.name||'BrokerUnavailable';}
   if(providerState==='balance-low'){
    result.provider_failure='BOLNA_BALANCE_LOW';
    const reconciled=await appRequest('/api/sandbox/runs/'+result.run_id+'/conversations/'+result.call_id+'/abort','POST',{});
    result.provider_call_reconciled=reconciled.ok===true;
    throw new Error('Bolna reports that the account balance is too low. No assistant audio was generated; add existing provider credits before another run.');
   }
   throw new Error('No audible Bolna question was captured for the synthetic participant.');
  }
  result.captured_assistant_audio??=[];
  result.captured_assistant_audio.push(await preserveCapturedAssistantPcm(pcmBase64,turnIndex));
  let turn;
  if(parentRpc){
   let response;
   // The SDK has no transcript event. Use the existing scoped execution read
   // opportunistically; if no current question is exposed, recognize the audio.
   let providerQuestion=null,lookup='unavailable';
   try{const evidence=await brokerExecution(result.run_id,result.call_id,result.provider_execution_id);
    providerQuestion=providerQuestionAtReply(evidence?.transcript,result.turns.length);
    lookup=providerQuestion?'current_question':'no_current_question';
   }catch(error){lookup=error?.name==='TimeoutError'?'timeout':'unavailable';}
   result.live_transcript_lookups??=[];
   result.live_transcript_lookups.push({audio_turn:turnIndex+1,participant_turns:result.turns.length,result:lookup});
   try{response=await participantTurnFromParent(pcmBase64,turnIndex,providerQuestion);}
   catch(error){result.failed_audio=await preserveCapturedAssistantPcm(pcmBase64,turnIndex);throw error;}
   if(response.type==='end_call'){
    result.terminal_handoff=true;result.caregiver_update_saved=response.report_saved;
    result.terminal_assistant_text=response.assistant_text;
    appendBolnaArchiveAudio(archiveAudio,'assistant',pcmBase64);
    break;
   }
   if(response.type==='continue_audio'){
    appendBolnaArchiveAudio(archiveAudio,'assistant',pcmBase64);
    continue;
   }
   turn={assistant_text:response.assistant_text,participant_text:response.participant_text,
    participant_role:response.role,participant_audio_pcm_base64:response.pcm_base64,
   question_source:response.question_source,assistant_text_source:response.question_source};
   result.turns.push({assistant_text:turn.assistant_text,participant_text:turn.participant_text,
    participant_role:turn.participant_role,question_source:turn.question_source,turn:turnIndex+1});
  }else{
   let response;
   try{response=await participantTurn(pcmBase64,history);}
   catch(error){result.failed_audio=await preserveCapturedAssistantPcm(pcmBase64,turnIndex);throw error;}
   if(response.assistant_text.length<5){
    result.recognized_short_text=response.assistant_text;
    result.failed_audio=await preserveCapturedAssistantPcm(pcmBase64,turnIndex);
    throw new Error('The Bolna question could not be transcribed clearly.');
   }
   turn={...response,participant_audio_pcm_base64:response.participant_audio_pcm_base64};
   result.turns.push({assistant_text:turn.assistant_text,participant_text:turn.participant_text,
    participant_role:turn.participant_role,question_source:'live_audio_transcription',turn:turnIndex+1});
  }
  history.push({role:'assistant',content:turn.assistant_text},{role:'user',content:turn.participant_text});
  const injectionStarted=Date.now();
  const injection=await page.evaluate(pcm=>window.__claim911InjectPcm?.(pcm),turn.participant_audio_pcm_base64);
  const injectionEnded=Date.now();
  const overlap=await page.evaluate(({start,end})=>(window.__claim911RemoteSpeechEvents||[])
   .filter(event=>event.at>=start+250&&event.at<=end&&event.level>=0.003).length,{start:injectionStarted,end:injectionEnded});
  result.turns.at(-1).injection_started_at=injectionStarted;
  result.turns.at(-1).injection_ended_at=injectionEnded;
  result.turns.at(-1).remote_energy_frames_during_participant=overlap;
  if(!injection?.track_ready)throw new Error('Synthetic participant audio did not reach the browser microphone track.');
  if(parentRpc){appendBolnaArchiveAudio(archiveAudio,'assistant',pcmBase64);appendBolnaArchiveAudio(archiveAudio,'participant',turn.participant_audio_pcm_base64);}
  result.participant_audio_injected=true;
  result.synthetic_mic_injection=injection;
  currentVolumeBout=null;
 }
 if(result.turns.length&&!result.terminal_handoff){
  // A test turn is not complete when the synthetic person has spoken. Keep
  // Bolna connected long enough to capture its next answer, then verify that
  // response independently from the provider transcript after hangup.
  const followUpDeadline=Math.min(Date.now()+30000,sessionDeadline);let followUpPcm=null;
  while(Date.now()<followUpDeadline&&!followUpPcm){
   await page.waitForTimeout(100);
   audioPump.check();
   if(bolnaVolumeBouts.length){
    const bout=bolnaVolumeBouts.shift();
    followUpPcm=bout.pcm_base64;
    if(followUpPcm){result.follow_up_audio_source=await page.evaluate(()=>window.__claim911RemoteAudioSource||'unknown');
     result.follow_up_audio_bout={duration_ms:bout.duration_ms,detector:bout.detector};}
   }
  }
  if(!followUpPcm)throw new Error('Bolna did not answer after the synthetic participant turn.');
  result.follow_up_assistant_audio_captured=Boolean(followUpPcm);
  if(parentRpc)appendBolnaArchiveAudio(archiveAudio,'assistant',followUpPcm);
  if(!parentRpc){
   try{result.follow_up_assistant_text=(await transcribeAssistant(followUpPcm,history)).assistant_text;}
   catch(error){result.failed_follow_up_audio=await preserveCapturedAssistantPcm(followUpPcm,result.turns.length);throw error;}
  }
 }
 result.webrtc_audio_stats_active=await liveAudioStats();
 const endButton=voice.getByRole('button',{name:'End voice check'});
 if(await endButton.isVisible().catch(()=>false))await endButton.click();
 await page.waitForFunction(()=>{
  const text=document.querySelector('.sandbox-bolna [aria-live="polite"]')?.textContent||'';
  return text.includes('Voice session ended.')||text.includes('Could not connect');
 },null,{timeout:15000}).catch(()=>{});
 result.ended=(await voice.locator('[aria-live="polite"]').textContent()||'').includes('Voice session ended.');
 // Provider callbacks can finish after the browser hangs up. Give the sandbox
 // webhook route a bounded settling window before evaluating its transcript.
 const detail=await appRequest('/api/sandbox/runs/'+run.id);
 if(detail.ok){const value=detail.value;result.incident_id=value.incident_id;result.run_state=value.state;result.checkpoint_count=value.checkpoint;
  result.provider_configuration=value.provider_configuration;result.conversations=value.conversations||[];}
 const providerTranscriptDeadline=Date.now()+30000;
 while(Date.now()<providerTranscriptDeadline){
  try{const evidence=await brokerExecution(result.run_id,result.call_id,result.provider_execution_id);
   if(evidence){result.provider_execution_status=evidence.status;result.provider_transcript=evidence.transcript;
    result.provider_conversation_duration=evidence.conversation_duration;
    if(['completed','failed','no-answer','busy','cancelled','balance-low'].includes(evidence.status))break;}}
  catch(error){result.provider_transcript_error=error?.name||'BrokerUnavailable';break;}
  await page.waitForTimeout(1000);
 }
 result.provider_transcripts=[];
 for(const call of result.conversations||[]){
  const saved=await appRequest('/api/sandbox/runs/'+run.id+'/conversations/'+call.id);
  if(saved.ok)result.provider_transcripts.push(...(saved.value.transcript||[]).map(item=>item.text||''));
 }
 if(result.provider_transcript)result.provider_transcripts.push(result.provider_transcript);
 result.dialogue_evaluation=evaluateBolnaDialogue({transcript:result.provider_transcript||'',turns:result.turns,
  mode:participantMode,purpose:process.env.CLAIM911_WORKFLOW_PURPOSE||undefined,deferSemanticAlignment:parentRpc});
 result.dialogue_checks={
  provider_dialogue_order_and_content:result.dialogue_evaluation.passed,
  participant_audio_injected:result.participant_audio_injected===true,
  bolna_microphone_requested_synthetic_track:(await page.evaluate(()=>window.__claim911SyntheticMicMetrics||{})).requests>0,
  role_audio_injected_into_microphone:(await page.evaluate(()=>window.__claim911SyntheticMicMetrics||{})).injections===result.turns.length,
  caregiver_update_saved:process.env.CLAIM911_WORKFLOW_PURPOSE!=='CAREGIVER_INTAKE'||result.caregiver_update_saved===true,
  no_post_handoff_participant_turn:process.env.CLAIM911_WORKFLOW_PURPOSE!=='CAREGIVER_INTAKE'||(result.terminal_handoff===true&&result.turns.length>=1&&result.turns.length<=2),
 };
 // A connected WebRTC session is only transport evidence. Do not report the
 // scripted scenario as passing unless Bolna's own saved transcript confirms
 // that each expected prompt preceded the role-bounded reply and a later
 // assistant turn followed it. The adaptive mode has separate live-ASR gates.
 const requiredDialogueChecks=['provider_dialogue_order_and_content','participant_audio_injected',
  'bolna_microphone_requested_synthetic_track','role_audio_injected_into_microphone'];
 if(process.env.CLAIM911_WORKFLOW_PURPOSE==='CAREGIVER_INTAKE')requiredDialogueChecks.push('caregiver_update_saved','no_post_handoff_participant_turn');
 result.dialogue_checks_passed=requiredDialogueChecks.every(name=>result.dialogue_checks[name]===true);
 if(!result.dialogue_checks_passed)result.errors.push('Bolna transcript or synthetic participant evidence did not satisfy the required dialogue checks.');
 // Always retain actual captured media before a checker can reject the call.
 // A capture is diagnostic evidence, never a passing workflow archive.
 if(parentRpc&&archiveAudio.length){
  const capturePath=archivePath+'.capture.json';
  await writeFile(capturePath,JSON.stringify({run_id:result.run_id,call_id:result.call_id,
   execution_id:result.provider_execution_id,turns:archiveAudio,checkpoint_eligible:false})+'\n',{mode:0o600});
  result.media_capture_path=capturePath;
 }
 if(parentRpc&&result.dialogue_checks_passed){
  if(result.provider_execution_status!=='completed'||!result.provider_transcript||!result.provider_configuration?.assistant_config_sha256)
   throw new Error('A completed provider transcript and reviewed assistant fingerprint are required before archive.');
  const providerTurns=parseBolnaTranscript(result.provider_transcript);
  if(providerTurns.length!==archiveAudio.length||providerTurns.length<2||providerTurns.some((turn,index)=>(turn.role==='assistant'?'assistant':'participant')!==archiveAudio[index].speaker))
   throw new Error('Captured audio turn boundaries do not match Bolna provider transcript turns.');
  const body={execution_id:result.provider_execution_id,assistant_config_sha256:result.provider_configuration.assistant_config_sha256,
   provider_transcript_sha256:createHash('sha256').update(result.provider_transcript).digest('hex'),
   turns:providerTurns.map((turn,index)=>({speaker:turn.role==='assistant'?'assistant':'participant',text:turn.text,pcm_base64:archiveAudio[index].pcm_base64}))};
  await writeFile(archivePath,JSON.stringify(body)+'\n',{mode:0o600});await chmod(archivePath,0o600);
  result.provider_archive_prepared=true;
 }
 result.full_case=result.run_state==='COMPLETED'&&result.checkpoint_count===13;
}catch(error){result.failed_at=error?.name||'harness';result.errors.push(error?.message||'Synthetic participant harness failed.');}
finally{
 if(parentRpc&&archiveAudio.length){
  try{await writeFile(archivePath+'.capture.json',JSON.stringify({run_id:result.run_id,call_id:result.call_id,
   execution_id:result.provider_execution_id,turns:archiveAudio,checkpoint_eligible:false})+'\n',{flag:'wx',mode:0o600});}
  catch(error){if(error.code!=='EEXIST')result.capture_preservation_error=error?.name||'CaptureUnavailable';}
 }
 if(audioPump)await audioPump.stop();
 if(page&&result.connected&&!result.webrtc_audio_stats_active){
  try{result.webrtc_audio_stats_active=await liveAudioStats();}catch{}
 }
 if(browser&&page&&result.connected&&!result.ended){
  try{
   const end=page.getByRole('region',{name:'Bolna browser voice check'}).getByRole('button',{name:'End voice check'});
   if(await end.isVisible().catch(()=>false))await end.click({timeout:3000});
   await page.waitForFunction(()=>document.querySelector('.sandbox-bolna [aria-live="polite"]')?.textContent?.includes('Voice session ended.'),null,{timeout:8000}).catch(()=>{});
   result.ended=(await page.locator('.sandbox-bolna [aria-live="polite"]').textContent().catch(()=>''))?.includes('Voice session ended.')||false;
  }catch{}
 }
 if(page&&result.run_id&&!Array.isArray(result.provider_transcripts)){
  try{
   const detail=await appRequest('/api/sandbox/runs/'+result.run_id);
   if(detail.ok){const value=detail.value;result.incident_id=value.incident_id;result.run_state=value.state;result.checkpoint_count=value.checkpoint;
    result.provider_configuration=value.provider_configuration;result.conversations=value.conversations||[];}
   result.provider_transcripts=[];
   for(const call of result.conversations||[]){
    const saved=await appRequest('/api/sandbox/runs/'+result.run_id+'/conversations/'+call.id);
    if(saved.ok)result.provider_transcripts.push(...(saved.value.transcript||[]).map(item=>item.text||''));
   }
  }catch(error){result.transcript_collection_error=error?.name||'collection';}
 }
 if(page&&result.connected&&result.call_id&&result.provider_execution_id&&!result.provider_transcript){
  try{
   const detail=await appRequest('/api/sandbox/runs/'+result.run_id);
   if(detail.ok)result.incident_id=detail.value.incident_id;
   const evidence=await brokerExecution(result.run_id,result.call_id,result.provider_execution_id);
   if(evidence){result.provider_execution_status=evidence.status;result.provider_transcript=evidence.transcript;
    result.provider_conversation_duration=evidence.conversation_duration;result.provider_transcripts??=[];
    result.provider_transcripts.push(result.provider_transcript);}
  }catch(error){result.provider_transcript_error=error?.name||'BrokerUnavailable';}
 }
 if(page){
  try{const captured=await page.evaluate(async()=>{
   const pcs=window.__claim911PeerConnections||[],stats=[];
   for(let index=0;index<pcs.length;index++){
    try{const report=await pcs[index].getStats();for(const item of report.values()){
     if(item.type==='inbound-rtp'&&item.kind==='audio')stats.push({peer:index,packets_received:item.packetsReceived,
      packets_lost:item.packetsLost,bytes_received:item.bytesReceived,total_samples:item.totalSamplesReceived,
      concealed_samples:item.concealedSamples,jitter:item.jitter,audio_level:item.audioLevel});
    }}catch(error){stats.push({peer:index,error:error?.name||'StatsUnavailable'});}
   }
   return {microphone:window.__claim911SyntheticMicMetrics||null,audio_source:window.__claim911RemoteAudioSource||null,
    audio_element:window.__claim911RemoteAudioElementState||null,recorder:window.__claim911RemoteRecorderState||null,
    track_state:window.__claim911RemoteAudioTrackState||null,webrtc_audio_stats:stats,
    volume_samples:(window.__claim911BolnaVolumeEvents||[]).length,
    volume_peak:Math.max(0,...(window.__claim911BolnaVolumeEvents||[]).map(sample=>sample?.level||0))};
  });
   result.synthetic_microphone=captured.microphone;result.audio_capture_source=captured.audio_source;
   result.audio_element=captured.audio_element;result.audio_recorder=captured.recorder;
   result.remote_audio_track_state=captured.track_state;result.webrtc_audio_stats=captured.webrtc_audio_stats;
   result.volume_sample_count=captured.volume_samples;result.volume_peak=captured.volume_peak;}
  catch{}
 }
 if(browser)await browser.close();
 if(vad)await vad.close();
}
if(result.turns.length&&!result.dialogue_evaluation){
 result.dialogue_evaluation=evaluateBolnaDialogue({transcript:result.provider_transcript||'',turns:result.turns,
  mode:participantMode,purpose:process.env.CLAIM911_WORKFLOW_PURPOSE||undefined,deferSemanticAlignment:parentRpc});
}
await mkdir(dirname(reportPath),{recursive:true});
await writeFile(reportPath,JSON.stringify(result,null,2)+'\n',{mode:0o600});await chmod(reportPath,0o600);
const summary={provenance:result.provenance,connected:result.connected,ended:result.ended,
 role:result.participant_role,turns:result.turns.length,session_status:result.session_status,
 transport:result.transport,synthetic:result.synthetic,phone_dispatch:result.phone_dispatch,
 run_id:result.run_id,checkpoint_count:result.checkpoint_count,full_case:result.full_case,
 dialogue_checks:result.dialogue_checks,dialogue_issues:result.dialogue_evaluation?.issues,errors:result.errors};
if(parentRpc)process.stdout.write(JSON.stringify({type:'completed',summary,report_path:reportPath})+'\n');
else console.log(JSON.stringify(summary));
if(!result.connected||!result.ended||result.transport!=='BOLNA_WEBRTC'||result.synthetic!==true||result.phone_dispatch!==false||!result.turns.length)process.exitCode=1;
if(!result.dialogue_checks_passed)process.exitCode=1;
