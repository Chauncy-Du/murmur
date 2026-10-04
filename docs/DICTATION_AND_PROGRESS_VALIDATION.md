# Dictation language and capsule progress — 2026-10-04

Active source: `D:\LocalProjects\MurMur`. Interface labels remain English.

This is the earlier capsule/language validation snapshot. The later written-polish contract, quotation protection and redesigned Services pages are documented in [SERVICES_AND_WRITING_VALIDATION.md](SERVICES_AND_WRITING_VALIDATION.md). Sample timings and test counts below belong to that earlier revision.

## Ordinary dictation

Right Alt dictation performs minimal cleanup in the source language. Chinese remains Chinese; mixed Chinese/English retains its Chinese structure and English terms. The translation target does not apply to this mode. Requests mentioned in dictated speech remain text to edit, rather than commands to execute.

The provider sends dictated text losslessly inside a JSON data field and supplies short examples of the editing contract. The response is plain edited text, with no generated introduction, explanation, language label or added quotation wrapper. Quotation marks in the source are retained. Explicit Translation and selected-text actions keep their separate request paths.

Known stock Chinese and previous English dictation prompts migrate in memory; custom prompt strings remain intact. The mandatory ordinary-dictation contract applies to both stock and custom profiles. Opening a profile does not rewrite its settings file.

A final source-specific constraint distinguishes Chinese, English and mixed input. A coarse output check rejects a result that loses all substantive Han text from the input, or converts substantive Latin words into Han-only output. Independently delimited filler-only words can still be removed. These checks are backstops against complete script loss; they do not prove semantic fidelity or identify every translation error. Rejected results follow the existing failure path: original text remains available, no automatic clipboard copy/paste occurs, and progress does not become 100%. Reported API usage still counts the completed request.

## Actual local model verification

The fixed public samples used the real `transform` path, local Auto selection and OpenAI-compatible endpoint at `127.0.0.1`. The response model was `qwen3.5:2b`. The initial prompt-only fix failed a mixed-language sample; a later trial also failed a spoken translation request. Those failures led to the data boundary and examples described above.

The final verification produced:

| Case | Observed final behavior | Time |
| --- | --- | ---: |
| Chinese | Chinese text, without its opening filler | 1.000 s |
| Mixed Chinese/English | Chinese structure retained; `review`, `interface`, `bubble`, `Settings`, `Auto model selection` retained | 0.515 s |
| English | English text, without `Um` | 0.406 s |
| Quoted mixed text | Chinese and English terms plus original curly quotation marks retained | 0.375 s |
| Spoken request to translate | The request remained Chinese dictated text; it was not executed | 0.360 s |
| Explicit Translation | The Chinese source was translated into English | 0.250 s |
| English spoken request to translate | The request remained English dictated text; it was not executed | 9.859 s |

None of these seven final outputs added an editorial preface. These are observed sample timings, not general latency or compliance guarantees. The extra English case initially translated incorrectly and was corrected after adding the source-specific constraint and symmetric guard. Usage returned by the model is saved in the six-case test evidence; external cost is zero for these local calls. The diagnostic does not write to the user's usage ledger.

Evidence: `work/dictation-language-final-six-validation.json` and `work/dictation-language-english-instruction-validation.json` (the latter recovered from the instrumented log). No personal speech, history, clipboard contents, cloud credentials or microphone input was used.

## Capsule workflow progress

Processing uses the whole rounded capsule as its purple progress background, beneath the operation label and percentage. The former looping Thinking indicator has been removed. A finite 180 ms animation smooths an actual milestone; it does not advance progress on a timer.

| Operation | Actual displayed steps |
| --- | --- |
| Dictation with cleanup | Transcribe → Polish |
| Dictation without cleanup | Transcribe |
| Voice translation | Transcribe → Translate |
| Voice input for an editor instruction | Transcribe |
| Ask Anything | Transcribe → Respond |
| Selected-text editing | Its one selected operation: Refine / Translate / Summarize / Expand / Edit |

Percentages represent completed workflow steps, not internal ASR or LLM computation. A two-step operation starts at 0%, reaches 50% after recognition, and reaches 100% only after a valid result. A one-step operation stays at 0% until its result is ready. Selected-text capture does not pretend to transcribe audio. No Search stage is displayed when no search is performed.

Cancel, failures, empty/malformed responses and stale callbacks do not report successful completion. The real PCM recording waveform, compact size, no-activate flags and 240 ms expansion into the result bubble remain in place.

## Visual and automated verification

- Capsule, waveform and result-bubble tests: 34 passed at each of 125% and 150% scale.
- Controller workflow, regular controller and Ask tests: 77 passed before the final language guard additions.
- Final language/provider/error-recovery/local-model/usage tests: 132 passed; the added usage-preservation regression plus language/error-recovery tests then passed 38 checks.
- The full suite passed 914 tests (642.38 s, three dependency warnings). Source changes continued during that run, so this is evidence for the starting revision rather than every final change.
- The final affected integration suite passed 414 tests (139.89 s). Its 90 source/test file hashes were unchanged across the run. It covers the current language guards, background error recovery, providers, local model selection, usage, controllers, settings, service overview, waveform and result workflow.
- The latest source startup exited successfully with 16 synthetic offscreen screenshots, using isolated application data and disabled hotkeys, credentials and microphone enumeration.
- General and Writing settings were rendered at 125% and 150% with synthetic profiles. New language descriptions fit; long prompts remain internally scrollable; the Save footer stays visible.
- Capsule screenshots include 156 px minimum width, all operation labels, 0/50/100% milestones, Demo and the result transition endpoint.

Current native physical hotkey, focus, microphone and multi-screen behavior was not revalidated by these offscreen checks. Daily source startup uses **Start-MurMur.cmd** in the active local directory. If a previous instance is running, exit through **Quit MurMur** in the tray before restarting.
