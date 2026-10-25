"""Trusted one-turn bridge for synthetic role actors in a Bolna browser call.

Input is bounded JSON on stdin. Secrets stay in the private provider profile and
the existing one-operation provider container. The audio package worker never
receives role facts, provider keys, or a network-capable handle.
"""
import argparse
import base64
import json
import sys
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sandbox.bolna_participant import BolnaParticipant,MAX_TURN_TEXT,natural_response_messages
from sandbox.provider_control import DockerProvider
from sandbox.scripted_desks import ScriptedDesk
from sandbox.participant_model import DeskParticipant,ReadOnlyRoleRecord
from sandbox.participant_dialogue import ParticipantDialogue


def budgeted_provider_request(provider,sandbox,run_id,operation,body):
    import psycopg
    from psycopg.rows import dict_row
    from sandbox.spend import reserve,settle
    request_id=str(uuid4())
    with psycopg.connect(sandbox['dsn'],row_factory=dict_row) as conn:
        reservation=reserve(conn,request_id=request_id,run_id=run_id,phase='development',
                            operation=operation,maximum_micro=100_000)
    if not reservation['new_reservation']:
        raise RuntimeError('Participant provider request requires reconciliation before retry')
    try:
        return provider.request(operation,body,reservation_id=request_id if operation=='reply' else None)
    finally:
        # Keep the upper-bound hold until provider usage has been reconciled.
        with psycopg.connect(sandbox['dsn'],row_factory=dict_row) as conn:
            settle(conn,request_id)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--provider-config', required=True)
    parser.add_argument('--synthesize-utterance', action='store_true')
    parser.add_argument('--respond-to-question', action='store_true')
    parser.add_argument('--transcribe-only', action='store_true')
    parser.add_argument('--natural-response', action='store_true')
    parser.add_argument('--sandbox-config')
    parser.add_argument('--run-id')
    args = parser.parse_args()
    if sum((args.synthesize_utterance,args.respond_to_question,args.transcribe_only,args.natural_response))>1:
        raise ValueError('Choose one synthetic participant operation')
    if args.natural_response and (not args.sandbox_config or not args.run_id):
        raise ValueError('Budgeted natural participant response requires its sandbox run')
    raw = sys.stdin.readline(950_001)
    if len(raw) > 950_000 or not raw.endswith('\n'):
        raise ValueError('Participant request exceeds its input bound')
    request = json.loads(raw)
    expected=({'role','record','text'} if args.synthesize_utterance else
              {'role','record','question'} if args.respond_to_question else
              {'role','record','history','pcm_base64'})
    if set(request) != expected:
        raise ValueError('Participant request fields do not match the bounded contract')
    role = request['role']
    if role not in {'caregiver', 'hospital_insurance', 'billing', 'medical_records', 'implant_store', 'tpa', 'insurer'}:
        raise ValueError('Unknown synthetic participant role')
    record = request['record']
    if not isinstance(record, dict) or record.get('synthetic') is not True or len(json.dumps(record).encode()) > 8_000:
        raise ValueError('Role-owned synthetic record is outside its size limit')
    provider = DockerProvider(json.loads(Path(args.provider_config).read_text()))
    if args.synthesize_utterance:
        text=request['text']
        if not isinstance(text,str) or not 0<len(text)<=2_000:
            raise ValueError('Synthetic participant utterance is outside its size limit')
        audio=provider.synthesize(text,'en',speaker=role)
        print(json.dumps({'participant_role':role,'participant_text':text,
                          'participant_audio_pcm_base64':base64.b64encode(audio).decode(),
                          'workflow_write':False,'checkpoint_eligible':False}))
        return
    if args.respond_to_question:
        question=request['question']
        if not isinstance(question,str) or not 0<len(question)<=2_000:
            raise ValueError('Expected synthetic question is outside its size limit')
        answer=ScriptedDesk(role,record).reply([{'role':'assistant','content':question}])
        audio=provider.synthesize(answer,'en',speaker=role)
        print(json.dumps({'assistant_text':question,'participant_text':answer,
                          'participant_role':role,'participant_audio_pcm_base64':base64.b64encode(audio).decode(),
                          'workflow_write':False,'checkpoint_eligible':False}))
        return
    if args.transcribe_only:
        history=request['history'];audio=base64.b64decode(request['pcm_base64'],validate=True)
        if not isinstance(history,list) or len(history)>38:
            raise ValueError('Participant conversation history is outside its limit')
        if not 0<len(audio)<=640_000 or len(audio)%2:
            raise ValueError('Assistant audio must be bounded 16 kHz mono PCM')
        recognized=provider.transcribe(audio,'en')
        question=recognized.get('text') if isinstance(recognized,dict) else None
        if not isinstance(question,str) or not question.strip() or len(question)>2_000:
            raise ValueError('Assistant speech did not produce a bounded question')
        print(json.dumps({'assistant_text':question.strip(),'participant_role':role,
                          'workflow_write':False,'checkpoint_eligible':False}))
        return
    history = request['history']
    if not isinstance(history, list) or len(history) > 38:
        raise ValueError('Participant conversation history is outside its limit')
    for turn in history:
        if not isinstance(turn, dict) or set(turn) != {'role', 'content'} or turn['role'] not in {'assistant', 'user'}:
            raise ValueError('Conversation history contains a non-dialogue field')
        if not isinstance(turn['content'], str) or not 0 < len(turn['content']) <= 2_000:
            raise ValueError('Conversation history contains an unbounded turn')
    audio = base64.b64decode(request['pcm_base64'], validate=True)
    if args.natural_response:
        from psycopg.conninfo import conninfo_to_dict
        with Path(args.sandbox_config).open() as stream:sandbox=json.load(stream)
        database=conninfo_to_dict(sandbox.get('dsn',''))
        if (sandbox.get('environment')!='sandbox' or sandbox.get('live_calls_enabled') or sandbox.get('bolna_api_key')
            or not database.get('dbname','').lower().startswith('claim911_sandbox')
            or database.get('host','') not in {'localhost','127.0.0.1','::1'}):
            raise ValueError('Synthetic key-free sandbox profile required')
        audio=base64.b64decode(request['pcm_base64'],validate=True)
        if not 0<len(audio)<=640_000 or len(audio)%2:
            raise ValueError('Assistant audio must be bounded 16 kHz mono PCM')
        recognized=budgeted_provider_request(provider,sandbox,args.run_id,'transcribe',
                                              {'pcm_base64':base64.b64encode(audio).decode(),'language':'en'})
        question=recognized.get('text') if isinstance(recognized,dict) else None
        if not isinstance(question,str) or not question.strip() or len(question)>MAX_TURN_TEXT:
            raise ValueError('Assistant speech did not produce a bounded question')
        messages=natural_response_messages(role,record,history+[{'role':'assistant','content':question.strip()}])
        def invoke(ms,tools):
            if tools:raise PermissionError('Standalone participant is read-only')
            return budgeted_provider_request(provider,sandbox,args.run_id,'reply',{'messages':ms,'tools':[]})
        actor=DeskParticipant(ReadOnlyRoleRecord(role,record),invoke,authorized=lambda:True,brief='Synthetic conversation partner.')
        dialogue=ParticipantDialogue(actor.reply,history=messages[1:-1])
        answer=dialogue.prepare(len(messages[1:-1])//2+1,question.strip()).answer
        synthesized=budgeted_provider_request(provider,sandbox,args.run_id,'synthesize',
                                               {'text':answer,'language':'en','speaker':role})
        participant_audio=base64.b64decode(synthesized['pcm_base64'],validate=True)
        print(json.dumps({'assistant_text':question.strip(),'participant_text':answer,
                          'participant_role':role,'participant_audio_pcm_base64':base64.b64encode(participant_audio).decode(),
                          'workflow_write':False,'checkpoint_eligible':False}))
        return
    actor=ScriptedDesk(role,record)
    participant = BolnaParticipant(role=role, record=record, speech=provider, actor=actor)
    participant.history = history
    result = participant.answer_audio(audio)
    print(json.dumps({
        'assistant_text': result['assistant_text'],
        'participant_text': result['participant_text'],
        'participant_role': result['participant_role'],
        'participant_audio_pcm_base64': base64.b64encode(result['participant_audio_pcm']).decode(),
        'turn': result['turn'],
        'workflow_write': False,
        'checkpoint_eligible': False,
    }))


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        safe_errors={
            'Assistant audio must be bounded 16 kHz mono PCM':'ASSISTANT_AUDIO_FORMAT',
            'Assistant speech did not produce a bounded question':'ASSISTANT_AUDIO_UNCLEAR',
            'Participant conversation turn limit reached':'TURN_LIMIT',
            'Synthetic participant did not produce a bounded answer':'PARTICIPANT_REPLY_INVALID',
            'Synthetic participant audio is outside the bounded PCM contract':'PARTICIPANT_AUDIO_FORMAT',
            'Known English synthetic participant required':'ROLE_VOICE_UNAVAILABLE',
            'Restricted sandbox egress proxy is required':'EGRESS_PROXY_REQUIRED',
        }
        print(json.dumps({'error': 'Synthetic participant turn failed', 'category': type(exc).__name__,
                          'safe_code': safe_errors.get(str(exc), type(exc).__name__)}), file=sys.stderr)
        raise SystemExit(1)
