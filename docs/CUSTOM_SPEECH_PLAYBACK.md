# Custom speech playback

The concierge supports optional server-side ElevenLabs speech. Configure these keys on the existing Render web service; keep their values outside GitHub:

- `ELEVENLABS_API_KEY`: restricted provider credential with Text to Speech access and an appropriate provider-side credit limit.
- `ELEVENLABS_VOICE_ID`: the owner's chosen voice identifier.
- `ELEVENLABS_MODEL_ID`: optional model identifier; defaults to `eleven_v4`.

No source recordings, generated private samples, account metadata or credentials belong in this repository.

## Behavior

When configured, `/ask` keeps its existing `response` and `wines` fields and adds a short-lived signed playback token. `/speech` accepts only those server-signed replies, up to 1,800 characters. It cannot read arbitrary visitor-supplied text. Tokens expire after 15 minutes and become invalid when the key or voice changes.

Speech runs only after a visitor presses the playback button. The audio is lowered by half a semitone using Rubber Band, preserving tempo. The imageio-ffmpeg wheel supplies the executable so the native Python deployment does not rely on system packages.

Provider responses and audio processing are bounded. A process permits one generation at a time, at most six new generations per minute, and retains at most 16 audio clips in memory for reuse. These limits apply per process and reset on restart; use the provider key's credit cap for an account-level budget. No files are written by playback. Browser responses use `Cache-Control: no-store`.

If custom speech fails, text stays visible; the app does not substitute a device voice. On phones that reject playback after an asynchronous download, a second tap plays the prepared audio. Before provider configuration, the existing device-voice option is explicitly labeled as such.

## Validation and release

- Python tests cover token forgery/expiry, changed configuration, request limits, provider failure, cache reuse, legacy `/ask` compatibility and real pitch/duration processing.
- Node tests cover custom playback, errors, second-tap phone playback and stale downloads after a new question.
- Keep the change reviewable in a feature branch until server credentials are configured and a live provider request can be verified.
- After deployment, verify terminal live status, `/health`, `/wines`, one recommendation and its generated audio, then browser playback on the published Hostinger embed.

API reference: https://elevenlabs.io/docs/api-reference/text-to-speech/convert
FFmpeg packaging: https://github.com/imageio/imageio-ffmpeg
