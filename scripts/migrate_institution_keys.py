"""Add distinct synthetic issuer keys without rotating existing credentials."""
import argparse,base64,json,os
from pathlib import Path
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization


def install(runtime):
    sim_path=runtime/'simulator.json';core_path=runtime/'coordinator.json'
    sim=json.loads(sim_path.read_text());core=json.loads(core_path.read_text())
    for issuer in ['hospital','insurer']:
        field=issuer+'_signing_private_key'
        if field not in sim:
            key=Ed25519PrivateKey.generate()
            sim[field]=base64.b64encode(key.private_bytes(serialization.Encoding.Raw,serialization.PrivateFormat.Raw,serialization.NoEncryption())).decode()
        key=Ed25519PrivateKey.from_private_bytes(base64.b64decode(sim[field]))
        core[issuer+'_public_key']=base64.b64encode(key.public_key().public_bytes(serialization.Encoding.Raw,serialization.PublicFormat.Raw)).decode()
    for p,data in [(sim_path,sim),(core_path,core)]:
        p.write_text(json.dumps(data,indent=2));os.chmod(p,0o600)
    print('Distinct synthetic hospital and insurer issuer keys configured; coordinator has public keys only.')


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--runtime',required=True);args=p.parse_args();install(Path(args.runtime))
