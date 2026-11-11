# Indian data sources, and the plan for a synthetic test set

Checked in November 2026 from the sources' public pages. Where a licence says **verify**, it could
not be confirmed from the page, so read the licence file before using it. Nothing here is legal
advice: have counsel review the "verify" items before any paid launch.

**The short version.** There is no large, openly licensed Indian clinical dataset for any of our
six tools. What exists is open speech data that isn't medical, official drug lists, and published
standards and statistics. So the plan is to build our own synthetic data, and to use the public
sources only to make it realistic.

## Rules

- Only public, legally usable sources. No scraping of hospital portals, no purchased or leaked data,
  nothing that identifies a patient.
- Real patient data needs an ethics committee, a data-use agreement and a DPDP Act review first.
  Until then, made-up patients only (see `agent_context.md`).
- Datasets are used for **evaluation** unless the licence says training is fine.

## Top sources, ranked by usefulness

| # | Source | Helps | Licence | Commercial use | Real patients |
|---|---|---|---|---|---|
| 1 | [Jan Aushadhi list](https://static.pib.gov.in/WriteReadData/specificdocs/documents/2026/mar/doc202634810501.pdf) (2,110 generics, Dec 2025) | Prescription Analyzer | Government publication | Yes, as facts | No |
| 2 | [NLEM 2022](https://qps.nhsrcindia.org/sites/default/files/2022-09/nlem2022.pdf) (384 medicines) | Prescription Analyzer | Government publication | Yes | No |
| 3 | [CDSCO approved new drugs](https://cdsco.gov.in/opencms/opencms/en/Approval_new/Approved-New-Drugs/) and [combination products](https://cdsco.gov.in/opencms/opencms/en/Approval_new/FDC-New-Drugs-Marketing/) | Prescription Analyzer | Government publication | Yes | No |
| 4 | [IndicVoices](https://huggingface.co/datasets/ai4bharat/IndicVoices) (about 12,000 h, 22 languages) | DiagnoFast, ClinScribe | CC-BY-4.0 | Yes, with attribution | No |
| 5 | [Eka Medical ASR Evaluation](https://aikosh.indiaai.gov.in/home/datasets/details/eka_medical_asr_evaluation_dataset.html) (3,619 English + 320 Hindi clips) | DiagnoFast, ClinScribe | MIT | Yes | **Verify** it holds no identifiable audio |
| 6 | [NRCeS FHIR guide for ABDM](https://nrces.in/ndhm/fhir/r4/all-examples.html) with example bundles | DischargeCare, ReferralLoop, LabLens, ABHA | Not stated, **verify** | Very likely | No |
| 7 | [ABDM sandbox](https://sandbox.abdm.gov.in/) | ABHA integration | Application and agreement | Yes, after approval | No (test data) |
| 8 | Indian reference intervals: [Sairam 2014](https://springerlink.bibliotecabuap.elogim.com/content/pdf/10.1007/s12291-013-0365-5.pdf) (10,665 adults), [IFCC C-RIDL India](https://www.degruyterbrill.com/document/doi/10.1515/cclm-2018-0152/html) (512 adults) | LabLens | Journal articles; numbers are facts, cite them | Yes | Aggregate only |
| 9 | [ICMR Standard Treatment Workflows](https://stw.icmr.org.in/stws) | DiagnoFast, ClinScribe, DischargeCare | Copyrighted PDFs, **verify** | Reference only, don't republish | No |
| 10 | [Kathbath](https://huggingface.co/datasets/ai4bharat/Kathbath) (150 h Hindi), [Svarah](https://huggingface.co/datasets/ai4bharat/Svarah) (9.6 h Indian English) | DiagnoFast, ClinScribe | CC0 (packaging) / CC-BY-4.0 | Yes | No |
| 11 | [data.gov.in](https://data.gov.in) HMIS and IDSP | Disease patterns | Government Open Data Licence India | Yes, with attribution | Aggregate only |
| 12 | [HiMed](https://huggingface.co/datasets/FreedomIntelligence/HiMed) (about 412,000 Hindi medical items) | Hindi vocabulary | Apache-2.0 on the card; the paper is CC BY-NC-SA, **verify** | Probably | No |

## By area

### 1. Hindi, Hinglish and Indian-language speech and text (DiagnoFast, ClinScribe)

| Source | Size and languages | Licence | Real patients | Note |
|---|---|---|---|---|
| IndicVoices | 12,000 h, 22 languages | CC-BY-4.0 | No | Gated download. Best general Hindi robustness data. |
| [IndicVoices-R](https://ai4bharat.iitm.ac.in/indicvoices_r) | 74.6 h Hindi, 399 speakers | CC-BY-4.0 per AI4Bharat; AIKosh says CC BY-ND (**verify**) | No | Could give synthetic test audio more voices. |
| Eka Medical ASR Eval | 3,619 English + 320 Hindi | MIT | **Verify** | Only Indian medical speech test set found. Evaluation only. |
| Kathbath / Vistaar | 150 h Hindi | CC0 packaging, web-crawled text | No | Standard Hindi recognition benchmark. |
| Svarah | 9.6 h, 117 speakers | CC-BY-4.0 | No | Tests the Indian-English voice path. |
| [Common Voice Hindi](https://datacollective.mozillafoundation.org/) | Small | CC0 | No | Freest licence, low volume. |
| [COIL-D Health v2](https://aikosh.indiaai.gov.in/home/datasets/details/health_v2_1.html) | Hindi health text, 19+ translations | CC-BY-4.0 | No | Symptom vocabulary for the red-flag rules. |
| [MCDH](https://aclanthology.org/2024.findings-emnlp.675.pdf) | Hinglish doctor-patient dialogues | No licence found | No | Ask the authors first. |
| [MMCQS / MedSumm](https://arxiv.org/abs/2401.01596) | 3,015 Hinglish queries | Not stated; derived from HealthCareMagic | No | Upstream terms unclear. |
| [IndicMedDialog](https://github.com/ShubhamKumarNigam/IndicMedDialog) | Synthetic dialogues, English + 9 languages | Paper CC BY-NC-ND; data licence unknown | No | Treat as non-commercial. |
| [DISPLACE-M / DoPaCo](https://arxiv.org/abs/2603.06373) | 125 real Hinglish consultations, 24.5 h | Likely a challenge agreement | **Yes (real)** | Needs a data-use agreement and review. Don't use yet. |

### 2. Prescriptions and drug names (Prescription Analyzer)

- Drug names: items 1–3 above. They cover generics, not brands.
- Current brand list: [junioralive/indian-medicine-dataset](https://github.com/junioralive/indian-medicine-dataset),
  about 254,000 brands. The repo is MIT but the data looks scraped from pharmacy sites, so replace it
  before selling.
- Images: no openly licensed Indian handwritten prescription set exists.
  [Garain et al.](https://ieee-dataport.org/documents/dataset-classification-handwritten-and-printed-text-doctors-prescription)
  has 11,340 images labelled only handwritten or printed (IEEE DataPort, licence **verify**).
  Bangladeshi sets such as [RxHandBD](https://data.mendeley.com/datasets/dsb5r6vskg) (5,578 word
  images) help handwriting robustness only. Prescription images have to be made by us.

### 3. Lab reports and reference ranges (LabLens)

- Ranges: the studies in row 8. There is no single official ICMR adult table; ICMR's
  [TERIIP](https://www.icmr.gov.in/icmrobject/uploads/Call/1761797370_expressionofinteresteoiicmrstaskforceonestablishmentofreferenceintervalsinindianpopulationteriipphaseii.pdf)
  (children) is still a call for proposals.
- Formats: copy only the layout of public sample reports (column order, units, how flags print).
  Never reuse another lab's logo or wording, and never collect real reports.

### 4. Discharge summaries and referral letters

- NRCeS example bundles (row 6) give India-specific DischargeSummary, OPConsultation and
  DiagnosticReport structures with made-up patients.
- Mendeley synthetic notes: [Clinical Notes Based on Indian Format](https://data.mendeley.com/datasets/nn5r5htbpx)
  (10,000 notes) and [Synthetic Indian Clinical Notes](https://data.mendeley.com/datasets/bzgjmph5n2/1).
  Licence and quality **unverified**.
- MIMIC is American, credentialed and real patient data. Not recommended.

### 5. Disease patterns

| Source | Licence | Note |
|---|---|---|
| data.gov.in HMIS, IDSP | Government Open Data Licence India | Best legal base for how common each disease is, by state and season. |
| ICMR Standard Treatment Workflows | Copyrighted | Reference for case templates. Don't republish. |
| NFHS-5 published reports | Government publication | Use published tables. The [DHS microdata](https://dhsprogram.com/data/terms-of-use.cfm) is research-only, needs registration and bars commercial use. |
| [GBD India](https://www.healthdata.org/disease-burden-India) | **Non-commercial only** | A commercial product needs an IHME licence. |
| ICMR-INDIAB, LASI | Registration, research terms | Same handling as NFHS microdata. |

### 6. ABDM and FHIR

- ABDM sandbox: apply as an organisation; a committee approves access (consultants say 2–4 weeks,
  unofficial). Test ABHA numbers are on `abhasbx.abdm.gov.in`. Production needs a "sandbox exit" review.
  This is what replaces the simulated `abha.py`.
- NRCeS FHIR guide: validate every synthetic bundle against its profiles.
- [Synthea](https://github.com/synthetichealth/synthea) (Apache-2.0) has no India module. Optional.

## Needs approval, an agreement, or is non-commercial

- **Real patient data:** DISPLACE-M/DoPaCo, MIMIC, and any real pilot (ethics committee, ICMR ethical
  guidelines, DPDP Act).
- **Registration or agreement:** ABDM sandbox; NFHS, LASI and INDIAB microdata; gated Hugging Face
  sets (IndicVoices, Eka, Kathbath).
- **Non-commercial:** GBD/IHME; possibly IndicMedDialog; IndicVoices-R if its CC BY-ND listing is right.
- **Licence unclear:** MCDH, MMCQS, the Mendeley notes, Garain, the NRCeS examples, ICMR workflows,
  and the current scraped brand list.

## Plan: a synthetic Indian dataset, 1,000+ made-up patients per tool

### Shared base

1. **One generator of made-up patients**, with no keys or network. Each patient has an age, sex,
   state, language (Hindi, English or Hinglish), conditions, medicines, lab values and a history.
   - Disease mix from HMIS/IDSP shares and the ICMR workflow conditions.
   - Medicines only from Jan Aushadhi, NLEM and CDSCO.
   - Lab values from the published Indian ranges, with deliberate abnormal cases.
2. **Every record is marked synthetic** (`is_synthetic: true`, plus the seed), so the set rebuilds
   exactly. Names from a made-up list. No real phone numbers, ABHA numbers or addresses.
3. **A datasheet:** where each fact came from, the licences, and the known biases.

### Per tool

| Tool | What to make | Labels |
|---|---|---|
| DiagnoFast | Scripted interviews for all 6 forms in Hindi, Hinglish and English, including vague, contradictory and very long answers. At least 300 red-flag and 300 negated or history cases. Audio from several voices plus noise, and about 200 consented actor-recorded interviews. | Expected form fields, expected urgent flags, gold transcript |
| ClinScribe | Role-played consultations by consented actors following ICMR workflows, with clinician-written gold SOAP notes | Each note statement linked to its transcript line |
| LabLens | Extend `backend/tests/lab_validation` from 12 to about 40 Indian-style layouts, each as a text PDF, a scan and a phone photo (blur, tilt, shadow). Odd units, missing ranges, flags that disagree with the range. | Test, value, unit, range and flag per row |
| Prescription Analyzer | Volunteers handwrite made-up prescriptions under a consent and image-rights form, using the official drug lists. Mix in printed ones. All shorthand (1-0-1, BD, TDS, HS, SOS, x 5 days) and deliberately illegible fields. About 1,000 images from 20+ writers. | Every field, with clear, unsure or unreadable expected |
| ReferralLoop | Episodes following the FHIR structure, including rejections, no-shows and delays | Expected state path and alerts |
| DischargeCare | Indian-style discharge summaries following the NRCeS profile, with tasks, pending results and barriers | Expected checklist, tasks and closure rules |

### A frozen test set, to measure before and after any change

- Keep about 20% of each tool's data as a frozen, versioned test set (for example `eval/v1/`). Never
  tune on it. Spread it across language, specialty and difficulty. A clinician reviews 10% of it, and
  two people label a subset to check they agree.
- **Metrics**
  - DiagnoFast: field accuracy; red-flag recall (100% on rule cases) and false alarms; word error
    rate on medical terms.
  - ClinScribe: unsupported-statement rate and omission rate.
  - LabLens: exact match per field, against today's 37/37 synthetic score.
  - Prescription Analyzer: drug-name, dose and frequency accuracy, and above all how often a wrong
    reading is marked "clear".
  - ReferralLoop and DischargeCare: deterministic state tests.
- Every model, prompt or rule change reruns the set (`backend/tests/ai_eval/` for AI, the normal
  suite for rules). A safety-metric regression blocks the merge.
- External sets (Eka, Kathbath, Svarah) are evaluation-only and never mixed into training.

### Legal checklist

- Signed consent and image/voice release from every actor and writer, recorded under the DPDP Act.
- No real prescriptions, reports or recordings.
- Keep attribution files for CC-BY sources.
- Counsel reviews the "verify" items before any paid launch.

## What exists today

- `python -m backend.synthetic.seed_accounts` makes synthetic doctors, patients with logins, and
  patient records without logins, with consents, a visit and sometimes an allergy. The logins are
  written to `backend/storage/synthetic/` (git-ignored). See the README in that folder.
- Next: the generators above, one tool at a time, starting with DiagnoFast red-flag cases and
  LabLens layouts, because their gold labels need no clinician.
