# Chrome built-in AI: the reference to check our code against

**Read this before changing anything in the Ask panel** (`webapp/index.html`
AI section, `webapp/ai_tools.js`). It is a map of the official docs plus a
list of the places where our implementation and the documented API have
drifted apart. It is **documentation only** — nothing here has been applied
to the code.

Everything below was read from developer.chrome.com on **2026-09-10**. Version
numbers and API shapes move; treat the URLs as the authority and this file as
the index. The older, deeper write-up of *why* the tool loop is shaped the way
it is lives in [`research-web-ai-and-pyodide-query.md`](research-web-ai-and-pyodide-query.md)
(2026-08-26) — this file is the "verify against upstream" companion to it.

## The pages, and what each one settles

| Page | URL | What it settles |
|---|---|---|
| Prompt API | https://developer.chrome.com/docs/ai/prompt-api | The whole surface: `availability()`, `create()` options, session methods and properties |
| Get started | https://developer.chrome.com/docs/ai/get-started | The four availability states, and when user activation is required |
| Session management | https://developer.chrome.com/docs/ai/session-management | Context window, overflow, cloning, when to `destroy()`, stopping generation |
| Session compacting | https://developer.chrome.com/docs/ai/session-compacting | Summarise-and-restart for long conversations |
| Structured output | https://developer.chrome.com/docs/ai/structured-output-for-prompt-api | `responseConstraint` and the JSON Schema subset |
| Do's and don'ts | https://developer.chrome.com/docs/ai/built-in-ai-dos-donts | Warm-up, prompt design, memory, output handling, UX |
| Prompt API polyfill | https://developer.chrome.com/docs/ai/prompt-api-polyfill | `LanguageModel` on browsers that lack it (cloud or local backends) |
| Task API polyfill | https://developer.chrome.com/docs/ai/task-api-polyfill | How the task APIs are *built out of* the Prompt API — prompt templates and placeholders |
| Streaming / rendering | https://developer.chrome.com/docs/ai/streaming · https://developer.chrome.com/docs/ai/render-llm-responses | Streamed output and how to render it safely |
| Download UX | https://developer.chrome.com/docs/ai/inform-users-of-model-download | Telling the user about the one-time download |
| Model management | https://developer.chrome.com/docs/ai/understand-built-in-model-management | Storage and lifecycle of the model |
| Debug the model | https://developer.chrome.com/docs/ai/debug-built-in-model | Seeing the system prompts Chrome itself generates |
| APIs overview | https://developer.chrome.com/docs/ai/built-in-apis | Shipping status of every built-in AI API |

## API surface, as documented

```js
LanguageModel.availability(options?)   // same options you would pass to create()
LanguageModel.create(options?)
LanguageModel.params()                 // Extensions only: defaultTopK/maxTopK/defaultTemperature/maxTemperature
```

`create()` options: `initialPrompts` (`{role, content}[]`), `expectedInputs` /
`expectedOutputs` (`{type: "text"|"image"|"audio", languages}`; outputs are
text only), `signal`, `monitor` (for the `downloadprogress` event),
`temperature` / `topK` (**Extensions only**), `samplingMode` (web **origin
trial**, Chrome 148+: `most-predictable` … `most-creative`).

Session methods: `prompt(input, {signal, responseConstraint,
omitResponseConstraintInput})`, `promptStreaming(...)` (same options, returns a
`ReadableStream<string>`), `append(messages)`, `clone({signal})`, `destroy()`,
`measureContextUsage(options?)`.

Session properties: `contextUsage`, `contextWindow`, `samplingMode` (read-only,
origin trial), `temperature` / `topK` (read-only, Extensions).

**Availability is four states**, not two: `unavailable`, `downloadable`,
`downloading`, `available`. User activation (`navigator.userActivation.isActive`)
is required to call `create()` when the state is `downloadable` or `downloading`.

**Tool / function calling still does not exist** in this API as of this date —
the docs describe structured output only. Our emulated loop (constrained JSON
either `{"tool":"sql",...}` or `{"answer":...}`) remains the right shape.

### Requirements the diagnostics line should keep matching

Windows 10+, macOS 13+, Linux, ChromeOS 16389.0.0+ (Chromebook Plus only); not
Chrome on Android or iOS. 22 GB free storage, GPU with >4 GB VRAM *or* 16 GB RAM
with 4+ cores, unmetered network for the one-time download.

## Structured output

`responseConstraint` takes standard JSON Schema — object properties and types,
arrays with `maxItems`/`items`, string `pattern` regexes, `required`,
`additionalProperties`. Documented from Chrome 137.

```js
const result = await session.prompt(prompt_text, { responseConstraint: schema });
```

