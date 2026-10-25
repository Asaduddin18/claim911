"""Recover actual audio from a consented stereo provider recording, never TTS.

Offline only. Requires independently captured assistant PCM to identify the
provider's assistant channel, plus observed microphone injection windows.
The result is a diagnostic capture and cannot advance a workflow by itself.
Run with the existing audio environment (numpy and soundfile).
"""
import argparse,base64,hashlib,json
from pathlib import Path
import numpy as np
import soundfile as sf


def main():
 p=argparse.ArgumentParser();p.add_argument('--report',required=True);p.add_argument('--recording',required=True);p.add_argument('--output',required=True);a=p.parse_args()
 path=Path(a.report);report=json.loads(path.read_text());out=Path(a.output)
 if out.exists():raise ValueError('Existing captured evidence must be preserved')
 source=Path(a.recording);audio,sr=sf.read(source,dtype='float64',always_2d=True)
 if sr!=48000 or audio.shape[1]!=2:raise ValueError('This recovery requires the provider stereo 48 kHz recording')
 audio=audio[:len(audio)//3*3].reshape(-1,3,2).mean(axis=1)
 captured=sorted(path.parent.glob(path.name+'.assistant-turn-*.pcm'),key=lambda p:int(p.stem.rsplit('-',1)[1]))
 if len(captured)!=len(report['turns'])+1:raise ValueError('Every observed assistant turn must have its original captured PCM')
 reference=np.frombuffer(captured[0].read_bytes(),dtype='<i2').astype(float)/32768
 scores=[]
 for channel in range(2):
  signal=audio[:16000*16,channel];n=1<<(len(signal)+len(reference)-1).bit_length()
  correlation=np.fft.irfft(np.fft.rfft(signal,n)*np.conj(np.fft.rfft(reference,n)),n)[:len(signal)-len(reference)+1]
  pos=int(np.argmax(correlation));window=signal[pos:pos+len(reference)]
  scores.append(float(np.dot(window,reference)/np.sqrt(np.sum(window**2)*np.sum(reference**2))))
 assistant=int(np.argmax(scores))
 if scores[assistant]<.8 or scores[1-assistant]>.2:raise ValueError('Provider speaker-channel identity cannot be established from captured audio')
 turns=[];windows=[]
 for index,pcm in enumerate(captured):
  turns.append({'speaker':'assistant','pcm_base64':base64.b64encode(pcm.read_bytes()).decode()})
  if index<len(report['turns']):
   turn=report['turns'][index]
   start=max(0,(turn['injection_started_at']-report['connected_at'])/1000-1)
   end=(turn['injection_ended_at']-report['connected_at'])/1000+1
   if start>=end or end*16000>len(audio):raise ValueError('Observed microphone interval is outside the provider recording')
   participant=audio[int(start*16000):int(end*16000),1-assistant]
   if float(np.sqrt(np.mean(participant**2)))<.002:raise ValueError('The participant interval contains no audible speech')
   raw=(np.clip(participant,-1,1)*32767).astype('<i2').tobytes()
   turns.append({'speaker':'participant','pcm_base64':base64.b64encode(raw).decode()});windows.append([start,end])
 capture={'run_id':report['run_id'],'call_id':report['call_id'],'execution_id':report['provider_execution_id'],
  'turns':turns,'checkpoint_eligible':False,'recovery':{'source':'EXISTING_BOLNA_STEREO_RECORDING',
  'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'assistant_channel_correlation':scores,
  'participant_channel':1-assistant,'observed_injection_windows_seconds':windows,'new_audio_synthesized':False}}
 with out.open('x') as f:json.dump(capture,f)
 out.chmod(0o600);print(json.dumps({'captured_turns':len(turns),'new_provider_sessions':0,'new_audio_synthesized':False}))


if __name__=='__main__':main()
