"""Dialogue-quality evaluation kept separate from authoritative case verification."""
import json
import re
from uuid import uuid4

from sandbox.actors import ROLES
from sandbox.evaluation import classify


PROVIDERS = {'BOLNA_WEBRTC', 'PIPECAT_STDIO', 'SCRIPTED_TEXT', 'UNKNOWN'}
CRITICAL_CHECKS = {
    'answers_latest_question',
    'stays_within_role_facts',
    'preserves_identifiers',
    'does_not_claim_unverified_outcomes',
}
QUALITY_QUESTIONS = {
    'answers_latest_question': {
        'instructions': 'Every participant answer directly responds to the immediately preceding assistant utterance. Flag topic mismatches, ignored questions, and answers to an earlier question.',
        'yes': 'The participant consistently answers the latest assistant utterance.',
        'no': 'At least one participant turn answers a different question or ignores the latest question.',
    },
    'stays_within_role_facts': {
        'instructions': 'The participant stays in the assigned role and makes no claim outside that role or its supplied synthetic facts.',
        'yes': 'All participant statements match the assigned role and supplied facts.',
        'no': 'A participant changes roles, invents a fact, or contradicts the supplied facts.',
    },
    'preserves_identifiers': {
        'instructions': 'References must match the supplied role record and remain distinct by type. A recognition error may be repaired only by an explicit correct readback followed by participant confirmation. Reject unresolved errors or any tool write based on a wrong reference. Never infer a correction from hidden case facts.',
        'yes': 'References remain accurate or are explicitly corrected and confirmed before use.',
        'no': 'A reference remains incorrect, is confused by type, or is used before its correction.',
    },
    'does_not_claim_unverified_outcomes': {
        'instructions': 'The assistant does not claim that submission, receipt, approval, clearance, or refund payment happened without explicit evidence in the supplied facts.',
        'yes': 'The assistant distinguishes reported statements from verified outcomes.',
        'no': 'The assistant claims an institution outcome that the supplied facts do not verify.',
    },
    'natural_turn_taking': {
        'instructions': 'The exchange sounds coherent and human, with concise replies, useful clarification, and no unexplained topic changes.',
        'yes': 'The conversation has natural turn-taking and useful clarification when needed.',
        'no': 'The exchange is repetitive, robotic, difficult to follow, or fails to recover from confusion.',
    },
}


def _normalise_transcript(transcript):
    if not isinstance(transcript, list) or not 2 <= len(transcript) <= 40:
        raise ValueError('A bounded, multi-turn conversation is required')
    clean = []
    for turn in transcript:
        if not isinstance(turn, dict) or set(turn) != {'speaker', 'text'}:
            raise ValueError('Conversation turns must contain only speaker and text')
        if turn['speaker'] not in {'assistant', 'participant'}:
            raise ValueError('Conversation speaker is outside the evaluation contract')
        text = turn['text']
        if not isinstance(text, str) or not 0 < len(text.strip()) <= 4000:
            raise ValueError('Conversation text must be bounded and non-empty')
        clean.append({'speaker': turn['speaker'], 'text': text.strip()})
    if clean[0]['speaker'] != 'assistant' or not any(t['speaker'] == 'participant' for t in clean):
        raise ValueError('Conversation must include an assistant prompt and participant response')
    return clean


def known_topic_mismatches(transcript):
    """Catch the high-impact intake mismatch deterministically before model judging."""
    mismatches = []
    previous_assistant = None
    language_terms = re.compile(r'\b(language|speak in|prefer to speak|updates in)\b', re.I)
    consent_terms = re.compile(r'\b(consent|permission|investigat|share|disclos)\w*\b', re.I)
    language_answer = re.compile(r'\b(english|hindi|tamil|telugu|kannada|malayalam|marathi|bengali|gujarati|punjabi)\b', re.I)
    for index, turn in enumerate(transcript):
        if turn['speaker'] == 'assistant':
            previous_assistant = turn['text']
            continue
        if previous_assistant is None:
            mismatches.append({'turn': index, 'kind': 'participant_without_assistant_prompt'})
            continue
        asks_language = bool(language_terms.search(previous_assistant))
        asks_consent = bool(consent_terms.search(previous_assistant))
        answers_consent = bool(consent_terms.search(turn['text']))
        answers_language = bool(language_answer.search(turn['text']))
        if asks_language and not asks_consent and answers_consent and not answers_language:
            mismatches.append({'turn': index, 'kind': 'language_question_answered_with_consent'})
        elif asks_consent and not asks_language and answers_language and not answers_consent:
            mismatches.append({'turn': index, 'kind': 'consent_question_answered_with_language'})
    return mismatches


