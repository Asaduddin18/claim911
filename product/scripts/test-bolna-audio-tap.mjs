import {chromium} from 'playwright';
import {createServer} from 'node:http';
import {execFileSync} from 'node:child_process';
import {readFile} from 'node:fs/promises';
import {resolve} from 'node:path';
import {installBolnaRemoteAudioTap} from './bolna-remote-audio-tap.mjs';

const speechPath=resolve(process.env.CLAIM911_TEST_SPEECH_WAV||new URL('../../fixtures/audio/reference-english.wav',import.meta.url).pathname);
const speechWav=await readFile(speechPath);
const server=createServer((request,response)=>{
 if(request.url==='/speech.wav'){response.writeHead(200,{'content-type':'audio/wav'});response.end(speechWav);return;}
 response.writeHead(200,{'content-type':'text/html'});response.end('<html><body></body></html>');
});
await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
const origin=`http://127.0.0.1:${server.address().port}`;
const browser=await chromium.launch({headless:true,
 executablePath:process.env.CLAIM911_CHROME_PATH||'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
 args:['--autoplay-policy=no-user-gesture-required']});
try{
 const context=await browser.newContext({permissions:['microphone']});
 const page=await context.newPage();
 await page.addInitScript(installBolnaRemoteAudioTap);
 await page.goto(origin);
 const result=await page.evaluate(async()=>{
  const sourceContext=new AudioContext(),destination=sourceContext.createMediaStreamDestination();
  const wav=await (await fetch('/speech.wav')).arrayBuffer(),speechBuffer=await sourceContext.decodeAudioData(wav);
  const speechSource=sourceContext.createBufferSource();speechSource.buffer=speechBuffer;speechSource.connect(destination);
  // Use an actual local WebRTC sender/receiver pair. A MediaStreamDestination
  // alone does not exercise the remote-track clock, codec or receiver path.
  const outbound=new RTCPeerConnection(),inbound=new RTCPeerConnection();
  outbound.onicecandidate=event=>{if(event.candidate)inbound.addIceCandidate(event.candidate)};
  inbound.onicecandidate=event=>{if(event.candidate)outbound.addIceCandidate(event.candidate)};
  const received=new Promise(resolve=>inbound.ontrack=event=>resolve(event.streams[0]));
  outbound.addTrack(destination.stream.getAudioTracks()[0],destination.stream);
  await outbound.setLocalDescription(await outbound.createOffer());
  await inbound.setRemoteDescription(outbound.localDescription);
  await inbound.setLocalDescription(await inbound.createAnswer());
  await outbound.setRemoteDescription(inbound.localDescription);
  const remoteStream=await received;
  const audio=document.createElement('audio');audio.srcObject=remoteStream;audio.autoplay=true;
  document.body.appendChild(audio);await audio.play();
  const captureSetup={source:window.__claim911RemoteAudioSource||null,recorder:window.__claim911RemoteRecorderState||null};
  await window.__claim911ResumeAudioTap();
  for(let attempt=0;attempt<100&&!window.__claim911WorkletCapture?.ready;attempt++)await new Promise(resolve=>setTimeout(resolve,20));
  const startedAudioMs=window.__claim911RemoteAudioClockMs();
  const speechEnded=new Promise(resolve=>speechSource.onended=resolve);speechSource.start();await speechEnded;
  await new Promise(resolve=>setTimeout(resolve,350));
  const endedAudioMs=window.__claim911RemoteAudioClockMs();
  // Reproduce the production endpoint delay. The selected range must stay
  // fixed on the audio clock even while more silence enters the buffer.
  await new Promise(resolve=>setTimeout(resolve,1600));
  const frames=window.__claim911RemotePcmFrames||[];
  const samples=frames.reduce((sum,frame)=>sum+frame.length,0);
  const requestedWindow={start_ms:Math.max(0,startedAudioMs-100),end_ms:endedAudioMs};
  const pcm=await window.__claim911TakeRemotePcm?.(requestedWindow);
  const capturedBytes=Uint8Array.from(atob(pcm),c=>c.charCodeAt(0));
  const capturedSamples=new Int16Array(capturedBytes.buffer);let activeWindows=0;
  for(let start=0;start<capturedSamples.length;start+=320){
   const window=capturedSamples.subarray(start,start+320);let power=0;for(const value of window)power+=value*value;
   if(Math.sqrt(power/Math.max(1,window.length))/32768>0.003)activeWindows++;
  }
  const correctedCapture=window.__claim911WorkletCapture;
  const trailingEnd=window.__claim911RemoteAudioClockMs();
  const wrongTail=await window.__claim911TakeRemotePcm({start_ms:Math.max(0,trailingEnd-(requestedWindow.end_ms-requestedWindow.start_ms)),end_ms:trailingEnd});
  const tailSamples=new Int16Array(Uint8Array.from(atob(wrongTail),c=>c.charCodeAt(0)).buffer);let tailActive=0;
  for(let start=0;start<tailSamples.length;start+=320){
   const frame=tailSamples.subarray(start,start+320);let power=0;for(const value of frame)power+=value*value;
   if(Math.sqrt(power/Math.max(1,frame.length))/32768>0.003)tailActive++;
  }
  let expiredWindowRejected=false;
  try{await window.__claim911TakeRemotePcm({start_ms:0,end_ms:window.__claim911RemoteAudioClockMs()+1000});}
  catch{expiredWindowRejected=true;}
  const receiverStats=[];
  for(const stat of (await inbound.getStats()).values()){
   if(stat.type==='inbound-rtp'&&stat.kind==='audio')receiverStats.push({packets_received:stat.packetsReceived,
    packets_lost:stat.packetsLost,total_samples:stat.totalSamplesReceived,concealed_samples:stat.concealedSamples});
  }
  const peer=new RTCPeerConnection();peer.addTrack(destination.stream.getAudioTracks()[0],destination.stream);
  const sender=(window.__claim911PeerConnections||[]).flatMap(item=>item.getSenders()).find(item=>item.track?.kind==='audio');
  const replacementContext=new AudioContext(),replacement=replacementContext.createMediaStreamDestination();
  const senderReplaced=Boolean(sender);if(sender)await sender.replaceTrack(replacement.stream.getAudioTracks()[0]);
  const preflightMic=await navigator.mediaDevices.getUserMedia({audio:true,video:false});
  preflightMic.getTracks().forEach(track=>track.stop());
  const fakeMic=await navigator.mediaDevices.getUserMedia({audio:true,video:false});
  await outbound.getSenders()[0].replaceTrack(fakeMic.getAudioTracks()[0]);
  const sentPackets=async()=>{let count=0;for(const stat of (await outbound.getStats()).values()){
   if(stat.type==='outbound-rtp'&&stat.kind==='audio')count+=stat.packetsSent||0;}return count;};
  const beforeIdle=await sentPackets();await new Promise(resolve=>setTimeout(resolve,750));
  const idleMicPackets=await sentPackets()-beforeIdle;
  const micContext=new AudioContext(),micSource=micContext.createMediaStreamSource(fakeMic);
  const micProcessor=micContext.createScriptProcessor(2048,1,1),micMute=micContext.createGain();
  let microphonePeak=0;
  micProcessor.onaudioprocess=event=>{
   const channel=event.inputBuffer.getChannelData(0);
   for(const value of channel)microphonePeak=Math.max(microphonePeak,Math.abs(value));
  };
  micMute.gain.value=0;micSource.connect(micProcessor);micProcessor.connect(micMute);micMute.connect(micContext.destination);
  const sampleCount=256000,participantPcm=new Int16Array(sampleCount);
  for(let i=0;i<sampleCount;i++)participantPcm[i]=Math.round(Math.sin(i*2*Math.PI*220/16000)*12000);
  const rawPcm=new Uint8Array(participantPcm.buffer);let pcmString='';
  for(let i=0;i<rawPcm.length;i+=0x8000)pcmString+=String.fromCharCode(...rawPcm.subarray(i,Math.min(i+0x8000,rawPcm.length)));
  const injected=await window.__claim911InjectPcm(btoa(pcmString));
  await new Promise(resolve=>setTimeout(resolve,100));
  let originalWindowExpiredAfterConsumerDelay=false;
  try{await window.__claim911TakeRemotePcm(requestedWindow);}
  catch{originalWindowExpiredAfterConsumerDelay=true;}
  const queuedSnapshotPreserved=Uint8Array.from(atob(pcm),c=>c.charCodeAt(0)).every((value,index)=>value===capturedBytes[index]);
  await micContext.close();
  peer.close();outbound.close();inbound.close();await replacementContext.close();
  await sourceContext.close();
  return {track_count:window.__claim911RemoteAudioTracks?.length||0,frame_count:frames.length,
   pcm_samples:samples,pcm_base64_length:pcm?.length||0,peer_count:window.__claim911PeerConnections?.length||0,
   remote_audio_source:window.__claim911RemoteAudioSource||'missing',worklet:correctedCapture||null,
   capture_setup:captureSetup,recorder:window.__claim911RemoteRecorderState||null,speech_pcm_base64:pcm,
   real_webrtc_loopback:true,receiver_stats:receiverStats,idle_synthetic_mic_packets:idleMicPackets,
   capture_window:requestedWindow,captured_duration_ms:capturedSamples.length/16,
   voiced_duration_ms:activeWindows*20,endpoint_delay_ms:1600,unavailable_window_rejected:expiredWindowRejected,
   duration_only_tail_voiced_ms:tailActive*20,voiced_speech_recovered_ms:(activeWindows-tailActive)*20,
   sender_replaced:senderReplaced,synthetic_mic_requests:window.__claim911SyntheticMicMetrics?.requests||0,
   synthetic_mic_injections:window.__claim911SyntheticMicMetrics?.injections||0,
   synthetic_mic_samples:window.__claim911SyntheticMicMetrics?.samples_injected||0,
   preflight_mic_tracks:preflightMic.getAudioTracks().map(track=>track.readyState),
   fake_mic_tracks:fakeMic.getAudioTracks().map(track=>track.readyState),microphone_peak:microphonePeak,injected,
   original_window_expired_after_consumer_delay:originalWindowExpiredAfterConsumerDelay,queued_snapshot_preserved:queuedSnapshotPreserved};
 });
 let speechRecognition=null;
 if(result.speech_pcm_base64&&process.env.CLAIM911_PROVIDER_PROFILE&&process.env.CLAIM911_PYTHON){
  const bridge=new URL('../../scripts/bolna_participant_turn.py',import.meta.url).pathname;
  const request={role:'caregiver',record:{synthetic:true,known_facts:['the discharge summary needs a signature']},history:[],pcm_base64:result.speech_pcm_base64};
  const output=execFileSync(process.env.CLAIM911_PYTHON,[bridge,'--provider-config',process.env.CLAIM911_PROVIDER_PROFILE,'--transcribe-only'],
   {input:JSON.stringify(request)+'\n',encoding:'utf8',timeout:45000,maxBuffer:300_000,stdio:['pipe','pipe','pipe']});
  const recognizedText=JSON.parse(output).assistant_text;
  const recognized=recognizedText.toLowerCase().replace(/[^a-z0-9 ]/g,' ').replace(/\s+/g,' ').trim();
  speechRecognition=recognized.includes('discharge summary needs a signature');
  result.speech_recognition_passed=speechRecognition;result.speech_recognition_text=recognizedText;
 }
 delete result.speech_pcm_base64;
 console.log(JSON.stringify(result));
 if(!result.track_count||!result.pcm_samples||!result.pcm_base64_length||!result.peer_count||!result.sender_replaced||
  result.remote_audio_source!=='remote-webrtc-audio-worklet'||!result.worklet?.ready||result.worklet.returned_samples<8000||
  Math.abs(result.captured_duration_ms-(result.capture_window.end_ms-result.capture_window.start_ms))>2||
  result.voiced_duration_ms<500||!result.unavailable_window_rejected||
  result.voiced_speech_recovered_ms<700||
  !result.original_window_expired_after_consumer_delay||!result.queued_snapshot_preserved||
  result.synthetic_mic_requests!==2||result.synthetic_mic_injections!==1||result.synthetic_mic_samples!==256000||
  result.preflight_mic_tracks.includes('live')||!result.fake_mic_tracks.includes('live')||
  !result.injected.track_ready||result.microphone_peak<0.05||result.idle_synthetic_mic_packets<5||!result.receiver_stats?.some(item=>item.packets_received>20)||
  (process.env.CLAIM911_PROVIDER_PROFILE&&process.env.CLAIM911_PYTHON&&!speechRecognition))process.exitCode=1;
}finally{await browser.close();server.close();}
