"""Verify Azure resource identity and reconcile only free speech reservations."""
import argparse,hashlib,json,subprocess,sys
from pathlib import Path
from datetime import datetime,timezone,timedelta
import psycopg
from psycopg.rows import dict_row
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from sandbox.speech_costs import reconcile_speech,validate_proof
from scripts.configure_sandbox_bolna import _write_private


def az(*args):
    result=subprocess.run(['/opt/homebrew/bin/az',*args,'--output','json'],capture_output=True,text=True,timeout=60)
    if result.returncode:raise RuntimeError('Azure management verification unavailable; holds retained')
    return json.loads(result.stdout)


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--runtime',required=True);parser.add_argument('--apply',action='store_true');args=parser.parse_args()
    root=Path(args.runtime).resolve();profile=root/'azure/provider.json'
    provider=json.loads(profile.read_text());cfg=json.loads((root/'sandbox/coordinator.json').read_text())
    resource=json.loads((root/'azure/provisioning.json').read_text())
    if provider.get('environment')!='sandbox' or cfg.get('environment')!='sandbox':raise ValueError('Isolated sandbox profiles required')
    group=resource['resource_group'];name=resource['speech_name']
    account=az('cognitiveservices','account','show','--resource-group',group,'--name',name)
    if account.get('sku',{}).get('name')!='F0' or account.get('kind')!='SpeechServices' or account.get('location')!='eastus':
        raise ValueError('The deployed speech resource is not the reviewed free tier')
    keys=az('cognitiveservices','account','keys','list','--resource-group',group,'--name',name)
    keyhash=hashlib.sha256(provider['speech']['api_key'].encode()).hexdigest()
    if keyhash not in {hashlib.sha256(str(keys[k]).encode()).hexdigest() for k in ('key1','key2')}:
        raise ValueError('Configured speech credentials do not match the verified resource')
    created=account['systemData']['createdAt'];when=datetime.fromisoformat(created.replace('Z','+00:00'))
    if datetime.now(timezone.utc)-when>timedelta(days=7):raise ValueError('Historical management evidence requires a separate audit')
    events=az('monitor','activity-log','list','--resource-id',account['id'],'--start-time',(when-timedelta(minutes=5)).isoformat())
    writes=[e for e in events if e.get('operationName',{}).get('value','').lower()=='microsoft.cognitiveservices/accounts/write'
        and e.get('status',{}).get('value','').lower()=='succeeded']
    if not writes:raise ValueError('Resource write history is unavailable; historical holds retained')
    last_write=max(datetime.fromisoformat(e['eventTimestamp'].replace('Z','+00:00')) for e in writes)
    proof={'kind':'SpeechServices','sku':'F0','region':'eastus','resource_name':name,
        'credential_sha256':keyhash,'profile_sha256':hashlib.sha256(profile.read_bytes()).hexdigest(),
        'profile_saved_at':datetime.fromtimestamp(profile.stat().st_mtime,timezone.utc).isoformat(),
        'resource_created_at':created,'verified_at':datetime.now(timezone.utc).isoformat(),
        'last_resource_write_at':last_write.isoformat(),'no_updates_since_resource_write':True,
        'pricing_source':'https://azure.microsoft.com/en-us/pricing/details/speech/'}
    validate_proof(proof,provider['speech'])
    _write_private(root/'azure/free-speech-evidence.json',proof)
    if not args.apply:print(json.dumps({'verified':True,'scope':'F0_SPEECH_ONLY','ledger_changed':False}));return
    with psycopg.connect(cfg['dsn'],row_factory=dict_row) as conn:
        result=reconcile_speech(conn,proof,provider['speech'])
    print(json.dumps(result))


if __name__=='__main__':main()
