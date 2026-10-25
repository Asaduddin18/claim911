// Capture incrementally from the fixed-size WebRTC ring. A logical speech turn
// may span several windows; no snapshot or stored turn grows without a bound.
export class BoundedSpeechCapture {
 constructor({startMs,take,chunkMs=8000,maxMs=40000}){
  if(!Number.isFinite(startMs)||startMs<0||typeof take!=='function'||chunkMs<=0||chunkMs>10000||maxMs>40000||maxMs<chunkMs)
   throw new TypeError('Bounded speech capture configuration required.');
  this.start=startMs;this.cursor=startMs;this.take=take;this.chunkMs=chunkMs;this.maxMs=maxMs;this.parts=[];this.finished=false;
 }
 async snapshot(endMs,final=false){
  if(this.finished||!Number.isFinite(endMs)||endMs<this.cursor||endMs-this.start>this.maxMs)
   throw new Error('Assistant speech exceeded the bounded turn contract.');
  while(endMs-this.cursor>=this.chunkMs||(final&&endMs>this.cursor)){
   const end=Math.min(endMs,this.cursor+this.chunkMs);
   const raw=await this.take({start_ms:this.cursor,end_ms:end});
   const pcm=Buffer.from(raw||'','base64');
   const expected=(end-this.cursor)*32;
   if(!pcm.length||pcm.length%2||Math.abs(pcm.length-expected)>4)
    throw new Error('Assistant audio snapshot was missing or incomplete.');
   this.parts.push(pcm);this.cursor=end;
  }
  if(final){this.finished=true;return Buffer.concat(this.parts).toString('base64');}
  return null;
 }
}
