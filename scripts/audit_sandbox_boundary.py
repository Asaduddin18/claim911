"""Read-only topology audit plus credential-free probes in actual worker images.

No provider requests, institution operations, phone dispatch or runtime mounts.
"""
import argparse,json,re,subprocess,sys
from pathlib import Path
from datetime import datetime,timezone
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from sandbox.provider_control import DockerProvider
from scripts.configure_sandbox_bolna import _write_private


def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--runtime',required=True);p.add_argument('--output',required=True);a=p.parse_args()
 output=Path(a.output).resolve()
 if output.exists():raise ValueError('Preserve existing audit evidence')
 project=Path(__file__).resolve().parents[1];root=Path(a.runtime).resolve()
 cfg=json.loads((root/'azure/provider.json').read_text())
 provider=DockerProvider(cfg) # Existing fail-closed image/network/proxy inspection.
 vm=Path.home()/'.colima/claim911-sandbox/colima.yaml';text=vm.read_text()
 vm_checks={'no_host_mounts':bool(re.search(r'^mounts:\s*(?:null|\[\])\s*$',text,re.M)),
            'no_agent_forwarding':bool(re.search(r'^forwardAgent:\s*false\s*$',text,re.M))}
 report={'checked_at':datetime.now(timezone.utc).isoformat(),'scope':'SANDBOX_WORKER_BOUNDARY',
  'provider_requests':0,'phone_dispatch':False,'vm_checks':vm_checks,
  'trusted_provider_topology_validated':True,'trusted_provider_image':provider.image_id,'workers':[],
  'limits':'Checks the current configured container and VM boundary. This is not proof against operating-system vulnerabilities or a complete source-code security review.'}
 code=(project/'sandbox/isolation/probe.py').read_text()
 for tag in ('claim911-audio-worker:local','claim911-evals-worker:local'):
  image=subprocess.run(['docker','--context','colima-claim911-sandbox','image','inspect','--format','{{.Id}}',tag],capture_output=True,text=True,check=True,timeout=10).stdout.strip()
  if not re.fullmatch(r'sha256:[a-f0-9]{64}',image):raise ValueError('Pinned worker image required')
  cmd=['docker','--context','colima-claim911-sandbox','run','--rm','-i','--network','none',
       '--read-only','--user','65532:65532','--cap-drop','ALL','--security-opt','no-new-privileges:true',
       '--pids-limit','32','--memory','128m','--cpus','0.5',
       '--tmpfs','/tmp:rw,noexec,nosuid,nodev,size=8m,mode=1777','--entrypoint','python',image,'-I','-']
  result=subprocess.run(cmd,input=code,capture_output=True,text=True,timeout=30)
  try:probe=json.loads(result.stdout)
  except ValueError:probe={'passed':False,'failure':'Probe did not return valid evidence'}
  report['workers'].append({'image':image,'tag':tag,'exit_code':result.returncode,'probe':probe})
 report['passed']=all(vm_checks.values()) and all(w['exit_code']==0 and w['probe'].get('passed') is True for w in report['workers'])
 _write_private(output,report)
 print(json.dumps({'passed':report['passed'],'workers':len(report['workers']),'provider_requests':0,'output':str(output)}))
 if not report['passed']:raise SystemExit(1)


if __name__=='__main__':main()
