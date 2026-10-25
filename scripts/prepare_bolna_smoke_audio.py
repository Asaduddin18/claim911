"""Create a one-turn synthetic caregiver prompt through the isolated speech broker."""
import io
import json
import os
from pathlib import Path
import wave

from sandbox.provider_control import DockerProvider

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = Path(os.environ.get("CLAIM911_RUNTIME", ROOT.parents[1] / "work" / "claim911-runtime")).resolve()
CONFIG = RUNTIME / "sandbox" / "coordinator.json"
PROVIDER_CONFIG = RUNTIME / "azure" / "provider.json"
OUTPUT = RUNTIME / "sandbox" / "bolna-caregiver-input.wav"
TEXT = "The hospital says final insurance approval is pending, but they have not told us what is missing."


def main():
    config = json.loads(CONFIG.read_text())
    provider = json.loads(PROVIDER_CONFIG.read_text())
    if config.get("environment") != "sandbox" or provider.get("environment") != "sandbox":
        raise SystemExit("Speech synthesis requires the isolated sandbox provider profile.")
    speech = provider.get("speech", {})
    if speech.get("sku") != "F0":
        raise SystemExit("Only the configured free speech tier is enabled for this smoke clip.")
    pcm = DockerProvider(provider).synthesize(TEXT, "en", speaker="caregiver")
    audio = io.BytesIO()
    with wave.open(audio, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        # Let the browser session and Bolna greeting settle before caregiver intake.
        wav.writeframes(b"\0\0" * (16000 * 10))
        wav.writeframes(pcm)
        # Keep Chromium's file-backed fake microphone alive after speech so the
        # WebRTC session can finish the assistant's response before the UI stops it.
        wav.writeframes(b"\0\0" * (16000 * 55))
    OUTPUT.write_bytes(audio.getvalue())
    OUTPUT.chmod(0o600)
    print(json.dumps({"provider": "Azure Speech F0 via isolated broker", "language": "en",
                      "participant": "synthetic caregiver", "clip_seconds": round(len(audio.getvalue()) / 32000, 1)}))


if __name__ == "__main__":
    main()
