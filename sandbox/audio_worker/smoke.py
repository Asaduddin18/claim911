"""Offline image verification. Does not claim a conversation or audio pass."""
import json
from importlib.metadata import version
from pathlib import Path
import sys
sys.path.insert(0, '/app')
from pipecat.evals.scenario import EvalScenarioFile
from pipecat.pipeline.pipeline import Pipeline
from pipecat.frames.frames import InputAudioRawFrame
from pipeline import BrokerSTT, BrokerConversation, BrokerTTS

scenarios=list(EvalScenarioFile.load('/app/eval-smoke.yaml'))
pipeline=Pipeline([BrokerSTT(None),BrokerConversation(None),BrokerTTS(None)])
frame=InputAudioRawFrame(audio=b'\x00\x00'*160,sample_rate=16000,num_channels=1)
print(json.dumps({'pipecat_version':version('pipecat-ai'),'scenario_count':len(scenarios),
 'audio_frame_samples':frame.num_frames,'pipeline_constructed':pipeline is not None,
 'host_shared':Path('/Users').exists(),'provenance':'OFFLINE_IMAGE_SMOKE_ONLY',
 'audio_conversation_executed':False}))
