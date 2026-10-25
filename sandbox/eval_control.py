"""Bounded trusted stdio controller for an offline Pipecat Evals container."""
import json,os,re,selectors,subprocess,time
from uuid import uuid4
from sandbox.audio_worker.eval_contract import validate_payload


def run_evaluation(payload,*,image_id,classify,timeout=300):
 if not re.fullmatch(r'sha256:[a-f0-9]{64}',image_id):raise ValueError('Pinned evaluation image required')
 validate_payload(payload)
 container='claim911-evals-'+uuid4().hex
 command=['docker','--context','colima-claim911-sandbox','run','--rm','--name',container,'-i',
  '--network','none','--read-only','--user','65532:65532','--cap-drop','ALL','--security-opt','no-new-privileges:true',
  '--pids-limit','64','--memory','768m','--cpus','1','--tmpfs','/tmp:rw,noexec,nosuid,nodev,size=32m,mode=1777',
  '-e','LOGURU_LEVEL=ERROR',image_id]
 process=subprocess.Popen(command,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL)
 selector=selectors.DefaultSelector();selector.register(process.stdout,selectors.EVENT_READ)
 buffer=bytearray();deadline=time.monotonic()+min(timeout,300);requests=0
 def send(value):process.stdin.write(json.dumps(value).encode()+b'\n');process.stdin.flush()
 try:
  send(payload)
  while time.monotonic()<deadline:
   if not selector.select(timeout=1):continue
   chunk=os.read(process.stdout.fileno(),8192)
   if not chunk:raise RuntimeError('Evaluation ended without a result')
   buffer.extend(chunk)
   if len(buffer)>64000:raise ValueError('Evaluation output bound exceeded')
   while b'\n' in buffer:
    line,_,tail=buffer.partition(b'\n');buffer=bytearray(tail);message=json.loads(line)
    if message.get('type')=='classify':
     requests+=1
     if requests>24:raise ValueError('Classification request limit exceeded')
     answers=classify(message)
     send({'request_id':message['request_id'],'status':200,'answers':answers})
    elif message.get('type')=='result':
     if set(message)!={'type','framework','goal','metrics'} or message['framework']!='pipecat.evals':raise ValueError('Pipecat Evals result required')
     if message['goal'].get('verdict') not in {'yes','no','none'}:raise ValueError('Valid goal verdict required')
     if {m['name'] for m in message['metrics']}!=set(payload['criteria']):raise ValueError('Requested metrics must match result')
     if process.wait(timeout=5)!=0:raise RuntimeError('Evaluation process did not finish successfully')
     return {**message,'image_id':image_id,'classification_requests':requests,'state_verification':False,
      'evaluation_mode':'POSTHOC_SAVED_CONVERSATION','probabilities_calibrated':False}
    else:raise RuntimeError('Evaluation worker failed or emitted an unknown operation')
  raise TimeoutError('Evaluation time bound reached')
 finally:
  selector.close()
  if process.poll() is None:
   subprocess.run(['docker','--context','colima-claim911-sandbox','rm','--force',container],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=10)
   process.kill();process.wait(timeout=5)
  process.stdin.close();process.stdout.close()