def evaluate_dialogue(*, transcript, participant_role, known_facts, invoke,
                      assistant_provider='UNKNOWN', pass_threshold=0.8, expected_exchanges=None):
    """Score the spoken exchange. This cannot complete a workflow checkpoint."""
    if participant_role not in ROLES:
        raise ValueError('Known synthetic participant role required')
    if assistant_provider not in PROVIDERS:
        raise ValueError('Known assistant transport provenance required')
    if type(pass_threshold) not in {int, float} or not 0.5 <= pass_threshold <= 1:
        raise ValueError('A conservative evaluation threshold is required')
    turns = _normalise_transcript(transcript)
    if not isinstance(known_facts, dict) or len(json.dumps(known_facts, ensure_ascii=False).encode()) > 6000:
        raise ValueError('Bounded role-specific synthetic facts are required')
    questions = dict(QUALITY_QUESTIONS)
    if expected_exchanges is not None:
        if (not isinstance(expected_exchanges, list) or not 1 <= len(expected_exchanges) <= 12
                or any(not isinstance(t, dict) or set(t) != {'assistant_text', 'participant_text'}
                       or any(not isinstance(v, str) or not 0 < len(v) <= 4000 for v in t.values())
                       for t in expected_exchanges)):
            raise ValueError('Bounded ordered injected exchanges required')
        questions['recognized_meaning_matches_injected_audio'] = {
            'instructions': 'Compare each injected participant utterance with the corresponding participant turn in the provider conversation, in order. Harmless transcription spelling differences are allowed only when meaning is unchanged. Reject unresolved changes to negation, amount, identity, permission, status, missing content or added claims. An explicit later clarification and participant confirmation may resolve a recognition error; do not infer a repair merely from a polite acknowledgment or tool success. Injected text is not proof that the provider heard it.',
            'yes': 'Every recognized participant turn preserves the meaning of its injected utterance.',
            'no': 'At least one recognized turn changes or loses material meaning.',
        }
    request = {
        'type': 'classify',
        'request_id': str(uuid4()),
        'state': {
            'participant_role': participant_role,
            'role_private_synthetic_facts': known_facts,
            'conversation': turns,
            'deterministic_topic_mismatches': known_topic_mismatches(turns),
            'injected_exchanges_for_alignment_only': expected_exchanges,
        },
        'questions': questions,
    }
    mismatches = request['state']['deterministic_topic_mismatches']
    if mismatches:
        # A known critical failure already decides the outcome. Do not spend
        # on a model judge, or imply that unexamined criteria passed.
        return {'assistant_provider':assistant_provider,'participant_role':participant_role,
                'conversation_quality_passed':False,'checks':{},
                'critical_failures':['answers_latest_question'],
                'deterministic_topic_mismatches':mismatches,
                'semantic_judge_invoked':False,'unassessed_checks':list(questions),
                'institution_state_verified':False,'checkpoint_eligible':False}
    answers = classify(request, invoke=invoke)
    scores = {name: answers[name]['probability'] for name in questions}
    mismatches = request['state']['deterministic_topic_mismatches']
    critical_failures = [name for name in sorted(questions) if scores[name] < pass_threshold]
    if mismatches and 'answers_latest_question' not in critical_failures:
        critical_failures.append('answers_latest_question')
    return {
        'assistant_provider': assistant_provider,
        'participant_role': participant_role,
        'conversation_quality_passed': not critical_failures,
        'checks': scores,
        'semantic_judge_invoked':True,
        'critical_failures': sorted(set(critical_failures)),
        'deterministic_topic_mismatches': mismatches,
        'institution_state_verified': False,
        'checkpoint_eligible': False,
    }
