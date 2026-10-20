# Charlie custom voice — October 20, 2026

## Goal
Replace device-dependent browser speech with a reviewed custom voice for Charlie. Keep the existing microphone input, text recommendations and customer shopping experience working.

## Preparation status
Four supplied recordings have been prepared privately as individual source candidates, with leading/trailing silence trimmed and modest volume adjustment. Originals are unchanged. The clips have not been uploaded to a voice provider and no voice clone has been created. Source audio, spoken personal details, credentials and private account data must not be committed to this public repository.

## Required next step
Set up an owner-controlled voice-provider account. ElevenLabs Instant Voice Cloning is a candidate; review its current requirements before using it. Create a test voice using the best consistent single-speaker source recordings, then have the owner evaluate recognizability before enabling it publicly. Provider account and voice ID are not yet available to this workflow.

## App integration
- Keep the provider API key server-side in Render, outside source control and HTML.
- Store the selected voice ID as service configuration.
- Add bounded server-side speech generation for concierge replies and stream audio to the existing explicit playback control.
- Avoid an unrestricted public text-to-speech proxy: limit payload size, request frequency and cost exposure.
- Keep text available on speech errors. Make fallback behavior explicit; do not label a device voice as Charlie's custom voice.
- Validate provider errors and timeouts with mocked tests, then test an actual generated sample and playback on desktop/iPhone before rollout.

## Reference checked
https://elevenlabs.io/docs/eleven-creative/voices/voice-cloning/instant-voice-cloning

The provider recommends roughly 1–2 minutes of consistent clear speech, but describes successful tests with shorter samples. These brief voicemail sources require a prototype and owner likeness review; fidelity is not established.
