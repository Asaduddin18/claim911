"""Run one synthetic caregiver turn through the Bolna browser SDK and reconcile it."""
import json
import os
import re
import subprocess
import time
from pathlib import Path
from uuid import UUID

import psycopg
from psycopg.rows import dict_row

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = Path(os.environ.get("CLAIM911_RUNTIME", ROOT.parents[1] / "work" / "claim911-runtime")).resolve()
CONFIG_PATH = RUNTIME / "operational" / "coordinator.json"
REPORT_PATH = RUNTIME / "bolna-browser-smoke.json"
AUDIO_PATH = RUNTIME / "sandbox" / "bolna-caregiver-input.wav"
NODE = Path("/path/to/user/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node")
PRODUCT = ROOT / "product"
SCRIPT = PRODUCT / "scripts" / "bolna-browser-smoke.mjs"


def save(report):
    REPORT_PATH.write_text(json.dumps(report, indent=2) + "\n")
    REPORT_PATH.chmod(0o600)


def main():
    if not CONFIG_PATH.is_file() or not AUDIO_PATH.is_file() or not NODE.is_file():
        raise SystemExit("Private runtime, synthetic audio, or Node runtime is unavailable.")
    env = os.environ.copy()
    env.update({
        "CLAIM911_PARTICIPANT_AUDIO": str(AUDIO_PATH),
        "CLAIM911_REPORT_PATH": str(REPORT_PATH),
        "CLAIM911_EXCHANGE_WAIT_MS": "35000",
    })
    run = subprocess.run([str(NODE), str(SCRIPT)], cwd=PRODUCT, env=env, check=False)
    if not REPORT_PATH.is_file():
        raise SystemExit(f"Browser run did not produce a report (exit {run.returncode}).")
    report = json.loads(REPORT_PATH.read_text())
    config = json.loads(CONFIG_PATH.read_text())
    call_id = UUID(report["call_id"]) if report.get("call_id") else None
    case_id = UUID(report["case_id"]) if report.get("case_id") else None
    with psycopg.connect(config["dsn"]) as conn:
        if case_id:
            conn.execute(
                "UPDATE coordinator.incidents SET is_test=true, title='[Synthetic Bolna browser smoke] '||title WHERE id=%s",
                (case_id,),
            )
    if call_id:
        from coordinator.worker import poll_once, process_webhook_once, stop_once

        # The caregiver's End action queues a scoped stop. Reconcile only this exact
        # synthetic execution, never the rest of the operational call queue.
        stop_once(config, call_id=call_id)
        for attempt in range(3):
            poll_once(config, call_id=call_id)
            with psycopg.connect(config["dsn"], row_factory=dict_row) as conn:
                call = conn.execute(
                    "SELECT execution_id,state,transcript,recording_url FROM coordinator.calls WHERE id=%s",
                    (call_id,),
                ).fetchone()
            if not call:
                break
            if call["execution_id"]:
                for _ in range(3):
                    if not process_webhook_once(config, execution_id=call["execution_id"]):
                        break
                with psycopg.connect(config["dsn"], row_factory=dict_row) as conn:
                    call = conn.execute(
                        "SELECT execution_id,state,transcript,recording_url FROM coordinator.calls WHERE id=%s",
                        (call_id,),
                    ).fetchone()
            if call and (call["state"] in {"COMPLETED", "FAILED", "CANCELLED", "BUSY", "NO_ANSWER"}):
                break
            if attempt < 2:
                time.sleep(6)
        transcript = call["transcript"] if call else []
        text = " ".join(item.get("text", "") for item in transcript if isinstance(item, dict))
        user_at = text.casefold().rfind("user:")
        reply = text[user_at + 5:] if user_at >= 0 else ""
        next_assistant = re.search(r"\bassistant:\s*(.+?)(?=\nuser:|$)", reply, re.I | re.S)
        reply_text = next_assistant.group(1).strip() if next_assistant else ""
        language_detour = bool(re.search(r"preferred language|what language|language for (?:this|the) conversation", reply_text, re.I))
        participant_turns = len(re.findall(r"\buser\s*:", text, re.I))
        report["provider_state"] = call["state"] if call else None
        report["reconciled_transcript"] = transcript
        report["recording_available"] = bool(call and call["recording_url"])
        report["participant_audio_received"] = bool(re.search(r"\buser\s*:\s*\S+", text, re.I))
        report["complete_participant_turn"] = (
            report["participant_audio_received"]
            and all(phrase in text.casefold() for phrase in ("hospital", "insurance", "pending", "missing"))
        )
        report["dialogue_checks"] = {
            "participant_turn_count": participant_turns,
            "single_participant_turn": participant_turns == 1,
            "assistant_replied_after_caregiver": bool(reply_text),
            "reply_addresses_pending_approval": bool(re.search(r"approval|pending", reply_text, re.I)),
            "reply_asks_about_missing_evidence": bool(re.search(r"missing|document|information", reply_text, re.I)),
            "language_detour": language_detour,
            "follow_up_is_relevant": bool(reply_text and not language_detour
                and re.search(r"approval|pending", reply_text, re.I)
                and re.search(r"missing|document|information", reply_text, re.I)),
        }
    save(report)
    print(json.dumps({
        "connected": report.get("connected"),
        "ended": report.get("ended"),
        "provider_state": report.get("provider_state"),
        "participant_audio_received": report.get("participant_audio_received"),
        "complete_participant_turn": report.get("complete_participant_turn"),
        "dialogue_checks": report.get("dialogue_checks"),
        "recording_available": report.get("recording_available"),
        "phone_dispatch": report.get("phone_dispatch"),
    }))
    if not (run.returncode == 0 and report.get("connected") and report.get("ended")
            and report.get("complete_participant_turn") and report.get("dialogue_checks", {}).get("single_participant_turn")
            and report.get("dialogue_checks", {}).get("follow_up_is_relevant")):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
