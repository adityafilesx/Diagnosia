# Sarvam AI

Sarvam AI is an Indian provider of speech and language models. Diagnosia uses it for **Hindi and
English only**, including mixed Hindi and English (Hinglish), in DiagnoFast:

- **Speech to text first**, with Groq Whisper as the fallback.
- **A voice first**, with today's voices as the fallbacks.
- **Translation of the Hindi text the patient confirmed**, so the doctor sees English beside it.

It is optional and off by default. With the switch off, no key, or `ALLOW_REAL_PATIENT_DATA` on, the
app behaves exactly as it did before Sarvam. **Made-up patients only.**

Sarvam was removed from the code on 31 October 2026. Bringing it back was a product decision taken for
the IIITD hackathon build (`BUILD.md`).

Researched on 21 November 2026 from Sarvam's own pages. Every fact below has its source. Re-check them
before relying on them, because model names have already changed once: the names in our first plan
(Saarika, Bulbul v2, Sarvam-M) no longer appear in the current documentation.

## Sources

| Short name | Page |
|---|---|
| STT | <https://docs.sarvam.ai/api-reference-docs/speech-to-text/transcribe> |
| TTS | <https://docs.sarvam.ai/api-reference-docs/text-to-speech/convert> |
| VOICES | <https://docs.sarvam.ai/api/api-guides-tutorials/text-to-speech/voices> |
| TR | <https://docs.sarvam.ai/api-reference-docs/text/translate> |
| CHAT | <https://docs.sarvam.ai/api-reference-docs/chat/chat-completions> |
| LIMITS | <https://docs.sarvam.ai/api-reference-docs/ratelimits> (Pricing, Credits and Rate Limits) |
| PRICE | <https://www.sarvam.ai/api-pricing> |
| RETENTION | <https://docs.sarvam.ai/api/platform/data-retention> |
| TRUST | <https://www.sarvam.ai/trust-center> |
| PRIVACY | <https://www.sarvam.ai/privacy-policy> (updated 29 July 2026) |
| TERMS | <https://www.sarvam.ai/terms-of-service> (version 2.0, effective 29 July 2026) |

## Common to every call

- Host: `api.sarvam.ai`, over HTTPS. It is added to `DIAGNOSIA_ALLOWED_AI_HOSTS`. A call to any other host
  is refused before it is made.
- Authentication: the header `api-subscription-key: <key>` (STT, TTS, TR). The key comes from
  `SARVAM_API_KEY` in `.env` or from Settings, never from code.
- Errors (LIMITS): 429 means the rate limit was reached and 402 (`insufficient_quota_error`) means the
  credits are used up. Retry 429 and 503 with backoff. Like `speech._post`, we retry once and then fall
  back to the next provider.

## Speech to text (Saaras v4, which replaces Saarika)

| Item | Value | Source |
|---|---|---|
| Endpoint | `POST https://api.sarvam.ai/speech-to-text`, `multipart/form-data` | STT |
| Model | `saaras:v4` (default, recommended). `saaras:v3` is legacy. No Saarika model is listed | STT |
| Fields | `file`; `model`; `mode` = `transcribe` (default), `translate`, `verbatim`, `translit`, `codemix`; `language_code` (`hi-IN`, `en-IN`, …, or `unknown` for auto-detect) | STT |
| Response | `request_id`, `transcript`, `language_code`, optional `timestamps` and `language_probability` | STT |
| Audio | WAV, MP3, AAC, AIFF, OGG, OPUS, FLAC, MP4/M4A, AMR, WMA, WebM, PCM. Mixed down to mono; 16 kHz works best | STT |
| Length | The REST endpoint is for audio "under 30 seconds". No hard size limit is stated. Our recordings stop at 28 s | STT |
| Hinglish | `mode=codemix` writes English words in Latin script and Hindi words in Devanagari, for example "मेरा phone number है 9840950950". `mode=translit` writes everything in Latin script | STT |

**How we use it.** We send `mode=codemix` with `language_code` set to the language the patient chose
(`hi-IN` or `en-IN`), because the patient often mixes the two. The urgent-symptom rules already read
Devanagari, Latin-script Hindi and English, so codemix output is screened as it is today.

