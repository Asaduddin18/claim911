import copy
from coordinator.agent_fingerprint import fingerprint,reviewed_config


def agent():
 return {'id':'synthetic-id','agent_name':'Claim911','agent_type':'conversation','agent_welcome_message':'Welcome',
  'agent_prompts':{'task_1':{'system_prompt':'Read exact facts'}},'webhook_url':'https://voice.example/voice/webhook',
  'webhook_headers':{'Authorization':'SECRET'},'tasks':[{'tools_config':{
   'llm_agent':{'llm_config':{'provider':'azure','model':'gpt-4.1-mini','api_key':'hidden','temperature':0.2}},
   'transcriber':{'provider':'deepgram','model':'nova-3','language':'en','api_key':'also-hidden'},
   'synthesizer':{'provider':'elevenlabs','provider_config':{'voice_id':'voice-a','voice':'English','api_key':'hidden'}},
   'api_tools':{'tools':[{'name':'claim911_context','description':'Fetch context','parameters':{'type':'object'}}],
    'tools_params':{'claim911_context':{'method':'POST','url':'https://voice.example/context','api_token':'SECRET','param':'call_token'}}}}}]}


def test_fingerprint_tracks_assistant_behavior_routes_and_voice_but_omits_secrets():
 original=agent();base=fingerprint(original);safe=reviewed_config(original)
 assert 'SECRET' not in str(safe) and 'hidden' not in str(safe)
 for mutate in [
  lambda a:a['agent_prompts']['task_1'].update(system_prompt='Different prompt'),
  lambda a:a['tasks'][0]['tools_config']['llm_agent']['llm_config'].update(model='other-model'),
  lambda a:a['tasks'][0]['tools_config']['synthesizer']['provider_config'].update(voice_id='voice-b'),
  lambda a:a['tasks'][0].update(task_config={'optimize_latency':False,'incremental_delay':600}),
  lambda a:a['tasks'][0]['tools_config']['api_tools']['tools_params']['claim911_context'].update(url='https://other.example/context'),
  lambda a:a.setdefault('composition_by_language',{}).update(en=[{'type':'text','text':'Different effective prompt'}]),
 ]:
  changed=copy.deepcopy(original);mutate(changed);assert fingerprint(changed)!=base
 changed=copy.deepcopy(original);changed['webhook_headers']['Authorization']='ROTATED-SECRET'
 changed['tasks'][0]['tools_config']['llm_agent']['llm_config']['api_key']='rotated'
 assert fingerprint(changed)==base