Tools worth knowing: the [JSON Schema Tester](https://googlechrome.github.io/samples/json-schema-tester/),
and `@types/dom-chromium-ai` for TypeScript.

Note: **`omitResponseConstraintInput` is listed on the Prompt API page but not
explained on the structured-output page.** We pass it (`ai_tools.js` schema is
sent once, not re-sent per turn); if behaviour ever looks wrong, that is an
under-documented corner worth testing rather than trusting.

## Session management and context

```js
const { contextWindow, contextUsage } = languageModel;
const contextWindowLeft = contextWindow - contextUsage;
```

* On overflow the browser drops the **oldest prompt/response pairs**, one at a
  time — but never `initialPrompts`, which is why system instructions and
  few-shot examples belong there.
* A `contextoverflow` event fires as an early warning.
* A hard failure raises **`QuotaExceededError`** carrying `requested` and
  `contextWindow`.
* `clone()` forks the session with its initial prompts and history intact —
  the documented way to avoid re-parsing a system prompt per task.
* Sessions cost memory: `destroy()` what you are done with; keeping **one empty
  session alive** keeps the model warm cheaply.
* Stopping generation with an `AbortController` is presented as a *quota*
  measure as well as a UX one — an abandoned answer still costs context.

### Session compacting (for long conversations)

Summarise each turn with the **Summarizer API**, destroy the session, and start
a new one with the summaries as `initialPrompts` — because `initialPrompts` are
never evicted, the compacted history stays anchored. Trigger on
`contextUsage`/`contextWindow` or on the `contextoverflow` event; no numeric
threshold is mandated.

```js
const summary = await summarizer.summarize(msg.content.trim(), {
  context: 'This is a chat conversation turn. Preserve its key meaning as concisely as possible.'
});
```

## Do's and don'ts that bear on our page

* **Warm early.** Create the session as soon as intent is clear, not on the
  "Generate" click. `initialPrompts` must be final before `create()`.
* **System instructions at create time**, never as the first `prompt()`.
* **Baseline session + `clone()` per task**; don't reuse one session across
  unrelated tasks, and don't `create()` repeatedly with the same instructions.
* **`destroy()` explicitly**; don't leave several large sessions alive.
* **Send only what is needed** — input size drives latency. No raw HTML, no
  unfiltered datasets.
* **Use `responseConstraint`**, don't ask for JSON in prose. But **do not put
  `maxLength` in the schema** — models compress into other languages or emoji
  to satisfy it. Truncate in CSS instead.
* **Treat all output as untrusted**: sanitise the whole combined output, never
  `innerHTML` per chunk.
* Stream long outputs, don't stream short ones; give visible progress; consider
  a 1–2 s artificial delay for near-instant answers.
* Offer undo / version history; cache results (normalised input key,
  conservative TTL) rather than re-running identical inferences.

## Polyfills

**`prompt-api-polyfill`** (npm) provides `window.LanguageModel` where Chrome
does not, backed by either a cloud provider (Gemini, OpenAI — API keys, cost,
data leaves the device) or a **local Transformers.js** backend (no cost, data
stays local, model download; no structured output on this backend).

```js
if (!('LanguageModel' in window)) {
  await import('prompt-api-polyfill');
}
```

**`built-in-ai-task-apis-polyfills`** (npm) does the same for Summarizer,
Writer, Rewriter, Translator and Language Detector, loading the Prompt API
polyfill underneath when `window.LanguageModel` is missing.

### Why the task-API page is worth reading even though we don't use those APIs

It shows **how Chrome builds a task API out of the Prompt API**: a lookup keyed
by `type|format|length` selects a parameterised system prompt, and the user
message is assembled from a template with placeholders —

```
CONTEXT: SHARED_CONTEXT INPUT_CONTEXT TEXT: INPUT_TEXT
```

collapsing to `` `TEXT: ${inputText}` `` when there is no context, with language
instructions swapped in ("The summary must be written in Japanese.") and the
context paragraph removed entirely when unused. That is the same problem our
`SYSTEM_TEMPLATE` + `{{domain}}` / `{{schema}}` substitution solves, done by
the people who wrote the model's own prompts — a good pattern to compare ours
against, and a good argument for keeping placeholders rather than baking the
schema in.

## Where our code and the docs differ

Nothing here is a bug report — these are the checks to make and the openings to
consider, next time this area is touched.

1. **Quota handling is a guess.** We recreate the clone when
   `contextUsage > contextWindow * 0.8` (`AI_QUOTA_FRACTION`). The documented
   mechanisms are the `contextoverflow` event and a `QuotaExceededError` that
   carries `requested` and `contextWindow`, plus `measureContextUsage()` to ask
   *before* sending. Either would be exact where our fraction is a guess.
2. **`measureContextUsage()` is unused.** A long tool result could be measured
   before it is sent rather than capped blindly at 50 rows / ~2000 chars.
3. **`append()` is unused.** The tool result could be appended while the user
   is still reading, giving the model a head start.
4. **Compacting.** PR #8's description already wants "a self-compacting tool
   call"; the documented answer is Summarizer + fresh session with summaries as
   `initialPrompts`. Worth measuring before writing our own.
5. **Sampling.** We set neither `temperature`/`topK` (Extensions only) nor
   `samplingMode` (origin trial). For a loop that must emit strict JSON,
   `most-predictable` is the obvious thing to try when it leaves the trial.
6. **Availability states.** We branch on `unavailable` and otherwise proceed;
   `downloadable` and `downloading` are distinct states with a **user-activation
   requirement** on `create()`. Our header-button gesture satisfies that today,
   but the diagnostics could say so explicitly using
   `navigator.userActivation.isActive`.
7. **Version numbers to re-check.** Our README and the `aiDiagnostics()` string
   say "stable in desktop Chrome 148+"; the current Prompt API page says the
   core API is Chrome 138+, with 148+ being the *sampling-parameters* origin
   trial and 137 structured output. Before repeating the 148 claim, re-read the
   page — the number we quote may be describing something narrower than the API.
8. **Streaming.** We use `prompt()`, not `promptStreaming()`. For the final
   prose answer the docs would have us stream; the JSON tool turns should stay
   non-streaming.
9. **Answer caching.** The docs recommend caching normalised inputs; we re-run
   every question, and our data is in IndexedDB already.
10. **The polyfill is a real answer to "no model here".** `prompt-api-polyfill`
    with the local Transformers.js backend would make the Ask panel work on
    Android and non-Chrome browsers without a native app — worth weighing
    against the ML-Kit route in issue #9 (bundle size and download versus a
    native dependency). No structured output on that backend, so the loop would
    need the prose-JSON fallback path we already have.
