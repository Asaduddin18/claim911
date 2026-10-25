from uuid import uuid4
import httpx,pytest
from coordinator.bolna import Bolna,DispatchUnknown,ProviderRejected


def session(agent):return {'run_id':str(uuid4()),'agent_id':agent,'sip_username':'ephemeral-user','sip_password':'ephemeral-pass','sip_domain':'sip.bolna.ai','wss_url':'wss://sip.bolna.ai/ws','sip_register':False,'expires_in':120,'ice_servers':[]}


def test_mint_uses_only_browser_endpoint_and_returns_no_long_lived_key():
 agent=str(uuid4());requests=[]
 def handler(request):
  requests.append(request);return httpx.Response(200,json=session(agent)|{'internal_account':'must-not-reach-browser'})
 provider=Bolna('bn-synthetic-secret',httpx.Client(base_url='https://api.bolna.ai',transport=httpx.MockTransport(handler)))
 result=provider.web_session(agent,{'claim911_greeting':'Hi, how can I help?','claim911_objective':'Synthetic caregiver intake'})
 assert requests[0].url.path=='/web-call/freeswitch-session' and requests[0].headers['Authorization']=='Bearer bn-synthetic-secret'
 assert 'internal_account' not in result and 'recipient_phone_number' not in requests[0].content.decode()
 assert 'bn-synthetic-secret' not in str(result)


def test_invalid_or_uncertain_session_is_not_retried():
 agent=str(uuid4())
 for bad in [session(agent)|{'expires_in':3600},session(agent)|{'wss_url':'wss://127.0.0.1/private'},session(agent)|{'sip_password':'bn-test'}]:
  calls=[]
  def handler(request):calls.append(request);return httpx.Response(200,json=bad)
  provider=Bolna('bn-test',httpx.Client(base_url='https://api.bolna.ai',transport=httpx.MockTransport(handler)))
  with pytest.raises(DispatchUnknown):provider.web_session(agent,{})
  assert len(calls)==1
 provider=Bolna('bn-test',httpx.Client(base_url='https://api.bolna.ai',transport=httpx.MockTransport(lambda r:httpx.Response(403))))
 with pytest.raises(ProviderRejected):provider.web_session(agent,{})
