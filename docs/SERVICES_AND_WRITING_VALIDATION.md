# Services and written dictation validation · 2026-10-04

This record describes an earlier Services revision. Current evidence is in [0.4.4 validation](RELEASE_0.4.4.md). Older validation sections
describe their respective revisions rather than every subsequent change.

## Services layout

Settings → Services opens a fixed-size, scroll-free overview with three modules:

1. **Speech to Text** — microphone audio to a transcript.
2. **Polish** — clear writing in the original language, with its own model.
3. **Ask Anything** — independent model configuration for questions, edits and drafts.

Every module has a model menu on the right, a short identity/status line,
**Test**, result details and **Advanced**. Advanced pages have a fixed **Back**
button and scroll only their detailed parameters. **Save changes** remains fixed.
Navigating between pages retains drafts; selecting or testing a model does not
save it. Custom endpoints, model identifiers, saved profiles and credential
handling continue to use the existing configuration flow.

Automatic selection is still **Auto**. The actual model and its corresponding
icon appear only after a successful check; choosing Auto does not imply a model
has been loaded or verified. Tests use the current unsaved configuration.
The active service's selector is disabled while its check is running.

Qwen, DeepSeek, Ollama and OpenAI use locally stored official marks with source
and terms retained. SenseVoice, Paraformer, Fun-ASR and cloud speech use distinct
neutral MurMur glyphs where an official engine-specific mark was not verified.
OpenAI-compatible transport alone does not establish an OpenAI model identity.
See [provider icon provenance](PROVIDER_ICONS.md).

## Written dictation

The stock dictation prompt now asks for readable written expression: remove
hesitation, filler words, accidental repeats and abandoned starts; improve
sentence structure; use paragraphs or a list when the dictated content supports
that structure. A clear self-correction should retain its final value. Genuine
uncertainty, facts, unfamiliar names and meaningful English terminology remain.

Chinese stays Chinese, English stays English, and mixed-language technical terms
remain in the mixed text. Examples and reinforcing rules match the source's
language. Spoken requests are text to edit, not instructions to execute. Explicit
Translation still uses its separate translation operation and target language.
No editorial preface, answer to a dictated question or added factual claim is
requested. Known stock prompts migrate in memory; custom prompts are preserved.

Protected quotes are supplied as source data. If content is unchanged and its
location is unambiguous, the application can restore missing or altered quote
delimiters. Changed quoted content or an ambiguous location causes a failure
with the original transcript retained. The check is conservative and does not
claim to detect every semantic change in unquoted text. Quotation recovery
retains returned token usage. Obvious mixed-language English-term loss is also checked; explicit corrections skip that lexical check. Full Han/Latin source-language loss is
rejected before a final result is automatically copied or pasted.

## Current automated verification

| Scope | Result | Evidence |
| --- | --- | --- |
| Provider, language, quotes, mixed-term safety, writing rules, Ask, storage and service mocks | 292 passed, 10.63 s | `work/pytest-services-term-safety-final.log` |
| Combined providers/storage/controller/workflow checks before the last mixed-term safeguard | 376 passed, 101.36 s | `work/pytest-services-delivery-combined.log` |
| Settings, three-module navigation, drafts, test state and fixed layout at 125% | 70 passed, 89.32 s | `work/services-stable-ui-verification/pytest-125.log` |
| Same UI scope at 150% | 70 passed, 89.30 s | `work/services-stable-ui-verification/pytest-150.log` |
| Icon identity, local assets, licensing, SVG safety and dark visibility | 42 passed | `tests/test_provider_icons.py` and related targeted tests |
| Latest isolated application startup | exit 0, 16 screenshots | `work/services-delivery-startup-smoke.log` |

The 376-test run captured 119 unchanged operational source/test/asset hashes.
After adding the term-loss safeguard, the 292-test run captured 120 unchanged
hashes. UI source/test hashes were unchanged across the final two UI runs.
These are scoped checks, not a claim that every project test ran against every
subsequent prompt revision. The initial broad run had 475 passes and 7 failures
while files were changing; outdated control and suffix assumptions were fixed
and affected checks rerun. Original logs remain retained.

Startup uses synthetic data, offscreen Qt, disabled global hotkeys and stubbed
credential/microphone discovery. It does not read user recordings or history or
make paid requests. The overview, detailed Polish page, speech dropdown and
long-model/error layouts were visually inspected at 125%/150%. The main window
remains 920 × 680 logical pixels and cannot be resized or maximized.

## Actual local model calls

`work/services-public-language-final.json` contains the final actual
OpenAI-compatible loopback calls, raw model output, returned usage, timings,
manual reviews and unchanged source hashes. Auto selected **qwen3.5:2b**.
Only fixed public examples were sent; there was no microphone input, user text,
cloud key or user usage-ledger write.

Seven core samples retained the correct language and operation: Chinese, mixed
terminology, English, a quoted API response, Chinese and English dictation
mentioning translation, and explicit Translation. The final mixed response kept
review, interface, bubble, Settings and Auto model selection. The English spoken
translation request remained English but omitted Please; politeness fidelity is
not perfect. Earlier explicit Translation lost today; the final call retained it.
A single successful sample does not establish general semantic accuracy.

The shortened shared rules initially regressed mixed terms and Chinese dictation
mentioning translation. Stronger source-specific language rules restored the
latter. A subsequent mixed response still translated bubble, so a lexical
safeguard now rejects obvious English-term loss before automatic copy/paste,
retaining the original transcript. Function words, fillers and case changes do
not force the original syntax. Explicit correction markers skip this lexical
check because deletion of a superseded phrase can be legitimate and its scope
cannot be determined reliably by token matching. Quote and whole-language checks
still apply. No paid retry or silent model change was added.

`work/services-public-structured-writing.json` records a separate fixed sample
about a three-part Services interface. Actual 2B output removed hesitation and
repetition and expressed the requirements as clear written sentences while
retaining module names. It did not produce a list; list formatting is not forced.
The source had no correction markers, so the new term check does not change its
accepted result. Earlier quote evidence also records recovery of unchanged
contents and rejection of altered contents, rather than treating a guarded
failure as successful polishing.

Small models are not reliably correct on every self-correction. Earlier 2B
weekday trials retained both values or introduced an alternative. An
already-installed 9B model passed two comparable correction examples (22.390 s
including loading for the first, 2.281 s for the second), on an earlier prompt
revision. This is not a final-source or universal quality/latency claim. Auto
and the user's saved model were not silently changed; larger models remain
selectable from Polish. Failed and earlier prompt revisions are retained in
separate evidence files rather than discarded.

## Limits

This turn did not revalidate physical hotkeys, microphone recording, clipboard
restoration, target focus, browser inputs or multi-screen positioning. The real
online provider paths remain available, but no new cloud calls were made for
this change. Ask Anything's independent online credentials remain user-owned.
The portable security block remains in effect; no portable payload was rebuilt,
copied or executed. Development and generated files stayed in the active local
workspace, with no Git operation or retired Dropbox build/cache recreation.
