# Locklear Winery AI Concierge

## Objective
Extend the existing Wine Concierge application into a conversational winery host called Dad. Preserve the real portrait and recognizable voice of Dad, with his permission, and use verified winery information.

## Source of truth
Repository: d-locklear/wine-concierge. Test changes before production deployment. Obtain approval before changing the live website or app.

## Priorities
1. Avatar: use the exact original uploaded portrait, not AI-generated replacements. Obtain permission to use the image. Add the source image to app assets and wire it into the UI.
2. Voice: assess four supplied voicemails and one video for clarity and usable speech. Confirm consent and provider requirements before cloning or publishing. Test recognition with family.
3. Portfolio: verify current available wines and ciders against latest owner-confirmed list; do not infer availability from old records.
4. Conversation: enable spoken interaction, accurate wine recommendations, winery history and customer questions; make it clear Dad is a virtual host.
5. Deployment: inspect existing application, configuration and Render setup; develop in a non-production branch and test before merging or deploying.

## Immediate next steps
- Inspect repository structure and current avatar implementation.
- Add the exact uploaded portrait to the app assets; do not regenerate Dad's face.
- Inventory and assess audio sources for authorized voice replication.
- Validate portfolio data and build a test conversation flow.

## Status
Portrait implementation prepared on `feature/dad-original-portrait` for review. The
customer pages at `/` and `/embed` display the exact original uploaded JPEG as
`static/images/dad-original.jpeg`, without regeneration, recompression or cropping.
Both supplied portrait files were byte-identical. The image is 1254 × 1254 pixels;
its SHA-256 is `977be9e3b0d53b8a42d46f149ecff7e24e5808948a4fe1f1dd7c2e012d7c5fb0`.
The page explicitly identifies Dad as a virtual AI host and describes the current
interaction as text. The `/ask` contract and catalog behavior are unchanged.

Audio inventory: four supplied voicemails contain about 52.9 seconds total, and
the supplied video is about 24.3 seconds long with an audio stream. One voicemail
uses an 8 kHz mono stream; three use 44.1 kHz stereo; the video uses 44.1 kHz mono.
These are container/codec observations, not measurements of usable speech,
speaker identity, clarity or suitability for cloning. Source audio/video remains
private and is not committed to this public repository.

The customer concierge has no voice implementation. The separate authenticated
owner assistant has realtime speech using a configured provider voice; it must
not be reused as Dad or expose private memory tools to guests. A recognizable
Dad voice still requires listening and speaker review, confirmed consent,
provider selection and requirements, and family recognition testing. No clone,
speaking avatar, live deployment or Hostinger website change has been made.

## Guest dictation follow-up

The owner approved the portrait design preview on October 18, 2026. Optional
browser speech recognition now fills the existing question field for review;
it never automatically submits a recording or opens the private owner assistant.
Recognition requires a supported secure browser and explicit microphone action.
Denied access, missing microphones and network failures retain text entry.
The browser may use its speech service online, which is disclosed before use.
Microphone activity stops when the page is hidden or a question is submitted.
Replies remain text: no substitute voice is presented as Dad. Physical-device
microphone and embedded Hostinger permissions still require verification before
deployment. This work does not merge or deploy the branch.

Validation: `node --test tests/concierge_voice.test.cjs` passed all seven
behavior checks (dictation, limits, denial, cancellation, stale events, startup
failure and `/ask` submission). The focused Python portrait/shop suite passed
all sixteen checks. JavaScript syntax and `git diff --check` passed. Real-browser
permission prompts and physical microphone capture are not covered by these
automated checks.

## Public host name

Owner requested Charlie as the guest-facing host name on October 18, 2026.
The welcome heading, introduction, image alternative text, page title and AI
disclosure use Charlie. The original portrait asset and its filename are unchanged.
The design preview uses the same name.

## Hosted phone-test preview

`preview_app.py` serves the review-branch customer UI with a test-preview label.
It forwards validated guest questions and public catalog reads only to the
existing public concierge. No production secrets, database access, owner
assistant modules or private memory endpoints are included in this server.
Use `pip install -r requirements-preview.txt` and
`gunicorn preview_app:app --bind 0.0.0.0:$PORT --timeout 90` for the separate
Render free web service. The main branch and existing service remain unchanged.
Questions submitted in this preview use the existing recommendation backend.
Physical phone microphone testing and recognizable voice remain pending.

## iPhone microphone correction, October 18

Owner phone test: typed questions responded, but dictation requested mic access
without capturing words. Preview logs showed the phone loaded the page, with
no guest `/ask` request during the failed dictation. A likely client-side cause
was the visibility-change listener aborting recognition during iOS permission
UI; that listener was removed. Interim text is now shown without focusing the
textarea, and a hung recognition session resets after 20 seconds with a
Safari/keyboard-dictation fallback. This is a code correction and hypothesis,
not proof of physical iPhone recognition. WebKit documents that SpeechRecognition
behavior may differ in embedded app browsers; test the updated preview on
Safari proper before considering a different transcription path.
