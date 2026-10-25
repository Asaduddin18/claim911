"""Fixed deployed-model adapter. No arbitrary provider or deployment selection."""
import json,re
import os
from urllib.parse import urlsplit
from urllib.request import Request,build_opener,ProxyHandler
try:
    from .azure_speech import NoRedirects
except ImportError:
    from azure_speech import NoRedirects

FUNCTIONS={'claim911_report_references','claim911_report_query','claim911_report_document','claim911_report_update','release_signed_summary','publish_own_document','dispatch_approved_packet','link_enhancement','issue_fixed_decision','reconcile'}


def validate_output_schema(schema,depth=0):
    if not isinstance(schema,dict) or depth>6:raise ValueError('Bounded numeric evaluation schema required')
    if schema=={'type':'number'}:return
    if (set(schema)!={'type','properties','required','additionalProperties'} or schema['type']!='object'
        or schema['additionalProperties'] is not False or not isinstance(schema['properties'],dict)
        or not 1<=len(schema['properties'])<=12 or not isinstance(schema['required'],list)
        or len(schema['required'])!=len(schema['properties']) or any(not isinstance(k,str) for k in schema['required'])
        or set(schema['required'])!=set(schema['properties'])):
        raise ValueError('Closed required evaluation objects only')
    for name,child in schema['properties'].items():
        if not isinstance(name,str) or not 0<len(name)<=100:raise ValueError('Bounded evaluation field name required')
        validate_output_schema(child,depth+1)


def validate_messages(messages):
    pending=set()
    for message in messages:
        if not isinstance(message,dict):raise ValueError('Structured conversation message required')
        role=message.get('role')
        if role=='tool':
            if set(message)!={'role','content','tool_call_id'} or message['tool_call_id'] not in pending or not isinstance(message['content'],str):
                raise ValueError('Tool result must match a preceding allowed function call')
            pending.remove(message['tool_call_id'])
        elif role=='assistant' and 'tool_calls' in message:
            if set(message)!={'role','content','tool_calls'} or message['content'] is not None and not isinstance(message['content'],str):
                raise ValueError('Bounded assistant tool message required')
            calls=message['tool_calls']
            if not isinstance(calls,list) or len(calls)!=1:raise ValueError('One function call per message required')
            call=calls[0]
            if set(call)!={'id','type','function'} or call['type']!='function' or not isinstance(call['id'],str) or not 0<len(call['id'])<=100:
                raise ValueError('Bounded function call required')
            function=call['function']
            if set(function)!={'name','arguments'} or function['name'] not in FUNCTIONS or not isinstance(function['arguments'],str):
                raise ValueError('Only approved function messages are enabled')
            if pending:raise ValueError('Resolve the prior function before another call')
            pending.add(call['id'])
        elif set(message)!={'role','content'} or role not in {'developer','user','assistant'} or not isinstance(message['content'],str) or pending:
            raise ValueError('Plain synthetic conversation context required')
    if pending:raise ValueError('A function response is required before another model request')


class AzureModel:
    def __init__(self,config):
        parsed=urlsplit(config['endpoint'])
        if parsed.scheme!='https' or not re.fullmatch(r'[a-z0-9-]+\.openai\.azure\.com',parsed.netloc) or parsed.path not in {'','/'} or parsed.query or parsed.fragment:
            raise ValueError('Verified first-party Azure OpenAI endpoint required')
        if config['model']!='gpt-5-mini' or not re.fullmatch(r'[a-zA-Z0-9_.-]{1,64}',config['deployment']):
            raise ValueError('Only the verified deployed sandbox model is enabled')
        self._url=config['endpoint'].rstrip('/')+'/openai/v1/chat/completions'
        self._key=config['api_key'];self._deployment=config['deployment']
        proxy=os.environ.get('CLAIM911_EGRESS_PROXY','')
        if proxy!='http://claim911-egress-proxy:3128':
            raise ValueError('Restricted sandbox egress proxy is required')
        self._opener=build_opener(ProxyHandler({'https':proxy}),NoRedirects())

    def reply(self,messages,tools=None,output_schema=None):
        if not isinstance(messages,list) or not 1<=len(messages)<=40:raise ValueError('Bounded model context required')
        validate_messages(messages)
        if len(json.dumps({'messages':messages,'tools':tools,'output_schema':output_schema}).encode())>24000:raise ValueError('Synthetic model context exceeds request budget')
        payload={'model':self._deployment,'messages':messages,'max_completion_tokens':2048,'reasoning_effort':'low'}
        if output_schema is not None:
            if tools:raise ValueError('Evaluation structured output cannot invoke tools')
            validate_output_schema(output_schema)
            payload['response_format']={'type':'json_schema','json_schema':{'name':'claim911_evaluation','strict':True,'schema':output_schema}}
        if tools:
            if not isinstance(tools,list) or len(tools)>2 or any(t.get('type')!='function' or t.get('function',{}).get('name') not in FUNCTIONS for t in tools):
                raise ValueError('Only approved Claim911 reporting functions are enabled')
            payload.update(tools=tools,parallel_tool_calls=False)
        request=Request(self._url,data=json.dumps(payload).encode(),headers={'api-key':self._key,'Content-Type':'application/json'})
        with self._opener.open(request,timeout=45) as response:
            raw=response.read(1_000_001)
        if len(raw)>1_000_000:raise ValueError('Model response exceeds gateway bound')
        result=json.loads(raw);choice=result['choices'][0]
        calls=choice['message'].get('tool_calls') or []
        if choice['finish_reason'] not in {'stop','tool_calls'} or not (choice['message'].get('content') or calls):
            raise ValueError('Model did not return a complete response')
        return {'text':choice['message'].get('content'),'tool_calls':calls,'usage':result.get('usage',{}),'model':result.get('model')}
