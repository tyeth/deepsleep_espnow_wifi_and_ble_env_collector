# Android model retention test, 2026-10-22

Result: **baseline FAIL; persistence fix PASS on the same Android emulator**. The original failure evidence below is preserved. The fix and offline restart/inference results follow it. This does not establish physical-phone compatibility or prevent storage eviction.

## Environment

- Official Android 36 Google APIs x86_64 system image, revision 7; Pixel 6 hardware profile, 4 GiB RAM, four cores, 8 GiB data partition.
- Preinstalled Chrome 133.0.6943.137. This is an emulator result, not physical-phone validation or a claim about all Chrome versions.
- Collector assets from `eff562bd0d46a0491156c26e064c7058a2083b98`, served at the secure-context loopback origin `http://127.0.0.1:8974` with the v19 service worker.
- Prompt API polyfill 1.22.2, Transformers.js 4.3.0, `onnx-community/Qwen2.5-0.5B-Instruct`, WASM worker / q8. Native LanguageModel was absent and WebGPU returned no adapter.
- Model file: `onnx/model_quantized.onnx`, response Content-Length **512,096,557 bytes** (512 MB decimal / 488 MiB). Resolved model revision observed on the initial load: `22942cb7d7ba4cc81bb4673549ca4d4614469b5e`.

## Observations

1. Initial online load reached `local phone model ready`. A complete natural-language query over all 2,377 demo rows returned the correct maxima: bedroom 2,261 ppm and local 2,573 ppm. The portal reported 99.9 seconds and one SQL query. Renderer RSS was observed at 1,760,512 KiB; that is a snapshot, not peak memory or a phone performance estimate.
2. The initial load logged: `Unable to add response to browser cache: UnknownError: Failed to execute 'put' on 'Cache': Unexpected internal error.`
3. After inference, the origin used 109,203,971 bytes. Cache Storage retained scripts, tokenizer/configuration files and the WASM runtime, but no ONNX weight entry. OPFS was empty; only the application's IndexedDB database existed. Persistent storage was not granted. Android had 6.3 GiB free and the reported origin quota was 4,981,238,169 bytes. The exact cause of the cache-write error remains unresolved.
4. A page reload with Playwright's browser-context network set offline loaded the portal and demo data from storage. An uncached Hugging Face fetch failed, verifying the network restriction. After explicitly enabling the local model again, initialization failed with `TypeError: Failed to fetch`; the model-weight request reported `ERR_INTERNET_DISCONNECTED`.
5. Chrome was fully force-stopped and restarted without clearing browser data. The existing portal storage survived. Enabling the model again requested the weight URL, followed a 302 redirect, and received an HTTP 200 response with Content-Length 512,096,557. The separate metadata range probe returned 206. The model eventually became ready, but logged the same cache-write error. No ONNX weight entry existed afterwards; origin usage was only 112,659,992 bytes.
6. Repeating the offline reload after that second successful initialization again failed to initialize the model. Thus the observed retention failure reproduced across two successful online initializations and offline revisits, including a full browser restart between them.

The local-model opt-in is reset on page reload; this test explicitly re-enabled it each time. That is separate from retaining downloaded weights. The label remained at `downloading model: 0%` through initialization and does not distinguish transfer, cache write, and runtime initialization.

## Separate cache-lifecycle finding

The current service worker's activation handler deletes every cache except its own versioned `envhub-v19` cache. That also includes `transformers-cache` on a service-worker update. This is a separate code-inspection finding and is not an explanation for the initial Cache.put failure, which occurred during the first successful model initialization.

The baseline did not support a one-time-download claim; the repaired implementation was subsequently tested as described below. The staged DUT assets remain unchanged; the active hardware soaks were not interrupted for this test.


## Persistence fix and actual Android validation, 12:50 UTC

`prompt_backend.js` now supplies a Transformers custom cache. Small configuration, tokenizer and runtime files retain their existing Cache Storage path. ONNX weights use the origin-private file system, keyed by the complete model URL, with writes bounded to 4 MiB. A replacement is published only after a complete response and successful atomic close. A partial/failed download never replaces a previously saved file. Browsers without the necessary file-storage API keep the existing browser-cache fallback.

