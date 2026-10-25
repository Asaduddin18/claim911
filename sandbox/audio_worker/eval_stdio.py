"""Pipecat Evals over saved synthetic dialogue, with a credential-free stdio judge."""
import asyncio,json,sys
sys.path.insert(0,'/app')
from eval_contract import validate_payload
from dataclasses import asdict
from uuid import uuid4
from pipecat.classifiers.base_classifier import BaseClassifier,YesNoQuestion,YesNoResult,ChoiceQuestion,ChoiceResult
from pipecat.evals.judge import EvalJudge
from pipecat.evals.simulation import EvalSimulationScenario,EvalSimulationMetric
from pipecat.evals.simulation_judge import EvalSimulationJudge


class StdioClassifier(BaseClassifier):
 def __init__(self):super().__init__();self.lock=asyncio.Lock()
 async def _ask(self,state,questions,images=()):
  if images or len(questions)>12:raise ValueError('Bounded text classification only')
  async with self.lock:
   id=str(uuid4());payload={'type':'classify','request_id':id,'state':state,'questions':{k:v.model_dump() for k,v in questions.items()}}
   encoded=json.dumps(payload)
   if len(encoded)>24000:raise ValueError('Judge question bound exceeded')
   print(encoded,flush=True)
   line=await asyncio.to_thread(sys.stdin.readline,24001)
   if len(line)>24000:raise ValueError('Judge response bound exceeded')
   response=json.loads(line)
   if response.get('request_id')!=id or response.get('status')!=200:raise ValueError('Classification unavailable')
   answers=response['answers'];results={}
   if set(answers)!=set(questions):raise ValueError('Incomplete classifier answers')
   for key,question in questions.items():
    answer=answers[key]
    if isinstance(question,YesNoQuestion):
     probability=answer['probability']
     if type(probability) not in {int,float} or not 0<=probability<=1:raise ValueError('Invalid probability')
     results[key]=YesNoResult(probability=probability)
    elif isinstance(question,ChoiceQuestion):
     probabilities=answer['probabilities']
     if set(probabilities)!=set(question.options) or any(type(v) not in {int,float} or not 0<=v<=1 for v in probabilities.values()) or abs(sum(probabilities.values())-1)>0.02:raise ValueError('Invalid option probabilities')
     choice=max(probabilities,key=probabilities.get);results[key]=ChoiceResult(choice=choice,probabilities=probabilities,confidence=probabilities[choice])
    else:raise ValueError('Unsupported classifier question')
   return results,None


async def main():
 line=sys.stdin.readline(24001)
 if len(line)>24000:raise ValueError('Conversation bound exceeded')
 data=validate_payload(json.loads(line))
 scenario=EvalSimulationScenario(name='claim911-captured-dialogue',persona='Synthetic participants in the labeled conversation',goal='Respond to the actual questions truthfully',success=data['success'],metrics=[EvalSimulationMetric(name=k,criterion=v,min_score=1) for k,v in data['criteria'].items()])
 judge=EvalJudge(StdioClassifier(),explainer=None,allow_continue=False)
 try:result=await EvalSimulationJudge(scenario,judge=judge).judge(data['messages'])
 finally:await judge.close()
 print(json.dumps({'type':'result','framework':'pipecat.evals','goal':asdict(result.goal),'metrics':[asdict(m) for m in result.metrics]}),flush=True)


try:asyncio.run(main())
except Exception as exc:
 print(json.dumps({'type':'error','error_type':type(exc).__name__}),flush=True);raise SystemExit(1)
