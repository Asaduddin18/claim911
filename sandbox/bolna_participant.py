"""Role-bounded participant turns for the Bolna browser sandbox harness.

Bolna remains the assistant. This controller transcribes its latest spoken turn,
asks one synthetic participant role to answer from that role's own record, and
returns audio in a role-specific licensed voice. It never verifies or writes a
Claim911 workflow outcome.
"""
import json
from sandbox.participant_dialogue import ParticipantDialogue
from sandbox.actors import ROLES


MAX_PCM_BYTES = 3_200_000  # 100 seconds of 16 kHz, mono, signed 16-bit PCM.
MAX_ASSISTANT_PCM_BYTES = 1_280_000
MAX_TURNS = 20
MAX_TURN_TEXT = 2_000


def natural_response_messages(role,record,history):
    if (role not in ROLES or not isinstance(record,dict) or record.get('synthetic') is not True
        or record.get('role')!=role):
        raise ValueError('Known synthetic role record required')
    if not isinstance(history,list) or len(history)>MAX_TURNS*2:
        raise ValueError('Participant conversation history is outside its limit')
    participant_history=[]
    for turn in history:
        if (not isinstance(turn,dict) or set(turn)!={'role','content'}
            or turn['role'] not in {'assistant','user'} or not isinstance(turn['content'],str)
            or not 0<len(turn['content'])<=MAX_TURN_TEXT):
            raise ValueError('Conversation history contains an invalid turn')
        participant_history.append({'role':'user' if turn['role']=='assistant' else 'assistant',
                                    'content':turn['content']})
    instruction=(
        'You are a person taking part in a synthetic Claim911 discharge rehearsal. '
        'Stay in the assigned role and use only the role record below. '
        'Reply directly to the latest Claim911 utterance in one or two natural, concise sentences. '
        'If it asks several things, answer the parts supported by your record and ask one brief clarification for the rest. '
        'Never invent identifiers, institution actions, signatures, decisions, receipt, clearance or payments. '
        'Do not claim to change a case or perform a protected action. If you do not know, say so plainly. '
        'If someone asks whether this is a real case, say it is a synthetic demonstration. '
        'Use ordinary spoken English, without field names, bullet points or robotic readbacks.\n'
        +json.dumps({'participant_role':role,'synthetic_record':record},ensure_ascii=False))
    return [{'role':'developer','content':instruction},*participant_history]


class BolnaParticipant:
    def __init__(self, *, role, record, speech, actor, language='en'):
        if role not in ROLES or not isinstance(record, dict) or record.get('synthetic') is not True:
            raise ValueError('Known synthetic role record required')
        if language != 'en':
            raise ValueError('The Bolna participant harness currently supports English only')
        if actor is None or speech is None:
            raise ValueError('A role actor and bounded speech adapter are required')
        self.role = role
        self.record = record
        self.speech = speech
        self.actor = actor
        self.language = language
        self.history = []
        self.turns = 0

    def answer_audio(self, assistant_pcm):
        if not isinstance(assistant_pcm, bytes) or not 0 < len(assistant_pcm) <= MAX_ASSISTANT_PCM_BYTES or len(assistant_pcm) % 2:
            raise ValueError('Assistant audio must be bounded 16 kHz mono PCM')
        if self.turns >= MAX_TURNS:
            raise ValueError('Participant conversation turn limit reached')
        recognized = self.speech.transcribe(assistant_pcm, self.language)
        question = recognized.get('text') if isinstance(recognized, dict) else None
        if not isinstance(question, str) or not question.strip() or len(question) > MAX_TURN_TEXT:
            raise ValueError('Assistant speech did not produce a bounded question')
        prepared=self._prepare_text(question.strip())
        answer=prepared.answer
        pcm = self.speech.synthesize(answer, self.language, speaker=self.role)
        if not isinstance(pcm, bytes) or not 0 < len(pcm) <= MAX_PCM_BYTES or len(pcm) % 2:
            raise ValueError('Synthetic participant audio is outside the bounded PCM contract')
        self._accept_text(prepared)
        return {
            'assistant_text': question.strip(),
            'participant_text': answer,
            'participant_role': self.role,
            'participant_audio_pcm': pcm,
            'turn': self.turns,
            'workflow_write': False,
            'checkpoint_eligible': False,
        }

    def _prepare_text(self,question):
        if getattr(self,'_dialogue',None) is None:
            def reply(messages):
                # This legacy actor adapter uses the assistant/caregiver view;
                # the shared text core always uses the participant perspective.
                return self.actor.reply([{'role':'assistant' if m['role']=='user' else 'user',
                                          'content':m['content']} for m in messages])
            self._dialogue=ParticipantDialogue(reply,history=[
                {'role':'user' if m['role']=='assistant' else 'assistant','content':m['content']}
                for m in self.history],max_turns=MAX_TURNS)
        return self._dialogue.prepare(self._dialogue.completed+1,question)

    def _accept_text(self,prepared):
        canonical=self._dialogue.accept_output(prepared)
        self.history=[{'role':'assistant' if m['role']=='user' else 'user','content':m['content']} for m in canonical]
        self.turns=self._dialogue.completed

    def answer_text(self,question):
        """Exercise the same participant with no recognition or speech adapters.

        This is text-only test evidence, never a Bolna or audio pass.
        """
        prepared=self._prepare_text(question)
        self._accept_text(prepared)
        return {'assistant_text':prepared.question,'participant_text':prepared.answer,
                'participant_role':self.role,'turn':self.turns,
                'workflow_write':False,'checkpoint_eligible':False,'audio_tested':False}
