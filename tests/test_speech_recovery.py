from http.client import IncompleteRead
import json
import pytest
from sandbox.provider_worker.azure_speech import AzureSpeech


def test_transient_free_speech_connect_failure_recovers_without_another_model_request(monkeypatch):
 from urllib.error import URLError
 monkeypatch.setenv('CLAIM911_EGRESS_PROXY','http://claim911-egress-proxy:3128')
 speech=AzureSpeech({'sku':'F0','region':'eastus','api_key':'synthetic-test'})
 class Recovering(Opener):
  def open(self,request,timeout):
   self.calls+=1
   if self.calls==1:raise URLError('Tunnel connection failed: 400 Invalid egress request')
   return Read(Opener(0))
 speech._opener=Recovering(0)
 assert speech._request('tts','/cognitiveservices/v1',b'fixture')==b'complete fixture response'
 assert speech._opener.calls==2


def test_timestamp_is_spoken_naturally_with_its_exact_date_and_timezone():
 from sandbox.provider_worker.azure_speech import speech_markup
 rendered=speech_markup('Received 2026-10-23T10:20:00+05:30.')
 assert '23 October 2026 at 10:20 AM, UTC plus 5 hours 30 minutes' in rendered
 assert '>2026-10-23T10:20:00+05:30</sub>' in rendered


class Read:
 def __init__(self,opener):self.opener=opener
 def __enter__(self):return self
 def __exit__(self,*a):pass
 def read(self,*a):
  if self.opener.failures:
   self.opener.failures-=1;raise IncompleteRead(b'unusable partial response',100)
  return b'complete fixture response'


class Opener:
 def __init__(self,failures):self.failures=failures;self.calls=0
 def open(self,request,timeout):
  self.calls+=1;assert request.full_url.startswith('https://eastus.tts.speech.microsoft.com/')
  return Read(self)


def test_truncated_free_speech_response_is_discarded_then_retried_once(monkeypatch):
 monkeypatch.setenv('CLAIM911_EGRESS_PROXY','http://claim911-egress-proxy:3128')
 speech=AzureSpeech({'sku':'F0','region':'eastus','api_key':'synthetic-test'})
 speech._opener=Opener(1)
 assert speech._request('tts','/cognitiveservices/v1',b'fixture')==b'complete fixture response'
 assert speech._opener.calls==2


def test_two_truncated_free_responses_can_recover_without_repeating_model_work(monkeypatch):
 monkeypatch.setenv('CLAIM911_EGRESS_PROXY','http://claim911-egress-proxy:3128')
 speech=AzureSpeech({'sku':'F0','region':'eastus','api_key':'synthetic-test'})
 speech._opener=Opener(2)
 assert speech._request('tts','/cognitiveservices/v1',b'fixture')==b'complete fixture response'
 assert speech._opener.calls==3


def test_third_truncated_response_stops_without_unbounded_retries(monkeypatch):
 monkeypatch.setenv('CLAIM911_EGRESS_PROXY','http://claim911-egress-proxy:3128')
 speech=AzureSpeech({'sku':'F0','region':'eastus','api_key':'synthetic-test'})
 speech._opener=Opener(4)
 with pytest.raises(IncompleteRead):speech._request('tts','/cognitiveservices/v1',b'fixture')
 assert speech._opener.calls==3


def test_detailed_recognition_preserves_service_rank_and_exposes_confidence(monkeypatch):
 monkeypatch.setenv('CLAIM911_EGRESS_PROXY','http://claim911-egress-proxy:3128')
 speech=AzureSpeech({'sku':'F0','region':'eastus','api_key':'synthetic-test'})
 def request(service,path,data,headers):
  assert service=='stt' and 'format=detailed' in path
  assert data[:4]==b'RIFF'
  return json.dumps({'RecognitionStatus':'Success','NBest':[
   {'Display':'Has the signed summary been released?','Confidence':0.8},
   {'Display':'Has a summary been released?','Confidence':0.95}]}).encode()
 speech._request=request
 result=speech.transcribe(b'\x01\x00'*16000,'en')
 assert result['text']=='Has the signed summary been released?'
 assert result['confidence']==0.8
 assert len(result['alternatives'])==2


@pytest.mark.parametrize('payload',[
 {'RecognitionStatus':'NoMatch'},
 {'RecognitionStatus':'Success','NBest':[{'Display':'An uncertain guess','Confidence':True}]},
 {'RecognitionStatus':'Success','NBest':[{'Display':'','Confidence':0.99}]},
 {'RecognitionStatus':'Success','NBest':[{'Display':'A guess','Confidence':1.5}]},
])
def test_unusable_recognition_never_becomes_a_participant_question(monkeypatch,payload):
 monkeypatch.setenv('CLAIM911_EGRESS_PROXY','http://claim911-egress-proxy:3128')
 speech=AzureSpeech({'sku':'F0','region':'eastus','api_key':'synthetic-test'})
 speech._request=lambda *args:json.dumps(payload).encode()
 with pytest.raises(ValueError):speech.transcribe(b'\x01\x00'*16000,'en')


def test_long_assistant_turn_fits_existing_forty_second_archive_bound(monkeypatch):
 monkeypatch.setenv('CLAIM911_EGRESS_PROXY','http://claim911-egress-proxy:3128')
 speech=AzureSpeech({'sku':'F0','region':'eastus','api_key':'synthetic-test'})
 requests=[]
 def request(*args):
  requests.append(args)
  return json.dumps({'RecognitionStatus':'Success','NBest':[{'Display':'Are those references correct?','Confidence':0.95}]}).encode()
 speech._request=request
 assert speech.transcribe(b'\x01\x00'*640000,'en')['text']=='Are those references correct?'
 assert len(requests)==1
 with pytest.raises(ValueError):speech.transcribe(b'\x01\x00'*640001,'en')
 assert len(requests)==1
