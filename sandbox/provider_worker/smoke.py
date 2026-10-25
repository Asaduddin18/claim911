"""One-shot free speech validation. Credentials arrive via stdin, never env/mounts."""
import base64,json,sys
sys.path.insert(0,'/app')
from azure_speech import AzureSpeech
stage='configuration'

def main():
    global stage
    config=json.loads(sys.stdin.readline(20000))
    if config.get('environment')!='sandbox':raise ValueError('Synthetic sandbox required')
    speech=AzureSpeech(config['speech'])
    samples={'en':'This is a synthetic hospital test. The discharge summary needs a signature.',
             'hi':'यह एक काल्पनिक परीक्षण है। अस्पताल से छुट्टी के लिए दस्तावेज़ पर हस्ताक्षर चाहिए।'}
    results=[]
    for language,text in samples.items():
        stage=language+'_synthesis'
        pcm=speech.synthesize(text,language)
        stage=language+'_recognition'
        recognized=speech.transcribe(pcm,language)
        results.append({'language':language,'source_text':text,'recognized_text':recognized['text'],
                        'pcm_base64':base64.b64encode(pcm).decode(),'duration_seconds':len(pcm)/32000})
    print(json.dumps({'provenance':'AZURE_F0_SPEECH_ROUNDTRIP','synthetic':True,'agent_workflow_executed':False,'results':results}))

try:main()
except Exception as exc:
    # No traceback, HTTP response or credential values can escape the broker.
    print(json.dumps({'status':'failed','stage':stage,'error_type':type(exc).__name__,'provider_details_redacted':True}))
    raise SystemExit(1)
