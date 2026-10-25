// No providers, speech APIs or institution services. Exercise the production
// bounded collector over a real local WebRTC receiver for a long spoken turn.
import assert from 'node:assert/strict';
import {createServer} from 'node:http';
import {chromium} from 'playwright';
import {installBolnaRemoteAudioTap} from './bolna-remote-audio-tap.mjs';
import {BoundedSpeechCapture} from './bounded-speech-capture.mjs';
const server=createServer((q,r)=>r.end('<html><body></body></html>'));
await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
const browser=await chromium.launch({headless:true,executablePath:'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',args:['--autoplay-policy=no-user-gesture-required']});
try{
 const page=await browser.newPage();await page.addInitScript(installBolnaRemoteAudioTap);
 await page.goto(`http://127.0.0.1:${server.address().port}`);
 await page.evaluate(async()=>{
  const context=new AudioContext(),output=context.createMediaStreamDestination(),tone=context.createOscillator();
  tone.frequency.value=220;tone.connect(output);tone.start();
  const sender=new RTCPeerConnection(),receiver=new RTCPeerConnection();
  sender.onicecandidate=e=>{if(e.candidate)receiver.addIceCandidate(e.candidate)};
  receiver.onicecandidate=e=>{if(e.candidate)sender.addIceCandidate(e.candidate)};
  const received=new Promise(resolve=>receiver.ontrack=e=>resolve(e.streams[0]));
  sender.addTrack(output.stream.getAudioTracks()[0],output.stream);
  await sender.setLocalDescription(await sender.createOffer());await receiver.setRemoteDescription(sender.localDescription);
  await receiver.setLocalDescription(await receiver.createAnswer());await sender.setRemoteDescription(receiver.localDescription);
  const audio=document.createElement('audio');audio.autoplay=true;audio.srcObject=await received;document.body.appendChild(audio);await audio.play();
  await window.__claim911ResumeAudioTap();
  window.__longLoopback={sender,receiver,context,tone};
 });
 await page.waitForFunction(()=>window.__claim911WorkletCapture?.ready);
 const start=await page.evaluate(()=>window.__claim911RemoteAudioClockMs());
 let windows=0;
 const capture=new BoundedSpeechCapture({startMs:start,take:async w=>{
  windows++;return page.evaluate(w=>window.__claim911TakeRemotePcm(w),w);}});
 let end=start;
 while(end-start<28000){
  await page.waitForTimeout(250);end=await page.evaluate(()=>window.__claim911RemoteAudioClockMs());
  await capture.snapshot(end);
 }
 const pcm=Buffer.from(await capture.snapshot(end,true),'base64');
 assert.ok(windows>=4);assert.ok(pcm.length>26*32000);
 assert.ok(Math.abs(pcm.length-(end-start)*32)<20);
 let oldRejected=false;
 try{await page.evaluate(w=>window.__claim911TakeRemotePcm(w),{start_ms:start,end_ms:start+8000});}catch{oldRejected=true;}
 assert.equal(oldRejected,true);
 console.log(JSON.stringify({provider_requests:0,real_webrtc:true,duration_ms:pcm.length/32,snapshots:windows,expired_initial_window_rejected:oldRejected,complete_bounded_capture:true}));
 await page.evaluate(async()=>{const x=window.__longLoopback;x.tone.stop();x.sender.close();x.receiver.close();await x.context.close();});
}finally{await browser.close();server.close();}