**What we don't use.** `mode=translate` turns the audio straight into English. We never use it for the
record, because the text the patient confirmed takes priority over any reading of the audio (see
`agent_context.md`). Translation runs on the confirmed text instead (below).

**Whisper's no-speech filter stays** on the Groq fallback. Saaras returns no per-segment no-speech
score, so nothing replaces that filter on the Sarvam path. The patient still sees, edits and confirms
every transcript before it is saved.

## Text to speech (Bulbul v3 and v4-flash)

| Item | Value | Source |
|---|---|---|
| Endpoint | `POST https://api.sarvam.ai/text-to-speech`, JSON | TTS |
| Models | `bulbul:v3` (the default when the model is omitted) and `bulbul:v4-flash` (recommended for new work). No Bulbul v2 is listed | TTS |
| Fields | `text` (1 to 2,500 characters), `language_code` (`hi-IN`, `en-IN`, …), `speaker`, `pace` 0.5–2.0, `pitch`, `loudness`, `speech_sample_rate` (22050 by default), `output_audio_codec` (`wav` by default, or `mp3` and others) | TTS |
| Response | `request_id`, `audios`: a list of base64 strings in the chosen codec | TTS |
| Voices | v3: 37 speakers, default `shubh`, with no per-language tags. v4-flash: `<name>_<lang>_<style>`, for example Hindi `ritu_hi_customer`, English `neha_en_customer`, and Hinglish `ishita_enhi_customer` | VOICES |

**How we use it.** `bulbul:v4-flash` as the default model, MP3 output (matching the Edge path, so the
page plays it the same way), and one Hindi and one English voice from Settings. The defaults are
`ritu_hi_customer` and `neha_en_customer`. Both models and voices are settings, because they change.
Our longest spoken text (a consent line, a question) is well under 2,500 characters, and longer text is
refused, as `speech.MAX_SPEECH_CHARS` already does.

**Why it matters.** Today Hindi is read by a neural voice only in demo mode (Edge), because Groq has no
Hindi voice. With Sarvam on, Hindi questions, consent lines, the queue number and the urgent message
are read in a natural voice outside demo mode too, still with made-up patients only.

## Translation (Mayura)

| Item | Value | Source |
|---|---|---|
| Endpoint | `POST https://api.sarvam.ai/translate`, JSON | TR |
| Models | `mayura:v1` (modes, scripts, auto-detect) and `sarvam-translate:v1` (formal mode only) | TR |
| Fields | `input` (at most 1,000 characters for `mayura:v1`), `source_language_code` (`auto` allowed for Mayura), `target_language_code`, `mode` (`formal`, `modern-colloquial`, `classic-colloquial`, `code-mixed`), `model` | TR |
| Response | `request_id`, `translated_text`, `source_language_code` | TR |
| Code-mixed input | **Not stated.** `code-mixed` is documented as an output mode only | TR |

**How we use it.** `mayura:v1`, `source_language_code=auto` (the answer may be Hinglish),
`target_language_code=en-IN`, `mode=formal`. An answer longer than 1,000 characters is split at
sentence breaks and the pieces are joined, because a typed answer can be up to 2,000 characters. The
English is stored beside the original, labelled "machine translation", and never replaces the
patient's words. A translation that fails is simply missing: the doctor reads the original.

## Chat (stretch only)

`POST https://api.sarvam.ai/v1/chat/completions` with `sarvam-105b` or `sarvam-105b-conversations`
(CHAT). It is OpenAI-shaped and supports `response_format` `json_schema`. The page lists both
`api-subscription-key` and `Authorization: Bearer` (examples use Bearer). Reasoning is on by default and
billed as output tokens. No Sarvam-M model is listed.

**Built as a stretch item** (Settings, Sarvam AI, "Also try Sarvam's chat model", off): `llm.py` adds
`sarvam-105b` as a third provider, always tried last, for text only (never photos), with `max_tokens`
in place of `max_completion_tokens`. It needs Sarvam's own switch, key and sign-off too, and stops with
real patient data allowed. Not run live.

