from sandbox.replay import render,export
import pytest


def test_recorded_replay_escapes_conversation_and_labels_unpaid_refund():
 snapshot={'summary':{'statements':[{'text':'Refund due INR 12,000.','source':{'issuer':'Hospital billing'}}],
  'pending':['Refund payment has not been verified.']}}
 html=render(snapshot,[{'purpose':'CAREGIVER_COMPLEX_UPDATE','state':'COMPLETED','turns':[{'speaker':'participant','text':'<script>unsafe()</script>','audio':'audio/turn.wav'}]}])
 assert 'RECORDED REPLAY' in html and 'No live calls or actions' in html
 assert '&lt;script&gt;' in html and '<script>' not in html
 assert 'Refund payment has not been verified.' in html and 'audio/turn.wav' in html


def test_partial_run_cannot_be_exported_as_completed_replay(monkeypatch,tmp_path):
 from sandbox import runs
 monkeypatch.setattr(runs,'get',lambda *args:{'state':'PAUSED','origin':'AUDIO_DEMONSTRATION'})
 with pytest.raises(ValueError):export(None,'unused',core=None,verifier=None,destination=tmp_path/'replay')
 assert not (tmp_path/'replay').exists()


def test_partial_phase_preview_cannot_claim_completed_case():
 snapshot={'full_case_completed':False,'verified_checkpoints':2,'summary':{'statements':[],'pending':['Claims verification remains pending.']}}
 html=render(snapshot,[])
 assert '2 of 13 checkpoints verified' in html
 assert '13 of 13 state checkpoints independently verified' not in html
 assert 'unfinished synthetic case' in html and 'Bolna is the assistant' in html


def test_conversation_player_preserves_captured_samples_and_labels_changed_timing(tmp_path):
 import wave
 from sandbox.replay import join_captured_turns
 sources=[]
 for number,samples in enumerate((b'\x01\x00'*160,b'\x02\x00'*320)):
  path=tmp_path/f'{number}.wav';sources.append(path)
  with wave.open(str(path),'wb') as output:
   output.setnchannels(1);output.setsampwidth(2);output.setframerate(16000);output.writeframes(samples)
 combined=tmp_path/'joined.wav'
 assert join_captured_turns(sources,combined)
 with wave.open(str(combined),'rb') as recorded:
  assert recorded.readframes(recorded.getnframes())==b'\x01\x00'*160+b'\0'*9600+b'\x02\x00'*320
 html=render({'summary':{'statements':[],'pending':[]}},[{'purpose':'BILLING','state':'COMPLETED','turns':[],'conversation_audio':'audio/joined.wav'}])
 assert 'Original call timing is not reproduced' in html
