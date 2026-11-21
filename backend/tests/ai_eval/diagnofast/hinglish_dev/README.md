# Hinglish phrasings (dev only, not frozen)

Hand-written single answers mixing Hindi and English, for the IIITD hackathon build (BUILD.md step 9).
They cover romanised Hinglish ("chest mein bahut pain hai") and the mixed-script style Sarvam's Saaras
v4 writes in its `codemix` mode ("मुझे chest में pain है").

- **Dev only.** Use them to measure and to tune, never as a frozen test. They are not part of `v1`, and
  `v1` is never edited.
- **Not clinically reviewed.** The labels follow `v1`'s categories. A clinician and a Hindi speaker should
  check them before they count for anything.
- Run: `python -m backend.synthetic.diagnofast_eval --hinglish`
