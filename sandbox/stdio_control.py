"""Trusted bounded bridge to a network-disabled Pipecat process.

Only validated synthetic audio operations cross the boundary. No capability or
provider secret is sent to the worker; this control process owns its grant.
"""
import base64,json,os,selectors,subprocess,time
from uuid import uuid4
from fastapi import HTTPException


class AudioExecutionError(RuntimeError):
    def __init__(self,operation,status,diagnostic=None):
        self.diagnostic={'operation':operation,'status':status,'failure':diagnostic}
        super().__init__('Scoped audio operation failed; inspect its boundary status')


def run_worker(gateway,capability,pcm,*,timeout=150,on_event=None):
    if not isinstance(pcm,bytes) or not 0<len(pcm)<=640000 or len(pcm)%2:
        raise ValueError('Bounded mono PCM utterance required')
    container='claim911-audio-'+uuid4().hex
    args=['docker','--context','colima-claim911-sandbox','run','--rm','--name',container,'-i','--network','none',
      '--read-only','--user','65532:65532','--cap-drop','ALL','--security-opt','no-new-privileges:true',
      '--pids-limit','64','--memory','768m','--cpus','1','--tmpfs','/tmp:rw,noexec,nosuid,nodev,size=32m,mode=1777',
      '-e','LOGURU_LEVEL=ERROR','--entrypoint','python','claim911-audio-worker:local','-I','/app/run_stdio.py']
    process=subprocess.Popen(args,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL)
    selector=selectors.DefaultSelector();selector.register(process.stdout,selectors.EVENT_READ)
    buffer=bytearray();deadline=time.monotonic()+min(timeout,180);events=[];spoken=None;reply=None
    def send(body):
        process.stdin.write(json.dumps(body).encode()+b'\n');process.stdin.flush()
    try:
        send({'pcm_base64':base64.b64encode(pcm).decode(),'sample_rate':16000,'channels':1})
        while time.monotonic()<deadline:
            if not selector.select(timeout=min(1,max(0,deadline-time.monotonic()))):continue
            chunk=os.read(process.stdout.fileno(),65536)
            if not chunk:raise RuntimeError('Audio worker ended without a validated result')
            buffer.extend(chunk)
            if len(buffer)>2_000_000:raise RuntimeError('Audio worker output exceeds boundary limit')
            while b'\n' in buffer:
                line,_,tail=buffer.partition(b'\n');buffer=bytearray(tail)
                message=json.loads(line)
                if message.get('type')=='request':
                    if len(events)>=60:raise RuntimeError('Audio worker request limit exceeded')
                    if set(message)!={'type','operation','body'}:raise RuntimeError('Invalid worker request envelope')
                    operation=message['operation'];body=message['body']
                    if not isinstance(body,dict):raise RuntimeError('Invalid worker operation body')
                    try:
                        result=gateway.execute(capability,operation,body)
                        if operation=='synthesize':spoken=base64.b64decode(result['pcm_base64'],validate=True)
                        if operation=='reply':reply=result['text']
                        events.append({'operation':operation,'status':200,
                          'text':result.get('text'),'usage':result.get('usage')})
                        if on_event is not None:on_event(list(events))
                        send({'request_id':body['request_id'],'status':200,'result':result})
                    except HTTPException as exc:
                        events.append({'operation':operation,'status':exc.status_code})
                        if on_event is not None:on_event(list(events))
                        # The controller already knows the authoritative failure.
                        # Do not lose its category behind a later worker EOF.
                        raise AudioExecutionError(operation,exc.status_code,exc.detail if isinstance(exc.detail,dict) else None) from None
                elif message.get('type')=='result':
                    if not message.get('passed'):raise RuntimeError('Pipecat pipeline did not produce a successful audio result')
                    audio=base64.b64decode(message['pcm_base64'],validate=True)
                    if not spoken or audio!=spoken or message.get('text')!=[reply]:
                        raise RuntimeError('Worker result does not match the scoped provider outputs')
                    process.stdin.close();process.wait(timeout=5)
                    if process.returncode!=0:raise RuntimeError('Worker failed after producing output')
                    return {'audio':audio,'text':reply,'events':events,'provenance':'PIPECAT_PIPELINE_STDIO_BROKER',
                            'network':'none','credentials_sent_to_worker':False}
                else:raise RuntimeError('Unknown worker protocol message')
        raise TimeoutError('Bounded audio pipeline run expired')
    finally:
        selector.close()
        if process.poll() is None:
            process.kill();process.wait(timeout=5)
            subprocess.run(['docker','--context','colima-claim911-sandbox','rm','--force',container],
                           stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=10)
        process.stdout.close()
        if not process.stdin.closed:process.stdin.close()
