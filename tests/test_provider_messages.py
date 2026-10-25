import pytest
from sandbox.provider_worker.azure_model import validate_messages,validate_output_schema,AzureModel
from sandbox.evaluation import answer_schema


def sequence(name='release_signed_summary'):
 return [{'role':'developer','content':'Synthetic medical records desk.'},
 {'role':'assistant','content':None,'tool_calls':[{'id':'release1','type':'function','function':{'name':name,'arguments':'{}'}}]},
 {'role':'tool','tool_call_id':'release1','content':'{"ready":true}'}]


def test_native_function_result_round_trip_is_supported():
 validate_messages(sequence())


def test_unrelated_or_unmatched_function_results_are_rejected():
 for messages in [sequence('read_host_file'),sequence()[:-1],sequence()[2:]]:
  with pytest.raises(ValueError):validate_messages(messages)


def test_history_cannot_insert_an_unresolved_second_function():
 messages=sequence();messages.insert(2,messages[1])
 with pytest.raises(ValueError):validate_messages(messages)


def test_evaluator_schema_requires_all_exact_choice_options():
 schema=answer_schema({'score':{'options':{'0':None,'1':None,'2':None}}})
 validate_output_schema(schema)
 options=schema['properties']['answers']['properties']['score']['properties']['probabilities']
 assert options['required']==['0','1','2'] and options['additionalProperties'] is False
 for wrong in ({'$ref':'https://external.invalid/schema'},schema|{'additionalProperties':True}):
  with pytest.raises(ValueError):validate_output_schema(wrong)


def test_model_adapter_sends_strict_evaluation_schema_without_tools():
 import json
 captured=[]
 class Response:
  def __enter__(self):return self
  def __exit__(self,*a):pass
  def read(self,*a):return json.dumps({'choices':[{'finish_reason':'stop','message':{'content':'{"answers":{"goal":{"probability":1}}}'}}]}).encode()
 class Opener:
  def open(self,request,timeout):captured.append(json.loads(request.data));return Response()
 model=object.__new__(AzureModel);model._deployment='gpt-5-mini';model._url='https://synthetic.openai.azure.com/openai/v1/chat/completions';model._key='synthetic-test';model._opener=Opener()
 schema=answer_schema({'goal':{'yes':None,'no':None}})
 model.reply([{'role':'user','content':'Classify the synthetic answer.'}],output_schema=schema)
 assert captured[0]['response_format']=={'type':'json_schema','json_schema':{'name':'claim911_evaluation','strict':True,'schema':schema}}
 assert 'tools' not in captured[0]
