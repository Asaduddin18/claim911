"""One fixed provider operation, invoked only by the trusted control process."""
import base64,json,sys
sys.path.insert(0,'/app')
from azure_speech import AzureSpeech
from azure_model import AzureModel
from network_diagnostics import network_failure

try:
    envelope=json.loads(sys.stdin.readline(1800000))
    if envelope.get('environment')!='sandbox':raise ValueError('Synthetic sandbox required')
    op=envelope['operation'];body=envelope['body']
    if op=='reply':
        if not envelope.get('reservation_id'):raise ValueError('Committed reservation required')
        result=AzureModel(envelope['model']).reply(body['messages'],tools=body.get('tools'),output_schema=body.get('output_schema'))
    elif op=='transcribe':
        result=AzureSpeech(envelope['speech']).transcribe(base64.b64decode(body['pcm_base64'],validate=True),body['language'])
    elif op=='synthesize':
        pcm=AzureSpeech(envelope['speech']).synthesize(body['text'],body['language'],body.get('speaker','assistant'))
        result={'pcm_base64':base64.b64encode(pcm).decode()}
    else:raise ValueError('Unsupported provider operation')
    print(json.dumps(result))
except Exception as exc:
    codes={'Provider response exceeds bounded audio size':'RESPONSE_TOO_LARGE',
      'Unexpected synthesized audio format':'AUDIO_FORMAT_MISMATCH',
      'Bounded English or Hindi text required':'INVALID_SPEECH_TEXT',
      'Speech recognition did not produce a final result':'NO_FINAL_TRANSCRIPT',
      'Model did not return a complete response':'INCOMPLETE_MODEL_RESPONSE',
      'Synthetic model context exceeds request budget':'MODEL_CONTEXT_TOO_LARGE'}
    error_code=codes.get(str(exc),'REDACTED_PROVIDER_FAILURE')
    print(json.dumps({'status':'failed','error_code':error_code,'error_type':type(exc).__name__,'provider_details_redacted':True,'network_failure':network_failure(exc),'http_status':getattr(exc,'code',None) if type(getattr(exc,'code',None)) is int else None}))
    raise SystemExit(1)
