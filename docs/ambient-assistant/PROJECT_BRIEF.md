# Ambient Personal Assistant

## Project vision

Create a private, consent-aware assistant that can accompany the user throughout the day, listen during explicitly activated conversations, retain useful context, surface reminders and action items, and eventually understand user-initiated camera input.

The assistant should feel continuous and personal while keeping the user in control of when microphones, cameras, memory, and external actions are active.

## Core outcomes

- Natural, low-latency voice conversation through a phone, computer, earbuds, or wearable.
- Optional conversation capture with transcription, speaker separation, summaries, decisions, and follow-up items.
- Searchable, editable long-term memory for people, projects, preferences, winery operations, product notes, and commitments.
- Commands such as “remember that,” “remind me,” “add that to the winery notes,” and “forget the last five minutes.”
- Approved integrations for calendar, reminders, email drafts, files, contacts, and business systems.
- Later camera assistance for equipment, labels, documents, gauges, vineyard conditions, and other intentionally shared scenes.

## Existing-product landscape

No single current product appears to combine ambient capture, strong conversational reasoning, durable personalized memory, broad integrations, and camera awareness.

| Product | Strength | Main gap for this project |
| --- | --- | --- |
| Bee | Ambient wearable capture, summaries, reminders, and personal patterns | No camera and less customizable than a purpose-built assistant |
| Plaud NotePin | Long-duration recording, speaker-labeled transcription, summaries, and searchable conversations | Primarily an AI recorder rather than an interactive personal assistant |
| ChatGPT Voice | Natural conversation, reasoning, memory, and research | Not intended to catalogue an entire day; video capability depends on voice mode and active sharing |
| Gemini Live | Real-time conversational camera and screen assistance | Visual sessions are intentional rather than continuous life capture |
| Microsoft Copilot Vision | Voice plus camera/screen understanding grounded in Microsoft 365 | Visual context is session-bound and lacks long-term visual recall |
| AI smart glasses | Hands-free camera, audio, photos, and visual questions | Usually lack comprehensive searchable memory and custom workflows |

## Recommended product strategy

Start with software and commercially available hardware. Use a phone, earbuds, Apple Watch, or an existing capture wearable rather than manufacturing hardware in the first phase.

The custom application supplies the differentiated layer:

- A personal assistant profile and controllable memory.
- Knowledge tailored to Locklear Vineyard and Winery and the user’s other projects.
- A conversational interface rather than transcription alone.
- Integrations and confirmed actions.
- Strong privacy controls and visible capture status.

## Proposed MVP

### 1. Companion application

- Initial target: select iPhone, Android, or cross-platform.
- Large, unmistakable Start/Stop listening control.
- Persistent recording indicator and elapsed-session display.
- Quick “mark important” control.

### 2. Meeting and conversation mode

- Live or post-session transcription.
- Speaker labels where reliable.
- Summary, decisions, questions, promises, and action items.
- Review screen before anything becomes long-term memory.

### 3. Personal memory

- Separate stores for family/personal, winery, projects, and general preferences.
- User-visible source and date for each memory.
- Edit, correct, export, and delete controls.
- Raw audio discarded by default after processing; retained only by explicit choice.

### 4. Voice assistant

- Real-time spoken interaction.
- User-selectable activation: button, earbud gesture, or optional wake phrase.
- Ability to remain silent while listening and respond only when addressed.

### 5. Actions and integrations

- Create reminders and calendar drafts.
- Draft emails or messages.
- Save approved notes to project knowledge.
- Require confirmation before sending messages, changing records, or taking consequential actions.

## Phase two: visual assistance

- User starts a camera session explicitly.
- Analyze selected frames rather than storing continuous video by default.
- Support questions about labels, documents, machinery, wiring, gauges, vineyard conditions, and troubleshooting.
- Allow the user to save a selected image and associated explanation as project memory.
- Explore smart-glasses integration only after the phone-based camera workflow is useful and trusted.

## Privacy and safety requirements

- Never hide active microphone or camera capture.
- Provide visible and, when appropriate, audible participant notification.
- Make local/on-device wake detection and audio filtering the preferred design where practical.
- Upload only what is necessary for the selected feature.
- Default to short retention and user-approved memory.
- Provide instant Pause, Private Mode, and Forget Recent controls.
- Separate raw recordings from summaries and structured memories.
- Encrypt stored content and protect access with device authentication.
- Account for consent and recording laws based on participant location before field use.
- Maintain an audit trail showing what was captured, remembered, shared, or acted upon.

## Technical direction

- Mobile client with microphone, notification, background-session, and later camera permissions.
- Realtime voice connection using WebRTC.
- Trusted backend for API credentials, authentication, tools, and integrations.
- Transcription and conversation-processing pipeline.
- Structured memory database with semantic search, categories, timestamps, and provenance.
- Action layer with confirmation gates.
- Privacy layer handling consent state, retention, deletion, and redaction.

## Early prototype sequence

1. Voice conversation with Start/Stop controls.
2. Conversation transcription and summary.
3. Review-and-save memory workflow.
4. Search and ask questions across saved memories.
5. Reminders and calendar integration.
6. Winery-specific knowledge and commands.
7. User-initiated camera mode.
8. Wearable and smart-glasses experiments.

## Decisions needed

- Initial platform: iPhone, Android, or both.
- Primary first use: meetings, winery operations, personal memory, or an equal blend.
- Whether to test Bee or Plaud as an interim capture device.
- Preferred storage approach: cloud-first, local-first, or hybrid.
- Which integration should come first: calendar/reminders, email, winery notes, or contacts.
- Working name and assistant personality.

## Definition of a successful first prototype

The user can start a clearly indicated session, hold a normal conversation, receive an accurate summary and action list, approve selected memories, retrieve those memories later by voice, and create a reminder without exposing API credentials or silently retaining raw audio.

## Current status

- Concept captured.
- Existing product categories reviewed.
- MVP and phased direction outlined.
- Next step: choose the initial device platform and primary first-use workflow.