The v20 service worker removes only older `envhub-vN` app-shell caches, preserving model/runtime caches owned by their loaders. Updating the actual emulator from v19 to v20 retained the existing six Transformers cache entries. The Android test then established:

- A fresh online initialization saved a **512,096,557-byte** weight file in `envhub-models-v1` and reached ready without the previous Cache.put warning. Total origin usage was 594,365,331 bytes, including 512,097,019 bytes of file storage.
- With Playwright's browser-context network disabled, a page reload and explicit local-model opt-in reached ready. An uncached external fetch failed independently.
- Android Wi-Fi and mobile data were then disabled, Chrome was fully force-stopped, and the same profile was reopened. `navigator.onLine` was false and an uncached external fetch failed. Saved weights again initialized successfully. The portal was served via the local ADB-forwarded origin; the model host was unreachable.
- A complete offline question-to-SQL-to-answer flow over the 2,377 demo rows returned bedroom **2,261 ppm** and local **2,573 ppm**, with **99.6 seconds / one query** reported. Resource entries contained no model-weight URL; the only Hugging Face request was the deliberately failing connectivity probe.
- Six storage/cache lifecycle tests cover bounded writes and a fresh cache instance, truncated downloads, failed writes and commits preserving old content, partial/empty responses, previous Cache Storage entries, revision separation, unavailable storage, and service-worker cache ownership. Existing 11 browser-AI tests, two native cancellation tests and 13 SQL test groups also pass.

The tested weight filename is `5aefcc105338ab75ffba9fa2231bcde7028e56b13ca51b8caafc90fee197f626.onnx`. No model download or data clearing occurred between the successful online write and the offline checks. The first-load failure and before/after conditions remain distinct. Browser data clearing or storage eviction can still require another download, and this result is specific to the tested Android/Chrome image. The progress label can still say downloading while a saved model initializes; it is not evidence of network transfer.

The implementation uses the documented [Transformers custom cache interface](https://huggingface.co/docs/transformers.js/api/env) and the file API's [publish-on-close behavior](https://developer.mozilla.org/en-US/docs/Web/API/FileSystemFileHandle/createWritable).

## AICore check

On the fully booted emulator, `pm list packages aicore` returned no package; Google Play services was present as a positive control. The actual image model is `sdk_gphone64_x86_64`, regardless of the Pixel 6 hardware profile. AICore/Gemini Nano has not been set up or validated here.

The linked [ML Kit Prompt API setup](https://developers.google.com/ml-kit/genai/prompt/android/get-started) is a native Android integration, with model availability checked through its native SDK. Google's [supported-device list](https://developers.google.com/ml-kit/genai#prompt-api-device-support) does not list this emulator. Separately, [Chrome's web Prompt API requirements](https://developer.chrome.com/docs/ai/prompt-api#review_the_hardware_requirements) still exclude Android. Installing an AICore APK alone would therefore not establish a working web LanguageModel API. The successful tests above used the separate Qwen JavaScript polyfill, not AICore.

## Emulator restart and loading-label follow-up, 14:08 UTC

After shutting down and restarting the same emulator, the original `http://127.0.0.1:8974` origin still held the complete 512,096,557-byte OPFS model. An initial visit to `http://localhost:8974` appeared empty because it is a different browser-storage origin; no data was cleared or model downloaded during this check. Keep the hostname and port identical when comparing revisits.

With the updated portal page and Android Wi-Fi/mobile data disabled, enabling the saved model displayed `loading local model...`, an `ai: loading` chip, and indeterminate progress, then reached `local phone model ready`. `navigator.onLine` was false and resource entries contained no ONNX request. The loading message no longer implies a download while saved weights initialize. Native Prompt API download progress retains its existing determinate behavior. The progress control's accessible label is now `AI model loading`.

All 19 existing browser-AI, model-cache and native-cancellation tests pass. The app-shell version is v21. This follow-up verifies saved-model initialization after emulator restart and page update; the earlier offline inference result remains the end-to-end answer evidence. No DUT portal was updated during the active hardware soaks.
