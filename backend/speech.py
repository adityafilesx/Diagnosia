"""Speech: Sarvam AI first when it is switched on, then Groq, Edge and the browser, as before.

Groq's Whisper transcribes English and Hindi, and Orpheus reads English aloud. Groq has no Hindi
voice, so without Sarvam, Hindi is read by Edge (demo mode only) or the browser's own voice.
Whisper can invent words from silence, so segments it marks as probably not speech are dropped
rather than written into a clinical transcript.

Sarvam (docs/integrations/SARVAM.md) is used only when addons.sarvam_ready says so: its switch, a
key, the sarvam_terms sign-off, and made-up patients only. Its speech to text runs Saaras v4 in its
mixed-language mode, never its translate mode: the text the patient confirms is the record, and
Mayura translates that text for the doctor. Any Sarvam failure falls back to today's providers.
"""
import asyncio
import base64
import re
import sqlite3
import time
from typing import List, Literal, Optional, Tuple
from urllib.parse import urlsplit

import httpx

from backend import settings_store
from backend.config import neural_tts_allowed, settings
from backend.integrations import execution

TTS_MODEL = "canopylabs/orpheus-v1-english"
TTS_VOICE = "troy"
MAX_SPEECH_CHARS = 2500
TIMEOUT_SECONDS = 60
MAX_ATTEMPTS = 2
RETRY_PAUSE_SECONDS = 0.5
RETRY_STATUSES = (429, 500, 502, 503, 504)
NO_SPEECH_LIMIT = 0.6
# The extension tells Whisper the format, and browsers differ: Safari records mp4.
EXTENSIONS = {"audio/webm": "webm", "audio/ogg": "ogg", "audio/mp4": "mp4", "audio/mpeg": "mp3", "audio/wav": "wav"}
LANGUAGE_CODES = {"en-IN": "en", "hi-IN": "hi"}

Language = Literal["en-IN", "hi-IN"]
VOICED_LANGUAGES = ("en-IN",)  # anything else is read by the browser
NEURAL_VOICES = {"en-IN": "en-IN-NeerjaNeural", "hi-IN": "hi-IN-SwaraNeural"}
NEURAL_TIMEOUT_SECONDS = 8
SARVAM_TIMEOUT_SECONDS = 20  # a patient is waiting on each of these
# A patient who may be unwell is listening: a little slower than Bulbul's 1.0, and a lower
# temperature (default 0.6) for a steadier, calmer delivery rather than an expressive one.
SARVAM_PACE = 0.9
SARVAM_TEMPERATURE = 0.4
MAYURA_MAX_CHARS = 1000  # Mayura's limit per request; longer answers go in pieces
DEVANAGARI = re.compile(r"[\u0900-\u097F]")
SENTENCE_END = re.compile(r"(?<=[.!?।|])\s+")


class SpeechUnavailable(Exception):
    """Speech couldn't be reached or isn't set up."""


class SpeechRejected(Exception):
    """The service refused this audio or text, for example because it's too long."""


def _key() -> str:
    key = settings_store.api_key()
    if not key:
        raise SpeechUnavailable("No API key")
    return key


def _post(path: str, **options) -> httpx.Response:
    """One retry for a blip. Anything else is reported, and no text is ever invented."""
    url = f"{settings.ai_base_url}{path}"
    if (urlsplit(url).hostname or "").lower() not in settings.allowed_ai_hosts:
        raise SpeechUnavailable("Speech host not on the allowed list")  # patient audio goes only to named providers
    headers = {"Authorization": f"Bearer {_key()}"}
    failure: Optional[SpeechUnavailable] = None
    for attempt in range(MAX_ATTEMPTS):
        if attempt:
            time.sleep(RETRY_PAUSE_SECONDS)
        try:
            response = httpx.post(url, headers=headers, timeout=TIMEOUT_SECONDS, **options)
        except httpx.HTTPError as error:
            failure = SpeechUnavailable(type(error).__name__)
            continue
        if response.status_code in (400, 413, 422):
            raise SpeechRejected(f"Speech service returned {response.status_code}")
        if response.status_code in RETRY_STATUSES:
            failure = SpeechUnavailable(f"Speech service returned {response.status_code}")
            continue
        if response.status_code != 200:
            raise SpeechUnavailable(f"Speech service returned {response.status_code}")
        return response
    raise failure


def _spoken_text(body: dict) -> str:
    segments = body.get("segments")
    if not isinstance(segments, list) or not segments:
        return body["text"]
    kept = [
        segment.get("text", "")
        for segment in segments
        if isinstance(segment, dict) and float(segment.get("no_speech_prob") or 0) < NO_SPEECH_LIMIT
    ]
    return re.sub(r"\s+", " ", " ".join(kept)).strip()


def sarvam_active() -> bool:
    """Whether Sarvam may be used now. Any doubt, such as a missing table on first start, means no."""
    from backend import addons
    from backend.db import connect

    db = connect()
    try:
        return addons.sarvam_ready(db)
    except sqlite3.Error:
        return False
    finally:
        db.close()


