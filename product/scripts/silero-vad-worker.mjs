import {spawn,execFileSync} from 'node:child_process';
import {readFile} from 'node:fs/promises';
import {randomUUID} from 'node:crypto';

// The pinned package/model stays in the existing VM image. Only synthetic PCM
// crosses stdin. No mounts, provider configuration, role facts or network.
export async function createSileroVad(){
 const image=execFileSync('docker',['--context','colima-claim911-sandbox','image','inspect','--format','{{.Id}}','claim911-audio-worker:local'],{encoding:'utf8',timeout:10000}).trim();
 if(!/^sha256:[a-f0-9]{64}$/.test(image))throw new Error('The isolated audio image could not be verified.');
 const source=await readFile(new URL('../../sandbox/audio_worker/vad_stdio.py',import.meta.url),'utf8');
 const name='claim911-vad-'+randomUUID();
 const process=spawn('docker',['--context','colima-claim911-sandbox','run','--rm','--name',name,'-i',
  '--network','none','--read-only','--user','65532:65532','--cap-drop','ALL','--security-opt','no-new-privileges:true',
  '--pids-limit','64','--memory','512m','--cpus','1','--tmpfs','/tmp:rw,noexec,nosuid,nodev,size=16m,mode=1777',
  '-e','LOGURU_LEVEL=ERROR','--entrypoint','python',image,'-I','-u','-c',source],{stdio:['pipe','pipe','ignore']});
 const remove=()=>{try{execFileSync('docker',['--context','colima-claim911-sandbox','rm','--force',name],{timeout:10000,stdio:'ignore'});}catch{}};
 let buffer='',counter=0,closed=false,readyResolve,readyReject;
 const waiting=new Map();
 const ready=new Promise((resolve,reject)=>{readyResolve=resolve;readyReject=reject;});
 const fail=()=>{readyReject(new Error('The isolated Silero worker is unavailable.'));for(const value of waiting.values())value.reject(new Error('Silero worker stopped.'));waiting.clear();};
 process.stdout.on('data',chunk=>{
  buffer+=chunk.toString();if(buffer.length>100000){process.kill();fail();return;}
  while(buffer.includes('\n')){
   const at=buffer.indexOf('\n'),line=buffer.slice(0,at);buffer=buffer.slice(at+1);
   try{const value=JSON.parse(line);
    if(value.ready===true&&value.detector==='SILERO_PIPECAT')readyResolve(value);
    else{const pending=waiting.get(value.id);if(pending){waiting.delete(value.id);pending.resolve(value);}}
   }catch{process.kill();fail();}
  }
 });
 process.on('error',fail);process.on('exit',()=>{closed=true;fail();});
 const startTimeout=setTimeout(()=>{readyReject(new Error('Silero worker startup timed out.'));process.kill();},20000);
 try{await ready;}catch(error){process.kill();remove();throw error;}finally{clearTimeout(startTimeout);}
 return {provenance:{detector:'SILERO_PIPECAT',image,network:'none',credentials_sent:false},
  async analyze(pcmBase64){
   if(closed)throw new Error('The Silero worker has ended.');
   const id=++counter;
   return new Promise((resolve,reject)=>{
    const timer=setTimeout(()=>{waiting.delete(id);reject(new Error('Silero audio analysis timed out.'));},10000);
    waiting.set(id,{resolve:value=>{clearTimeout(timer);resolve(value)},reject:error=>{clearTimeout(timer);reject(error)}});
    process.stdin.write(JSON.stringify({id,pcm_base64:pcmBase64})+'\n');
   });
  },
  async close(){
   if(closed){remove();return;}
   process.stdin.end();
   let timer;
   await Promise.race([new Promise(resolve=>process.once('exit',resolve)),new Promise(resolve=>{timer=setTimeout(resolve,3000);})]);
   clearTimeout(timer);
   if(!closed)process.kill();remove();
  }};
}
