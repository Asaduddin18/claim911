"""Create isolated local roles, schemas and service configuration. Never prints secrets."""
import argparse
import base64
import json
import os
from pathlib import Path
import secrets

import psycopg
from psycopg import sql
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--admin-dsn', default='postgresql://claim911@127.0.0.1:55432/postgres')
    parser.add_argument('--runtime', required=True)
    args = parser.parse_args()
    runtime = Path(args.runtime).resolve()
    runtime.mkdir(parents=True, exist_ok=True, mode=0o700)
    config_path = runtime / 'simulator.json'
    if config_path.exists():
        raise SystemExit('Configuration already exists. Reuse it; bootstrap will not rotate credentials.')
    with psycopg.connect(args.admin_dsn, autocommit=True) as conn:
        for role in ['claim911_hospital', 'claim911_claims', 'claim911_core']:
            if not conn.execute('SELECT 1 FROM pg_roles WHERE rolname=%s', (role,)).fetchone():
                conn.execute(sql.SQL('CREATE ROLE {} LOGIN').format(sql.Identifier(role)))
        conn.execute((Path(__file__).parents[1] / 'simulator/schema.sql').read_text())
    private = Ed25519PrivateKey.generate()
    private_bytes = private.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw,
                                          serialization.NoEncryption())
    public_bytes = private.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    config = {
        'admin_dsn': args.admin_dsn,
        'hospital_dsn': args.admin_dsn.replace('://claim911@', '://claim911_hospital@'),
        'claims_dsn': args.admin_dsn.replace('://claim911@', '://claim911_claims@'),
        'tokens': {role: secrets.token_urlsafe(32) for role in ['hospital','claims','insurer','agent','evaluator']},
        'signing_private_key': base64.b64encode(private_bytes).decode(),
    }
    core = {
        'dsn': args.admin_dsn.replace('://claim911@', '://claim911_core@'),
        'simulator_url': 'http://127.0.0.1:8111',
        'simulator_agent_token': config['tokens']['agent'],
        'receipt_public_key': base64.b64encode(public_bytes).decode(),
        'operator_token': secrets.token_urlsafe(32),
        'webhook_token': secrets.token_urlsafe(32),
        'gateway_token': secrets.token_urlsafe(32),
    }
    for path, data in [(config_path, config), (runtime/'coordinator.json', core)]:
        path.write_text(json.dumps(data, indent=2))
        os.chmod(path, 0o600)
    from migrate_institution_keys import install
    install(runtime)
    print('Database roles and schemas installed. Separate service configurations saved privately.')


if __name__ == '__main__':
    main()
