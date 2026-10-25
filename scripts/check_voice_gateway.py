"""Read-only preflight; never dispatches a call or uses a valid call token."""
import argparse,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parents[1]))
from coordinator.gateway_preflight import check_gateway
p=argparse.ArgumentParser();p.add_argument('--runtime',required=True);args=p.parse_args()
cfg=json.loads((Path(args.runtime)/'coordinator.json').read_text())
result=check_gateway(cfg)
print(json.dumps(result))
raise SystemExit(0 if result['ready'] else 1)
