import json,sys
import pytest
from scripts import bootstrap_profiles


def test_existing_runtime_cannot_silently_change_namespace(tmp_path,monkeypatch):
 (tmp_path/'simulator.json').write_text(json.dumps({'admin_dsn':'host=localhost dbname=postgres'}))
 (tmp_path/'operational').mkdir()
 config=tmp_path/'operational/coordinator.json'
 original=json.dumps({'environment':'operational','dsn':'host=localhost dbname=claim911_operational_other'})
 config.write_text(original)
 monkeypatch.setattr(sys,'argv',['bootstrap_profiles','--runtime',str(tmp_path),'--suffix','fresh'])
 monkeypatch.setattr(bootstrap_profiles.psycopg,'connect',lambda *a,**kw:pytest.fail('Namespace mismatch must stop before database mutation'))
 with pytest.raises(SystemExit,match='does not match'):bootstrap_profiles.main()
 assert config.read_text()==original


def test_invalid_namespace_is_rejected_before_reading_credentials(tmp_path,monkeypatch):
 monkeypatch.setattr(sys,'argv',['bootstrap_profiles','--runtime',str(tmp_path),'--suffix','bad-name'])
 monkeypatch.setattr(bootstrap_profiles.psycopg,'connect',lambda *a,**kw:pytest.fail('Must not connect'))
 with pytest.raises(ValueError,match='alphanumeric'):bootstrap_profiles.main()
