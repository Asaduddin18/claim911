// Capture runs independently of model/network waits, with one operation at a time.
export function createBackgroundAudioPump(capture,{intervalMs=100}={}){
 let pending=null,error=null,stopped=false;
 const tick=()=>{
  if(stopped||pending||error)return;
  pending=Promise.resolve().then(capture).catch(cause=>{error=cause;})
   .finally(()=>{pending=null;});
 };
 const timer=setInterval(tick,intervalMs);tick();
 return {
  check(){if(error)throw error;},
  async stop(){stopped=true;clearInterval(timer);if(pending)await pending;},
 };
}
