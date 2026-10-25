"""Allow verified synthetic sandbox recordings to be replayed through the broker."""
import json
import sqlite3
import time
from pathlib import Path

import psycopg


def backfill(runtime):
    runtime=Path(runtime).resolve()
    sandbox=json.loads((runtime/'sandbox'/'coordinator.json').read_text())
    gateway=json.loads((runtime/'voice-gateway.json').read_text())
    broker=json.loads((runtime/'sandbox'/'bolna-session-broker.json').read_text())
    if sandbox.get('environment')!='sandbox' or sandbox.get('bolna_api_key') or sandbox.get('live_calls_enabled'):
        raise ValueError('A key-free, phone-disabled sandbox database is required')
    route_path=Path(gateway['sandbox_route_db'])
    registry_path=Path(broker['broker_registry_db'])
    registry_path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    now=time.time();count=0
    with psycopg.connect(sandbox['dsn']) as db:
        calls=db.execute('''SELECT c.execution_id,c.id,c.incident_id,c.tool_token_hash
            FROM coordinator.calls c JOIN coordinator.sandbox_runs r ON r.incident_id=c.incident_id
            WHERE c.mode='SANDBOX_AUDIO' AND c.sandbox_audio_provenance='BOLNA_WEBRTC'
              AND c.state='COMPLETED' AND c.recording_consent AND c.recording_url IS NOT NULL
              AND c.execution_id IS NOT NULL''').fetchall()
    with sqlite3.connect(route_path) as routes,sqlite3.connect(registry_path) as registry:
        registry.execute('''CREATE TABLE IF NOT EXISTS sandbox_bolna_sessions(
            execution_id TEXT PRIMARY KEY,call_id TEXT NOT NULL,incident_id TEXT NOT NULL,
            created_at REAL NOT NULL,expires_at REAL NOT NULL)''')
        for execution_id,call_id,incident_id,token_hash in calls:
            route=routes.execute('SELECT 1 FROM sandbox_voice_routes WHERE execution_id=? AND call_token_hash=?',
                (str(execution_id),token_hash)).fetchone()
            if not route:continue
            prior=registry.execute('SELECT call_id,incident_id FROM sandbox_bolna_sessions WHERE execution_id=?',
                (str(execution_id),)).fetchone()
            expected=(str(call_id),str(incident_id))
            if prior and prior!=expected:
                raise ValueError('An execution is already allowlisted for a different synthetic conversation')
            registry.execute('''INSERT INTO sandbox_bolna_sessions(execution_id,call_id,incident_id,created_at,expires_at)
                VALUES(?,?,?,?,?) ON CONFLICT(execution_id) DO UPDATE SET expires_at=excluded.expires_at''',
                (str(execution_id),*expected,now,now+7*24*60*60))
            count+=1
    registry_path.chmod(0o600)
    return count


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime',required=True)
    args=parser.parse_args()
    count=backfill(args.runtime)
    print(f'Allowlisted {count} verified synthetic Bolna recording(s) for private replay.')
