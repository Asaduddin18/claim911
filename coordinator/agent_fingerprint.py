"""Stable, secret-free fingerprint for the user-reviewed Bolna assistant config."""
import hashlib,json


def _pick(value,keys):
 return {key:value[key] for key in keys if isinstance(value,dict) and key in value}


def reviewed_config(agent):
 tasks=[]
 for task in agent.get('tasks') or []:
  cfg=task.get('tools_config') or {}
  llm=(cfg.get('llm_agent') or {}).get('llm_config') or {}
  transcriber=cfg.get('transcriber') or {}
  synthesizer=cfg.get('synthesizer') or {}
  voice=synthesizer.get('provider_config') or {}
  api=cfg.get('api_tools') or {}
  tools=[]
  for tool in api.get('tools') or []:
   tools.append({'name':tool.get('name'),'description':tool.get('description'),
    'parameters':tool.get('parameters'),'key':tool.get('key')})
  params={}
  for name,item in sorted((api.get('tools_params') or {}).items()):
   params[name]={'method':item.get('method'),'url':item.get('url'),
    'argument_names':sorted((item.get('param') or {}).keys()) if isinstance(item.get('param'),dict) else None,
    'provider_auth_configured':bool(item.get('api_token'))}
  tasks.append({'llm':_pick(llm,['provider','model','temperature','top_p','top_k','max_tokens','reasoning_effort','frequency_penalty','presence_penalty']),
   'transcriber':_pick(transcriber,['provider','model','language','multilingual','stream','endpointing','noise_reduction','eot_timeout_ms']),
   'synthesizer':{'provider':synthesizer.get('provider'),'audio_format':synthesizer.get('audio_format'),
    'voice':_pick(voice,['model','voice','voice_id','speed','stability','similarity_boost','style','temperature'])},
   'tools':sorted(tools,key=lambda t:str(t.get('name'))),'tool_routes':params,
   'timing':_pick(task.get('task_config') or {},['incremental_delay','optimize_latency',
    'number_of_words_for_interruption','interruption_backoff_period','hangup_after_silence',
    'check_if_user_online','trigger_user_online_message_after','backchanneling','call_terminate'])})
 safe={'agent_name':agent.get('agent_name'),'agent_type':agent.get('agent_type'),
  'welcome_message':agent.get('agent_welcome_message'),'prompts':agent.get('agent_prompts'),
  'tasks':tasks,'webhook_url':agent.get('webhook_url'),
  'webhook_auth_headers':sorted((agent.get('webhook_headers') or {}).keys()) if isinstance(agent.get('webhook_headers'),dict) else bool(agent.get('webhook_headers'))}
 if 'composition_by_language' in agent:
  safe['composition_by_language']=agent['composition_by_language']
 if 'single_prompt_ui' in agent:
  safe['single_prompt_ui']=agent['single_prompt_ui']
 return safe


def fingerprint(agent):
 canonical=json.dumps(reviewed_config(agent),sort_keys=True,separators=(',',':'),ensure_ascii=False,default=str)
 return hashlib.sha256(canonical.encode()).hexdigest()


def legacy_fingerprint(agent):
 """Fingerprint format used before Bolna's effective locale prompt was tracked."""
 legacy=dict(agent)
 legacy.pop('composition_by_language',None)
 legacy.pop('single_prompt_ui',None)
 return fingerprint(legacy)
