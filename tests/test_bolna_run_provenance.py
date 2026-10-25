from datetime import datetime,timezone,timedelta

from sandbox import runs


def test_only_exact_legacy_or_fingerprinted_bolna_provenance_is_accepted():
    assert runs.valid_provider_configuration({'model':'gpt-5-mini','model_version':'2025-08-07',
        'speech_tier':'F0','transport':'PIPECAT_STDIO'})
    assert runs.valid_provider_configuration({'transport':'BOLNA_WEBRTC','assistant_config_sha256':'a'*64})
    assert not runs.valid_provider_configuration({'transport':'BOLNA_WEBRTC','assistant_config_sha256':'A'*64})
    assert not runs.valid_provider_configuration({'transport':'BOLNA_WEBRTC','assistant_config_sha256':'a'*64,'api_key':'secret'})
    assert not runs.valid_provider_configuration({'transport':'PIPECAT_STDIO','assistant_config_sha256':'a'*64})


class Result:
    def __init__(self,row):self.row=row
    def fetchone(self):return self.row


class FakeConnection:
    def __init__(self,incident):self.incident=incident;self.updated=None
    def execute(self,sql,args):
        if sql.startswith('SELECT consent_active'):
            return Result(self.incident)
        self.updated=args
        return Result(None)


def test_worker_lease_renewal_requires_current_lease_and_consent(monkeypatch):
    now=datetime(2026,10,24,tzinfo=timezone.utc)
    row={'state':'RUNNING','lease_token':'current','lease_until':now+timedelta(seconds=5),
         'incident_id':'case','consent_version':3}
    monkeypatch.setattr(runs,'get',lambda *_args,**_kwargs:row)
    conn=FakeConnection({'consent_active':True,'consent_version':3})
    assert runs.renew(conn,'run','current',now=now)
    assert conn.updated[0]==now+timedelta(minutes=3)
    assert not runs.renew(FakeConnection({'consent_active':True,'consent_version':3}),
                          'run','stale',now=now)
    row['lease_until']=now
    assert not runs.renew(FakeConnection({'consent_active':True,'consent_version':3}),
                          'run','current',now=now)
    row['lease_until']=now+timedelta(seconds=5)
    assert not runs.renew(FakeConnection({'consent_active':False,'consent_version':3}),
                          'run','current',now=now)
