"""Text-only participant boundary shared by local tests and the voice adapter.

No recognition, speech synthesis, evaluator, provider configuration or case
verification belongs here. The injected participant retains its role-scoped
record and institution operations. A turn ID binds generation to one question.
"""
from copy import deepcopy
from dataclasses import dataclass


@dataclass(frozen=True)
class PreparedReply:
    turn_id: int
    question: str
    answer: str


class ParticipantDialogue:
    def __init__(self,reply,*,history=None,max_turns=20):
        if not callable(reply) or type(max_turns) is not int or not 1<=max_turns<=20:
            raise ValueError('A bounded participant reply adapter is required')
        self._reply=reply
        self._history=deepcopy(history or [])
        if (len(self._history)%2 or len(self._history)>max_turns*2
            or any(not isinstance(m,dict) or set(m)!={'role','content'}
                   or m['role']!=('user' if n%2==0 else 'assistant')
                   or not isinstance(m['content'],str) or not 0<len(m['content'])<=2000
                   for n,m in enumerate(self._history))):
            raise ValueError('Participant-perspective paired history required')
        self.max_turns=max_turns
        self.prepared=None
        self.state='READY'
        self.completed=len(self._history)//2
        self.last_question=None;self.last_answer=None;self.failure_type=None

    @property
    def history(self):return deepcopy(self._history)

    def prepare(self,turn_id,question):
        if type(turn_id) is not int or turn_id<1 or not isinstance(question,str) or not 0<len(question.strip())<=2000:
            raise ValueError('A bounded observed question and turn ID are required')
        question=question.strip()
        if self.state=='FAILED':raise RuntimeError('Uncertain participant generation requires reconciliation')
        if self.prepared and turn_id==self.prepared.turn_id:
            if question!=self.prepared.question:raise ValueError('Turn ID cannot be reused for a changed question')
            return self.prepared
        if self.state!='READY':raise RuntimeError('Pending or uncertain participant turn requires reconciliation')
        if self.completed>=self.max_turns or turn_id!=self.completed+1:
            raise ValueError('Participant turns must be bounded and sequential')
        # A model/tool timeout might follow a synthetic institution write.
        # Never retry generation silently, even if no text was returned.
        self.last_question=question;self.last_answer=None;self.failure_type=None
        self.state='GENERATING'
        try:
            answer=self._reply(self.history+[{'role':'user','content':question}])
            if not isinstance(answer,str) or not 0<len(answer.strip())<=2000:
                raise ValueError('Bounded participant response required')
            self.last_answer=answer.strip()
            from sandbox.dialogue_quality import known_topic_mismatches
            if known_topic_mismatches([{'speaker':'assistant','text':question},
                                       {'speaker':'participant','text':answer}]):
                raise ValueError('Participant response answers a different question')
            self.prepared=PreparedReply(turn_id,question,answer.strip())
            self.state='REPLY_READY'
            return self.prepared
        except Exception as exc:
            self.failure_type=type(exc).__name__
            self.state='FAILED'
            raise

    def accept_output(self,prepared):
        """Record output preparation, never proof of audio delivery or case state."""
        if prepared is not self.prepared:raise ValueError('Only this session current reply may be accepted')
        if self.state=='READY':return self.history
        if self.state!='REPLY_READY':raise RuntimeError('Participant reply is not ready')
        self._history.extend([{'role':'user','content':prepared.question},{'role':'assistant','content':prepared.answer}])
        self.completed+=1
        self.state='READY'
        return self.history

    def diagnostic(self):
        """Bounded synthetic dialogue only, no role record, credentials or tools."""
        return {'scope':'PARTICIPANT_TEXT_DIAGNOSTIC','state':self.state,
                'completed_outputs':self.completed,'question':self.last_question,
                'generated_answer':self.last_answer,'failure_type':self.failure_type,
                'audio_delivery_verified':False,'workflow_state_verified':False}
