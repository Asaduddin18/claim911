"""Screen preserved voice reports without making provider requests."""
import argparse,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from sandbox.release_evidence import consecutive


def main():
 parser=argparse.ArgumentParser();parser.add_argument('--reports',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
 args=parser.parse_args();reports=[]
 for path in args.reports.glob('Claim911_Run_*.json'):
  report=json.loads(path.read_text())
  if report.get('run_id') and report.get('started_at') and report.get('finished_at'):reports.append(report)
 result=consecutive(reports);result['reports_screened']=len(reports)
 args.output.write_text(json.dumps(result,indent=2)+'\n')
 print(json.dumps(result))


if __name__=='__main__':main()
