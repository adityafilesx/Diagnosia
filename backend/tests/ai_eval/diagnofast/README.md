# DiagnoFast labelled test data

Made-up interviews and single answers with known answers, to measure DiagnoFast before and after a
change. See `v1/DATASHEET.md` for what is in it and, more important, what it cannot show.

```bash
python -m backend.synthetic.diagnofast_data          # rebuilds v1 (identical bytes; a test checks this)
python -m backend.synthetic.diagnofast_eval          # urgent-symptom rules, dev split. No keys, no network
python -m backend.synthetic.diagnofast_eval --split test   # frozen: report before and after a change
python -m backend.synthetic.diagnofast_eval --live --limit 100   # whole interviews with your AI keys
```

The frozen files can't change: `manifest.json` holds their SHA-256 and a test fails if one differs.
To change the data, make a new version (`v2`) so old scores stay comparable.

## Baseline: urgent-symptom rules (`red_flags.screen`), 11 November 2026

Run before any rule change, on the frozen test split. Dev split in brackets.

| Check | Test | Dev |
|---|---|---|
| Single answers with an urgent symptom, exact flags | 36/42 (85.7%) | 140/180 (77.8%) |
| Negation then symptom ("no fever, but chest pain"), exact flags | 7/11 (63.6%) | 52/65 (80.0%) |
| Negated mention, no flag | 14/15 (93.3%) | 85/93 (91.4%) |
| History mention, no flag | 6/6 | 17/17 |
| Ordinary complaints, no flag | 6/6 | 39/39 |
| Urgent interviews stopped at the right turn | 59/68 (86.8%) | 205/244 (84.0%) |
| Calm interviews wrongly stopped | 2 of 175 | 5 of 713 |

Recall by category on dev (test has too few per category to read): fainting 100%, self-harm 100%,
trouble breathing 94%, chest pain 81%, heavy bleeding 81%, severe allergy 78%, stroke signs 69%,
seizure 64%, poisoning 54%. By script on dev: English 91%, Devanagari 86%, romanised Hindi 75%.

### What the baseline found (real gaps in the rules, not data mistakes)

1. **Missed urgent phrasings.** The rules miss, among others: "face has gone crooked", "mouth has gone crooked",
   one-sided weakness in Hindi ("एक तरफ का हाथ पैर कमज़ोर"), jerking limbs without the word "seizure"
   ("हाथ पैर अकड़ गए हैं और झटके आ रहे हैं"), "बच्चे ने कीटनाशक पी लिया", "खांसी में खून आ रहा है",
   "He ate a whole strip of sleeping pills", swelling of the face with "सांस रुक रही है", and "heavy pressure
   in my chest". A missed urgent answer is the costly error, because the AI layer is the only other check.
2. **Hindi negation after a longer symptom phrase is not recognised.** "आत्महत्या के विचार नहीं है",
   "aatmahatya ke vichar nahi hai", "बेहोशी कभी नहीं हुआ" and "ज़हर खाना कभी नहीं हुआ" are flagged as urgent
   because the negation is more than one word away from the matched stem, or the stem is followed by a suffix.
   This over-flags, so it is the safer error, but it stops calm interviews.
3. **A negation can leak across a sentence in romanised Hindi** in one pattern, giving an extra label
   ("aatmahatya ke vichar nahi hua. seene par bhaaripan aur dabav hai" gives Chest pain and Self-harm).

These are left for a separate change with a clinician's review. The rules were not edited when this data was made.

### Questions for the product owner and a clinician

The 12 "ambiguous" answers are reported, not scored. For example: is "short of breath on climbing stairs"
urgent? Is "chest pain about two years ago"? Today the rules flag both. Decide the policy, then label them.