## Limits and prices

Rate limits per account, pay-as-you-go plan (LIMITS): speech to text 60 requests a minute, text to speech
60, translation 60, chat 60. A DiagnoFast interview makes at most about 12 of each, so a demo stays far
below them.

Prices, excluding GST (LIMITS, PRICE):

| Service | Pay as you go |
|---|---|
| Speech to text | Rs 0.49 a minute |
| Bulbul v4-flash | Rs 2.00 per 1,000 characters (v3: Rs 3.00) |
| Translation | Rs 2.00 per 1,000 characters |
| Sarvam 105B | Rs 10 per million input tokens, Rs 25 per million output tokens (introductory, to the end of 2026) |
| Free credit | Rs 100 on sign-up for verified users |

**Rough cost per intake (our estimate, not measured).** About 2 minutes of answers (Rs 1), about 1,500
characters spoken (Rs 3) and about 800 characters translated (Rs 1.60): roughly Rs 5 to 6 on top of
today's Rs 2 to 2.50 of AI calls. Voice is the largest part, so Settings can keep Sarvam for speech to
text and translation and leave the voice to today's providers. Measure it during the build.

## Data handling

Sarvam's own pages disagree with each other. Quoted exactly:

| Question | What the pages say | Status |
|---|---|---|
| Where is data processed? | TRUST: "In India, for Indian customers. Our managed production environment runs on Microsoft Azure's Central India region". TERMS 8.2: "We process and store information in India and may transfer it to other countries". PRIVACY lists transfers to the "United States: Cloud infrastructure (AWS, GCP, Azure)" and the EU | **Unconfirmed.** Conflicting statements |
| How long are inputs kept? | PRIVACY: "User-configurable (default: 30 days after last access)". RETENTION: "Until an Owner sets a retention period, your workspace's data is retained indefinitely." Zero retention ("No retention (0 days)") is "supported for Model APIs" | **Conflicting default.** The account owner must set zero retention |
| Used for training? | PRIVACY: "Default Policy: Opt-In", content is used "to train, fine-tune, and/ or improve our AI models unless you explicitly opt-out". TRUST says data is not used "to improve models for anyone else" | **Training is on unless the owner opts out** |
| Certifications | PRIVACY and TRUST: ISO 27001:2022 and SOC 2 Type II. TRUST lists the DPDP Act as "In progress"; PRIVACY calls Sarvam's operator a Data Fiduciary under it | Claimed, not checked by us |
| Data agreement | TERMS 8.1: a Data Processing Addendum applies to customer processing. TRUST offers it on request | Not requested or signed |
| Health data | PRIVACY: "We do NOT knowingly collect sensitive personal data as defined under DPDPA (… health data …)". No health-data position for API inputs | **Not stated** |

**What the account owner must do before any demo with a Sarvam key:** set the workspace retention to
"No retention (0 days)" and opt out of model training in the account settings. This software can't do
either or check them. Data staying in India is **unconfirmed**: say "may keep data in India, to be
confirmed in writing", never "stays in India".

## Fallback order

| Task | First | Then |
|---|---|---|
| Speech to text | Sarvam Saaras v4 (`codemix`) | Groq Whisper, with its no-speech filter |
| Voice | Sarvam Bulbul | Edge Neerja/Swara (demo mode only), Groq English, the browser's voice, on-screen text |
| Translation | Sarvam Mayura | None. The doctor reads the patient's own words |

Each attempt is recorded with `execution.AgentRun`, as the Groq calls are. No key, patient text or full
answer is ever logged.

## Live check

On 22 November 2026 a smoke test with made-up text passed: Bulbul v4-flash read a Hindi and an English
question (MP3), Saaras v4 in `codemix` mode wrote each back word for word, and Mayura translated a Hindi
sentence to English. No patient data was sent.

## Tests

Tests never call Sarvam. They patch the HTTP call in `speech.py`, as the Groq tests do, and check the
request shape, the fallbacks, the refusal with real data allowed, and that nothing is logged.
