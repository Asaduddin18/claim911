"""Install only a scoped synthetic seed token. Execution stays disabled by default."""
import argparse,json,secrets
from pathlib import Path


def main():
 parser=argparse.ArgumentParser();parser.add_argument('--runtime',required=True);args=parser.parse_args()
 folder=Path(args.runtime)/'sandbox';corepath=folder/'coordinator.json';simpath=folder/'simulator.json'
 core=json.loads(corepath.read_text());sim=json.loads(simpath.read_text())
 if core.get('environment')!='sandbox' or sim.get('environment')!='sandbox' or core.get('bolna_api_key') or core.get('live_calls_enabled'):
  raise RuntimeError('Isolated non-phone profiles required')
 token=sim['tokens'].get('sandbox_runner') or core.get('sandbox_seed_token') or secrets.token_urlsafe(32)
 if core.get('sandbox_seed_token') and core['sandbox_seed_token']!=token:raise RuntimeError('Resolve the existing token mismatch explicitly')
 sim['tokens']['sandbox_runner']=token;core['sandbox_seed_token']=token
 core.setdefault('sandbox_execution_enabled',False)
 for path,value in [(simpath,sim),(corepath,core)]:
  temporary=path.with_suffix('.tmp');temporary.write_text(json.dumps(value,indent=2));temporary.chmod(0o600);temporary.replace(path)
 print('Scoped sandbox preparation configured; execution setting preserved. No credentials displayed.')


if __name__=='__main__':main()