def _sarvam_post(path: str, **options) -> httpx.Response:
    """Like _post, for Sarvam: its own key header, the same allowed-host rule and one retry."""
    url = f"{settings.sarvam_base_url}{path}"
    if (urlsplit(url).hostname or "").lower() not in settings.allowed_ai_hosts:
        raise SpeechUnavailable("Sarvam host not on the allowed list")
    key = settings_store.api_key(None, "sarvam")
    if not key:
        raise SpeechUnavailable("No Sarvam key")
    headers = {"api-subscription-key": key}
    failure: Optional[SpeechUnavailable] = None
    for attempt in range(MAX_ATTEMPTS):
        if attempt:
            time.sleep(RETRY_PAUSE_SECONDS)
        try:
            response = httpx.post(url, headers=headers, timeout=SARVAM_TIMEOUT_SECONDS, **options)
        except httpx.HTTPError as error:
            failure = SpeechUnavailable(type(error).__name__)
            continue
        if response.status_code in (400, 413, 422):
            raise SpeechRejected(f"Sarvam returned {response.status_code}")
        if response.status_code in RETRY_STATUSES:
            failure = SpeechUnavailable(f"Sarvam returned {response.status_code}")
            continue
        if response.status_code != 200:  # 401, 402 (credits used up), 403
            raise SpeechUnavailable(f"Sarvam returned {response.status_code}")
        return response
    raise failure


def _sarvam_transcribe(audio: bytes, content_type: str, language: Language, model: str) -> str:
    base_type = content_type.split(";")[0].strip()
    response = _sarvam_post(
        "/speech-to-text",
        files={"file": (f"audio.{EXTENSIONS.get(base_type, 'webm')}", audio, content_type)},
        # codemix: patients mix Hindi and English. Never "translate": the confirmed text is the record.
        data={"model": model, "mode": "codemix", "language_code": language},
    )
    try:
        text = response.json()["transcript"]
    except (ValueError, KeyError, TypeError):
        raise SpeechUnavailable("Sarvam sent an unexpected reply") from None
    if not isinstance(text, str):
        raise SpeechUnavailable("Sarvam's reply had no text")
    return re.sub(r"\s+", " ", text).strip()


def transcribe(audio: bytes, content_type: str, language: Language) -> str:
    run = execution.AgentRun("speech_to_text")
    if sarvam_active():
        sarvam_model = settings_store.get("sarvam.stt_model")
        try:
            text = _sarvam_transcribe(audio, content_type, language, sarvam_model)
            run.tried("sarvam", sarvam_model, "succeeded")
            run.finish("succeeded")
            return text
        except (SpeechUnavailable, SpeechRejected) as error:
            run.tried("sarvam", sarvam_model, type(error).__name__)  # Whisper is tried next
    model = settings_store.model_for("transcription")
    try:
        text = _transcribe(audio, content_type, language, model)
    except (SpeechUnavailable, SpeechRejected) as error:
        run.tried("groq", model, type(error).__name__)
        run.finish("failed")
        raise
    run.tried("groq", model, "succeeded")
    run.finish("succeeded")
    return text


def _transcribe(audio: bytes, content_type: str, language: Language, model: str) -> str:
    base_type = content_type.split(";")[0].strip()
    response = _post(
        "/audio/transcriptions",
        files={"file": (f"audio.{EXTENSIONS.get(base_type, 'webm')}", audio, content_type)},
        data={
            "model": model,
            "language": LANGUAGE_CODES[language],
            "response_format": "verbose_json",
            "temperature": "0",
        },
    )
    try:
        text = _spoken_text(response.json())
    except (ValueError, KeyError, TypeError, AttributeError):
        raise SpeechUnavailable("The speech service sent an unexpected reply") from None
    if not isinstance(text, str):
        raise SpeechUnavailable("The speech service's reply had no text")
    return text


def speak(text: str, language: Language) -> bytes:
    """Returns WAV audio. Hindi isn't available here: the browser reads it instead."""
    if len(text) > MAX_SPEECH_CHARS:
        raise SpeechRejected("Text is too long to read aloud in one request")
    if language != "en-IN":
        raise SpeechUnavailable("No voice for this language")
    response = _post(
        "/audio/speech",
        json={"model": TTS_MODEL, "input": text, "voice": TTS_VOICE, "response_format": "wav"},
    )
    if not response.content:
        raise SpeechUnavailable("The speech service sent no audio")
    return response.content


