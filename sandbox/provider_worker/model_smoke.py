"""One bounded model connection test after a durable cost reservation."""
import json,sys
sys.path.insert(0,'/app')
from azure_model import AzureModel

try:
    config=json.loads(sys.stdin.readline(20000))
    if config.get('environment')!='sandbox' or not config.get('reservation_id'):
        raise ValueError('Synthetic context and committed reservation required')
    model=AzureModel(config['model'])
    result=model.reply([{'role':'developer','content':'This is a synthetic Claim911 connection test. Return exactly READY. Do not make an insurance decision.'},
                        {'role':'user','content':'Confirm the sandbox model connection.'}])
    print(json.dumps({'provenance':'AZURE_MODEL_CONNECTION_ONLY','synthetic':True,'agent_workflow_executed':False,**result}))
except Exception as exc:
    print(json.dumps({'status':'failed','error_type':type(exc).__name__,'provider_details_redacted':True}))
    raise SystemExit(1)
