"""Offline release evidence screening. Never substitutes for live state or human review."""
from datetime import datetime
from sandbox.actors import scenario_manifest
from sandbox.executor import PHASES


def screen(report):
    problems=[]
    keys=scenario_manifest()['checkpoints']
    if report.get('execution_scope','FULL_CASE')!='FULL_CASE':problems.append('COMPONENT_NOT_FULL_CASE')
    if (report.get('state')!='COMPLETED' or report.get('full_case_completed') is not True
        or report.get('verified_checkpoints')!=len(keys) or report.get('required_checkpoints')!=len(keys)
        or report.get('failure') is not None):problems.append('FULL_CASE_NOT_COMPLETED')
    config=report.get('provider_configuration') or {}
    fingerprint=config.get('assistant_config_sha256','')
    if (report.get('assistant_transport')!='bolna-browser' or config.get('transport')!='BOLNA_WEBRTC'
        or len(fingerprint)!=64 or any(c not in '0123456789abcdef' for c in fingerprint)):
        problems.append('REVIEWED_BOLNA_CONFIGURATION_REQUIRED')
    audit=report.get('independent_evaluation') or {}
    checks=audit.get('checks',[])
    if (audit.get('required_audio_provenance')!='BOLNA_WEBRTC' or audit.get('fixture_audio_allowed') is not False
        or audit.get('passed') is not True or audit.get('incident_id')!=report.get('incident_id')
        or len(checks)!=len(keys) or [c.get('checkpoint') for c in checks]!=keys
        or any(c.get('passed') is not True or not c.get('evidence_references') for c in checks)):
        problems.append('INDEPENDENT_FULL_CASE_EVIDENCE_REQUIRED')
    expected={purpose for purpose,_ in PHASES.values() if purpose}
    calls=report.get('conversations',[])
    records=[c for c in calls if c.get('purpose')=='RECORDS_DOCUMENT']
    if ('unsigned_summary' not in report.get('scenario_faults',[])
        or not any(c.get('followup') is False for c in records)
        or not any(c.get('followup') is True for c in records)):
        problems.append('UNSIGNED_SUMMARY_RECOVERY_REQUIRED')
    if not expected.issubset({c.get('purpose') for c in calls}):problems.append('VOICE_JOURNEYS_MISSING')
    for call in calls:
        quality=call.get('semantic_dialogue_evaluation') or {}
        if (call.get('archived') is not True or call.get('provenance')!='BOLNA_WEBRTC'
            or call.get('assistant_config_sha256')!=fingerprint
            or quality.get('conversation_quality_passed') is not True
            or quality.get('critical_failures')!=[]):
            problems.append('VOICE_ARCHIVE_OR_QUALITY_REQUIRED');break
    return {'run_id':report.get('run_id'),'eligible':not problems,'reasons':problems}


def consecutive(reports):
    # Repeated reports of one resumed run are one case, not fresh passes.
    unique={}
    for report in reports:
        key=report.get('run_id')
        if not key:raise ValueError('Run identity required')
        previous=unique.get(key)
        if previous is None or report['finished_at']>previous['finished_at']:unique[key]=report
    ordered=sorted(unique.values(),key=lambda r:datetime.fromisoformat(r['started_at']))
    full=[r for r in ordered if r.get('execution_scope','FULL_CASE')=='FULL_CASE'
          and r.get('assistant_transport')=='bolna-browser']
    latest=full[-3:];checks=[screen(r) for r in latest]
    configs={r.get('provider_configuration',{}).get('assistant_config_sha256') for r in latest}
    fresh=len({r.get('incident_id') for r in latest})==3
    return {'three_consecutive_full_cases_passed':len(latest)==3 and fresh and len(configs)==1
            and all(c['eligible'] for c in checks),'latest_full_cases':checks,
            'human_audio_review':'REQUIRED_SEPARATELY','hackathon_ready':False,
            'scope':'EXPORTED_REPORT_SCREENING_NOT_LIVE_STATE_REVERIFICATION'}