def speak_neural(text: str, language: Language) -> bytes:
    """MP3 question audio. The caller falls back when the optional service is unavailable.

    Kept separate from speak(), whose WAV contract is also used by prescriptions.
    Called from synchronous route workers, never from an event loop.
    """
    if len(text) > MAX_SPEECH_CHARS:
        raise SpeechRejected("Text is too long to read aloud in one request")
    if not neural_tts_allowed() or language not in NEURAL_VOICES:
        raise SpeechUnavailable("Neural voice is disabled")
    try:
        import edge_tts

        async def collect():
            voice = edge_tts.Communicate(text, NEURAL_VOICES[language], rate="-8%", pitch="+0Hz")
            chunks = []
            async for chunk in voice.stream():
                if chunk["type"] == "audio":
                    chunks.append(chunk["data"])
            return b"".join(chunks)

        async def bounded():
            return await asyncio.wait_for(collect(), timeout=NEURAL_TIMEOUT_SECONDS)

        data = asyncio.run(bounded())
        if not data:
            raise SpeechUnavailable("Neural voice returned no audio")
        return data
    except SpeechUnavailable:
        raise
    except Exception as error:
        # Service exceptions can contain request text; expose only the exception type.
        raise SpeechUnavailable(type(error).__name__) from None


def speak_sarvam(text: str, language: Language) -> bytes:
    """MP3 from Sarvam Bulbul, in the Hindi or English voice chosen in Settings."""
    if len(text) > MAX_SPEECH_CHARS:
        raise SpeechRejected("Text is too long to read aloud in one request")
    if language not in LANGUAGE_CODES:
        raise SpeechUnavailable("No voice for this language")
    run = execution.AgentRun("text_to_speech")
    model = settings_store.get("sarvam.tts_model")
    voice = settings_store.get("sarvam.voice_hi" if language == "hi-IN" else "sarvam.voice_en")
    try:
        response = _sarvam_post(
            "/text-to-speech",
            json={
                "text": text, "language_code": language, "speaker": voice, "model": model, "output_audio_codec": "mp3",
                "pace": SARVAM_PACE, "temperature": SARVAM_TEMPERATURE,
            },
        )
        try:
            audio = base64.b64decode(response.json()["audios"][0])
        except (ValueError, KeyError, IndexError, TypeError):
            raise SpeechUnavailable("Sarvam sent an unexpected reply") from None
        if not audio:
            raise SpeechUnavailable("Sarvam sent no audio")
    except (SpeechUnavailable, SpeechRejected) as error:
        run.tried("sarvam", model, type(error).__name__)
        run.finish("failed")
        raise
    run.tried("sarvam", model, "succeeded")
    run.finish("succeeded")
    return audio


def question_audio(text: str, language: Language) -> Optional[Tuple[bytes, str]]:
    """Audio for text read to a patient, or None for the browser's own voice.

    Sarvam first when it is on, then today's order: Edge (demo mode only), then Groq for English.
    """
    if sarvam_active():
        try:
            return speak_sarvam(text, language), "audio/mpeg"
        except (SpeechUnavailable, SpeechRejected):
            pass
    if neural_tts_allowed():
        try:
            return speak_neural(text, language), "audio/mpeg"
        except (SpeechUnavailable, SpeechRejected):
            pass
    if language not in VOICED_LANGUAGES:
        return None
    try:
        return speak(text, language), "audio/wav"
    except (SpeechUnavailable, SpeechRejected):
        return None


def _pieces(text: str, limit: int = MAYURA_MAX_CHARS) -> List[str]:
    """Splits at sentence ends, and only mid-sentence when one sentence is longer than the limit."""
    pieces: List[str] = []
    current = ""
    for sentence in SENTENCE_END.split(text.strip()):
        while len(sentence) > limit:
            if current:
                pieces.append(current)
                current = ""
            pieces.append(sentence[:limit])
            sentence = sentence[limit:]
        candidate = f"{current} {sentence}".strip() if current else sentence
        if len(candidate) > limit:
            pieces.append(current)
            current = sentence
        else:
            current = candidate
    if current:
        pieces.append(current)
    return [piece for piece in pieces if piece.strip()]


def translate_to_english(text: str) -> Optional[str]:
    """An English machine translation of an answer the patient confirmed, or None.

    Only Hindi needs it, so text with no Devanagari isn't sent. A failure returns None: the doctor
    then reads the patient's own words, which are always shown anyway.
    """
    if not text.strip() or not DEVANAGARI.search(text) or not sarvam_active():
        return None
    run = execution.AgentRun("translation")
    model = settings_store.get("sarvam.translate_model")
    translated = []
    try:
        for piece in _pieces(text):
            response = _sarvam_post(
                "/translate",
                json={"input": piece, "source_language_code": "auto", "target_language_code": "en-IN", "mode": "formal", "model": model},
            )
            try:
                part = response.json()["translated_text"]
            except (ValueError, KeyError, TypeError):
                raise SpeechUnavailable("Sarvam sent an unexpected reply") from None
            if not isinstance(part, str):
                raise SpeechUnavailable("Sarvam's reply had no text")
            translated.append(part.strip())
    except (SpeechUnavailable, SpeechRejected) as error:
        run.tried("sarvam", model, type(error).__name__)
        run.finish("failed")
        return None
    run.tried("sarvam", model, "succeeded")
    run.finish("succeeded")
    return " ".join(translated)
