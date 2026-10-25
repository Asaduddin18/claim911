export function installBolnaRemoteAudioTap(){
 const maxTurnSamples=320_000;
 window.__claim911BolnaVolumeEvents=[];
 window.__claim911RemoteSpeechEvents=[];
 window.__claim911RemotePcmFrames=[];
 window.__claim911RemotePcmSampleCount=0;
 window.__claim911RemoteAudioTracks=[];
 window.__claim911CaptureRemoteAudio=true;
 // The sandbox harness replaces only this page's microphone with a synthetic
 // stream. The production surfaces never load this init script.
 window.__claim911SyntheticMicEnabled=true;
 window.__claim911SyntheticMicMetrics={requests:0,injections:0,samples_injected:0};
 let micContext=null,micDestination=null,micKeepAlive=null;
 const ensureSyntheticMicContext=async()=>{
  if(!micContext){
   micContext=new AudioContext({sampleRate:48000});
   micDestination=micContext.createMediaStreamDestination();
   // A destination with no running source emits no RTP at all while idle.
   // Keep a real, silent audio clock running just like a physical microphone;
   // otherwise the SIP media bridge can starve the assistant's receive path.
   micKeepAlive=micContext.createConstantSource();micKeepAlive.offset.value=0;
   micKeepAlive.connect(micDestination);micKeepAlive.start();
  }
  await micContext.resume();
  return micDestination.stream;
 };
 window.__claim911InjectPcm=async pcmBase64=>{
  const stream=await ensureSyntheticMicContext(),raw=atob(pcmBase64),samples=new Int16Array(raw.length/2);
  if(!samples.length||samples.length>1_600_000)throw new Error('Synthetic participant audio exceeds the 100-second turn limit.');
  for(let i=0;i<samples.length;i++)samples[i]=raw.charCodeAt(i*2)|(raw.charCodeAt(i*2+1)<<8);
  const buffer=micContext.createBuffer(1,samples.length,16000),channel=buffer.getChannelData(0);
  for(let i=0;i<samples.length;i++)channel[i]=samples[i]<0?samples[i]/32768:samples[i]/32767;
  const source=micContext.createBufferSource();source.buffer=buffer;source.connect(micDestination);source.start();
  await new Promise(resolve=>source.onended=resolve);
  window.__claim911SyntheticMicMetrics.injections++;
  window.__claim911SyntheticMicMetrics.samples_injected+=samples.length;
  return {samples:samples.length,track_ready:stream.getAudioTracks().some(track=>track.readyState==='live')};
 };
 const mediaDevices=navigator.mediaDevices;
 const nativeGetUserMedia=mediaDevices?.getUserMedia?.bind(mediaDevices);
 if(nativeGetUserMedia){
  mediaDevices.getUserMedia=async constraints=>{
   if(window.__claim911SyntheticMicEnabled&&constraints?.audio){
    if(constraints.video)throw new Error('Sandbox voice harness accepts audio-only sessions.');
    window.__claim911SyntheticMicMetrics.requests++;
    // Bolna's preflight microphone check stops its track before the SIP call
    // requests the real microphone. Give every request an independent clone
    // so stopping preflight cannot kill the call's audio source.
    const stream=await ensureSyntheticMicContext();
    return new MediaStream(stream.getAudioTracks().map(track=>track.clone()));
   }
   return nativeGetUserMedia(constraints);
  };
 }
 let tapContext=null,remoteRecorder=null,remoteRecorderChunks=[],remoteRecorderMime='',remoteRecorderOptions=undefined;
 let workletFrames=[],workletSampleCount=0,workletTotalSamples=0,workletReady=false,workletOverflow=false,vadFrames=[],vadSampleCount=0;
 let remoteAudioElement=null,remoteSourceStream=null;
 const toPcm16k=input=>{
  const sourceRate=tapContext.sampleRate,targetRate=16000;
  const targetLength=Math.floor(input.length*targetRate/sourceRate),output=new Int16Array(targetLength);
  for(let i=0;i<targetLength;i++){
   const sourceIndex=i*sourceRate/targetRate,left=Math.floor(sourceIndex),fraction=sourceIndex-left;
   const sample=(input[left]||0)*(1-fraction)+(input[Math.min(left+1,input.length-1)]||0)*fraction;
   const clipped=Math.max(-1,Math.min(1,sample));
   output[i]=clipped<0?Math.round(clipped*32768):Math.round(clipped*32767);
  }
  return output;
 };
 const attach=(stream,sourceType='remote-track')=>{
  if(tapContext||!stream?.getAudioTracks?.().length)return;
  window.__claim911RemoteAudioTracks.push(...stream.getAudioTracks());
  window.__claim911RemoteAudioSource=sourceType;
  window.__claim911RemoteAudioTrackState=stream.getAudioTracks().map(track=>({readyState:track.readyState,muted:track.muted,enabled:track.enabled}));
  // Record the actual incoming WebRTC media track. This avoids reconstructing
  // speech from periodic analyser snapshots, which can lose most voiced
  // samples even when Bolna's own volume meter sees the audio.
  if(typeof MediaRecorder!=='undefined'){
   const mimeType=['audio/webm;codecs=opus','audio/webm','audio/mp4'].find(type=>MediaRecorder.isTypeSupported(type));
   try{
    remoteRecorderMime=mimeType||'';
    remoteRecorderOptions=mimeType?{mimeType}:undefined;
    remoteRecorder=new MediaRecorder(stream,remoteRecorderOptions);
    remoteRecorder.ondataavailable=event=>{if(event.data?.size)remoteRecorderChunks.push(event.data)};
    remoteRecorder.start(250);
    window.__claim911RemoteRecorderState={available:true,mime_type:remoteRecorder.mimeType,state:remoteRecorder.state};
   }catch(error){window.__claim911RemoteRecorderState={available:false,error:error?.name||'RecorderError'};remoteRecorder=null;}
  }else window.__claim911RemoteRecorderState={available:false,error:'MediaRecorderUnavailable'};
  tapContext=new AudioContext();
  const source=tapContext.createMediaStreamSource(stream),analyser=tapContext.createAnalyser(),mute=tapContext.createGain();
  // Capture every rendered quantum rather than periodically sampling an
  // analyser. The parallel recorder remains available to diagnose codec loss.
  if(tapContext.audioWorklet){
   const code=`class Claim911PcmCapture extends AudioWorkletProcessor {
    constructor(){super();this.pending=new Float32Array(1536);this.offset=0;}
    process(inputs){const channels=inputs[0];if(channels?.length){
     const length=channels[0].length;
     for(let i=0;i<length;i++){let sample=0;for(const channel of channels)sample+=(channel[i]||0)/channels.length;
      this.pending[this.offset++]=sample;
      if(this.offset===this.pending.length){this.port.postMessage(this.pending,[this.pending.buffer]);this.pending=new Float32Array(1536);this.offset=0;}
     }}return true;}}
    registerProcessor('claim911-pcm-capture',Claim911PcmCapture);`;
   const moduleUrl=URL.createObjectURL(new Blob([code],{type:'text/javascript'}));
   tapContext.audioWorklet.addModule(moduleUrl).then(()=>{
    const node=new AudioWorkletNode(tapContext,'claim911-pcm-capture');
    node.port.onmessage=event=>{
     if(!(event.data instanceof Float32Array)||!window.__claim911CaptureRemoteAudio)return;
     let power=0,peak=0;for(const value of event.data){power+=value*value;peak=Math.max(peak,Math.abs(value));}
     window.__claim911RemoteSpeechEvents.push({level:Math.sqrt(power/event.data.length),peak,at:Date.now()});
     workletFrames.push(event.data);workletSampleCount+=event.data.length;workletTotalSamples+=event.data.length;
     vadFrames.push(event.data);vadSampleCount+=event.data.length;
     const maxSamples=tapContext.sampleRate*20;
     while(workletSampleCount>maxSamples&&workletFrames.length){workletOverflow=true;workletSampleCount-=workletFrames.shift().length;}
     while(vadSampleCount>maxSamples&&vadFrames.length){vadSampleCount-=vadFrames.shift().length;}
    };
    const silent=tapContext.createGain();silent.gain.value=0;
    source.connect(node);node.connect(silent);silent.connect(tapContext.destination);
    workletReady=true;window.__claim911WorkletCapture={ready:true,sample_rate:tapContext.sampleRate};
   }).catch(error=>{window.__claim911WorkletCapture={ready:false,error:error?.name||'WorkletUnavailable'};})
    .finally(()=>URL.revokeObjectURL(moduleUrl));
  }
  analyser.fftSize=4096;
  mute.gain.value=0;
  const samples=new Float32Array(analyser.fftSize);
  const captureTimer=setInterval(()=>{
   if(window.__claim911CaptureRemoteAudio){
   analyser.getFloatTimeDomainData(samples);
   const frame=toPcm16k(samples);
   window.__claim911RemotePcmFrames.push(frame);window.__claim911RemotePcmSampleCount+=frame.length;
   while(window.__claim911RemotePcmSampleCount>maxTurnSamples&&window.__claim911RemotePcmFrames.length){
    const excess=window.__claim911RemotePcmSampleCount-maxTurnSamples,first=window.__claim911RemotePcmFrames[0];
    if(first.length<=excess){window.__claim911RemotePcmFrames.shift();window.__claim911RemotePcmSampleCount-=first.length;}
    else{window.__claim911RemotePcmFrames[0]=first.subarray(excess);window.__claim911RemotePcmSampleCount-=excess;}
   }
   }
  },Math.max(20,Math.round(analyser.fftSize/tapContext.sampleRate*1000)));
  source.connect(analyser);analyser.connect(mute);mute.connect(tapContext.destination);
  window.__claim911StopRemoteCapture=()=>clearInterval(captureTimer);
  window.__claim911ResumeAudioTap=()=>tapContext.resume();
  window.__claim911ClearRemotePcm=()=>{window.__claim911RemotePcmFrames=[];window.__claim911RemotePcmSampleCount=0;
   workletFrames=[];workletSampleCount=0;workletOverflow=false};
  const pcmToBase64=pcm=>{
   const bytes=new Uint8Array(pcm.buffer);let raw='';
   for(let i=0;i<bytes.length;i+=0x8000)raw+=String.fromCharCode(...bytes.subarray(i,Math.min(i+0x8000,bytes.length)));
   return btoa(raw);
  };
  window.__claim911DrainVadPcm=()=>{
   if(!vadSampleCount)return null;
   const mono=new Float32Array(vadSampleCount);let offset=0;
   for(const frame of vadFrames){mono.set(frame,offset);offset+=frame.length;}
   vadFrames=[];vadSampleCount=0;
   return pcmToBase64(toPcm16k(mono));
  };
  window.__claim911RemoteAudioClockMs=()=>workletTotalSamples*1000/tapContext.sampleRate;
  window.__claim911TakeRemotePcm=async(audioWindow)=>{
   if(workletReady&&workletSampleCount){
    const bufferedStart=workletTotalSamples-workletSampleCount;
    let start=bufferedStart,end=workletTotalSamples;
    if(audioWindow!==undefined){
     if(!audioWindow||typeof audioWindow!=='object'||!Number.isFinite(audioWindow.start_ms)||!Number.isFinite(audioWindow.end_ms)
      ||audioWindow.start_ms<0||audioWindow.end_ms<=audioWindow.start_ms||audioWindow.end_ms-audioWindow.start_ms>20000)
      throw new Error('A bounded absolute assistant audio window is required.');
     start=Math.floor(audioWindow.start_ms*tapContext.sampleRate/1000);
     end=Math.ceil(audioWindow.end_ms*tapContext.sampleRate/1000);
     if(start<bufferedStart||end>workletTotalSamples)
      throw new Error('The complete assistant audio window is no longer buffered.');
    }
    const frames=workletFrames,mono=new Float32Array(end-start);let offset=0,position=bufferedStart;
    for(const frame of frames){
     const frameEnd=position+frame.length;
     if(frameEnd>start&&position<end){
      const part=frame.subarray(Math.max(0,start-position),Math.min(frame.length,end-position));
      mono.set(part,offset);offset+=part.length;
     }
     position=frameEnd;
    }
    if(audioWindow===undefined){workletFrames=[];workletSampleCount=0;}
    workletOverflow=false;
    const pcm=toPcm16k(mono);
    window.__claim911RemoteAudioSource='remote-webrtc-audio-worklet';
    window.__claim911WorkletCapture={ready:true,sample_rate:tapContext.sampleRate,returned_samples:pcm.length,
     start_ms:start*1000/tapContext.sampleRate,end_ms:end*1000/tapContext.sampleRate};
    return pcmToBase64(pcm);
   }
   if(audioWindow!==undefined)throw new Error('Timestamped assistant capture requires the audio worklet.');
   if(remoteRecorder&&remoteRecorder.state!=='inactive'){
    await new Promise(resolve=>{remoteRecorder.addEventListener('stop',resolve,{once:true});remoteRecorder.stop();});
    const blob=new Blob(remoteRecorderChunks,{type:remoteRecorderMime||remoteRecorder.mimeType});
    remoteRecorderChunks=[];
    if(blob.size){
     const decoded=await tapContext.decodeAudioData(await blob.arrayBuffer());
     const channelCount=Math.max(1,decoded.numberOfChannels),mono=new Float32Array(decoded.length);
     for(let channel=0;channel<channelCount;channel++){
      const data=decoded.getChannelData(channel);for(let i=0;i<data.length;i++)mono[i]+=data[i]/channelCount;
     }
     const pcm=toPcm16k(mono);
     remoteRecorderChunks=[];
     try{remoteRecorder=new MediaRecorder(stream,remoteRecorderOptions);remoteRecorder.ondataavailable=event=>{if(event.data?.size)remoteRecorderChunks.push(event.data)};remoteRecorder.start(250);}
     catch(error){remoteRecorder=null;window.__claim911RemoteRecorderState={available:false,error:error?.name||'RecorderRestartError'};}
     if(pcm.length){window.__claim911RemoteRecorderState={...window.__claim911RemoteRecorderState,
      last_blob_bytes:blob.size,last_decoded_samples:decoded.length,returned_samples:pcm.length};return pcmToBase64(pcm);}
    }
    try{remoteRecorder=new MediaRecorder(stream,remoteRecorderOptions);remoteRecorder.ondataavailable=event=>{if(event.data?.size)remoteRecorderChunks.push(event.data)};remoteRecorder.start(250);}
    catch(error){remoteRecorder=null;window.__claim911RemoteRecorderState={available:false,error:error?.name||'RecorderRestartError'};}
   }
   const frames=window.__claim911RemotePcmFrames.splice(0),available=frames.reduce((n,frame)=>n+frame.length,0);
   window.__claim911RemotePcmSampleCount=0;
   const length=Math.min(available,maxTurnSamples);
   if(!length)return null;
   const pcm=new Int16Array(length);let offset=0;
   for(const frame of frames){
    if(offset>=length)break;
    const count=Math.min(frame.length,length-offset);pcm.set(frame.subarray(0,count),offset);offset+=count;
   }
   return pcmToBase64(pcm);
  };
 };
 const descriptor=Object.getOwnPropertyDescriptor(HTMLMediaElement.prototype,'srcObject');
 window.__claim911CaptureRenderedAssistantAudio=()=>{
  const element=remoteAudioElement||window.__claim911BolnaAudioElement;
  if(!(element instanceof HTMLAudioElement)||tapContext)return {attached:Boolean(tapContext),source:window.__claim911RemoteAudioSource||null};
  let rendered=null;
  try{
   rendered=element.captureStream?.();
  }catch{}
  const renderedTracks=rendered?.getAudioTracks?.().length||0;
  if(renderedTracks)attach(rendered,'rendered-media-element');
  else attach(remoteSourceStream,'remote-webrtc-track');
  window.__claim911RemoteAudioElementState={readyState:element.readyState,paused:element.paused,
   source_tracks:remoteSourceStream?.getAudioTracks?.().length||0,capture_tracks:renderedTracks};
  return {attached:Boolean(tapContext),source:window.__claim911RemoteAudioSource||null,capture_tracks:renderedTracks,
   readyState:element.readyState,paused:element.paused};
 };
 if(descriptor?.get&&descriptor?.set){
  Object.defineProperty(HTMLMediaElement.prototype,'srcObject',{configurable:true,
   get(){return descriptor.get.call(this)},
   set(stream){
    descriptor.set.call(this,stream);
    if(this instanceof HTMLAudioElement){
     remoteAudioElement=this;remoteSourceStream=stream;
     window.__claim911RemoteAudioElementState={readyState:this.readyState,paused:this.paused,
      source_tracks:stream?.getAudioTracks?.().length||0,capture_tracks:0};
     window.__claim911PendingRemoteStream=stream;
     if(stream?.getAudioTracks?.().length)attach(stream,'remote-webrtc-track');
     this.addEventListener('playing',()=>window.__claim911CaptureRenderedAssistantAudio?.(),{once:true});
    }
   }
  });
 }
 const OriginalPeerConnection=window.RTCPeerConnection;
 class Claim911TestPeerConnection extends OriginalPeerConnection{
  constructor(...args){
   if(['all','relay'].includes(window.__claim911TestIcePolicy))args[0]={...(args[0]||{}),iceTransportPolicy:window.__claim911TestIcePolicy};
   super(...args);(window.__claim911PeerConnections||=[]).push(this);
   this.addEventListener('track',event=>{
    if(event.track?.kind==='audio'){
     window.__claim911RemoteAudioTracks.push(event.track);
    }
   });
  }
 }
 Object.setPrototypeOf(Claim911TestPeerConnection,OriginalPeerConnection);
 window.RTCPeerConnection=Claim911TestPeerConnection;
}
