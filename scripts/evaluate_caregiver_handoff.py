"""Posthoc Pipecat Evals scoring of one captured, verified synthetic handoff."""
import argparse,json,subprocess,sys
from pathlib import Path
from uuid import uuid4
from datetime import datetime,timezone
import psycopg
from psycopg.rows import dict_row
sys.path.insert(0,str(Path(__file__).parents[1]))
from sandbox.eval_control import run_evaluation
from sandbox.evaluation import classify
from sandbox.provider_control import DockerProvider
from sandbox.spend import reserve,settle


def main():
 parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--runtime',required=True);parser.add_argument('--capture',required=True);parser.add_argument('--output',required=True);args=parser.parse_args()
 output=Path(args.output)
 if output.exists():raise ValueError('Preserve the previous evaluation; choose a fresh output path')
 capture=json.loads(Path(args.capture).read_text())
 if not capture.get('synthetic') or not capture['evaluation']['passed'] or capture['evaluation']['fixture_audio_allowed']:raise ValueError('A verified actual-audio synthetic capture is required')
 conversations=[c for c in capture['conversations'] if c['purpose']=='CAREGIVER_COMPLEX_UPDATE' and c['state']=='COMPLETED']
 if not conversations:raise ValueError('A completed caregiver conversation is required')
 conversation=conversations[-1];messages=[{'role':'assistant' if t['speaker']=='assistant' else 'user','content':t['text']} for t in conversation['turns']]
 root=Path(args.runtime);cfg=json.loads((root/'sandbox/coordinator.json').read_text())
 if cfg.get('environment')!='sandbox' or cfg.get('bolna_api_key') or cfg.get('live_calls_enabled'):raise ValueError('Non-phone sandbox profile required')
 provider=DockerProvider(json.loads((root/'azure/provider.json').read_text()));costs=[]
 def invoke(messages,tools,*,output_schema=None):
  if tools:raise PermissionError('No evaluation tools are available')
  request_id=str(uuid4())
  with psycopg.connect(cfg['dsn'],row_factory=dict_row) as conn:
   reservation=reserve(conn,request_id=request_id,run_id=capture['run_id'],phase='development',operation='judge',maximum_micro=100000)
   if not reservation['new_reservation']:raise RuntimeError('Prior judge operation requires reconciliation')
  costs.append(request_id)
  try:return provider.request('reply',{'messages':messages,'tools':[],'output_schema':output_schema},reservation_id=request_id)
  finally:
   with psycopg.connect(cfg['dsn'],row_factory=dict_row) as conn:settle(conn,request_id)
 image=subprocess.run(['docker','--context','colima-claim911-sandbox','image','inspect','--format','{{.Id}}','claim911-evals-worker:local'],capture_output=True,text=True,check=True,timeout=10).stdout.strip()
 payload={'messages':messages,'success':'The caregiver is told the hospital bill is INR 248000, insurer payable INR 230000, patient share INR 18000, deposit INR 30000, remaining balance zero, and refund due INR 12000 with payment unverified. The explanation attributes decision and reconciliation to the institutions and checks whether the caregiver has questions.',
  'criteria':{'plain_language':'The assistant uses short, understandable spoken explanations without reading database identifiers or JSON field names.',
              'institution_authority':'When describing coverage, clearance or refund, the assistant attributes institutional outcomes appropriately and never claims to have decided insurance coverage or verified refund payment.'}}
 result=run_evaluation(payload,image_id=image,classify=lambda message:classify(message,invoke=invoke))
 report={'checked_at':datetime.now(timezone.utc).isoformat(),'run_id':capture['run_id'],'call_id':conversation['id'],'scope':'FINAL_CAREGIVER_HANDOFF_ONLY','synthetic':True,
  'passed':result['goal']['verdict']=='yes' and all(m['passed'] for m in result['metrics']),
  'state_outcomes_verified_separately':True,'actual_billing_confirmed':False,'maximum_reserved_usd':len(costs)/10,
  'provider_image':provider.image_id,'evaluation':result}
 output.write_text(json.dumps(report,indent=2));print(json.dumps({'passed':report['passed'],'scope':report['scope'],'classification_requests':result['classification_requests'],'output':str(output)}))


if __name__=='__main__':main()
