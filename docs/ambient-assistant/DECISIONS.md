# Ambient Personal Assistant: Decisions

Confirmed 2026-09-25. These answer the "Decisions needed" section of [PROJECT_BRIEF.md](PROJECT_BRIEF.md).

| Decision | Choice | Reasoning |
| --- | --- | --- |
| Initial platform | iPhone first, built cross-platform so Android can follow | Fits Apple Watch and earbuds in the brief; one platform keeps the first prototype small. |
| Primary first use | Winery operations and meetings | Daily value, and "winery notes" gives memory a clear home. |
| Interim capture device | Test Plaud before Bee | Better long-duration, speaker-labeled capture; used for learning, not as the product. |
| Storage approach | Hybrid | Raw audio stays on the device and is discarded after processing; approved summaries and memories go to an encrypted backend for search. |
| First integration | Calendar and reminders | Part of the success definition and low risk. |
| Session history | Keep every session's transcript (text) and notes automatically for 90 days | Decided 2026-09-26. Recall shouldn't depend on remembering to save. Audio is never kept. A per-session "Don't keep this session" switch opts out; expired sessions are deleted automatically; anything worth keeping longer is saved as a memory. |
| Working name and personality | Open | Placeholder persona: a concise, trusted chief of staff who knows winemaking. |

## Implementation notes

- The backend lives in this repo's Flask app (`assistant/` blueprint), which keeps API credentials server-side.
- Voice uses the OpenAI Realtime API over WebRTC, matching the existing OpenAI setup. The browser receives only a short-lived client secret.
- Memories live in Render Postgres (`DATABASE_URL`). Memory text is encrypted with a key derived from `MEMORY_ENCRYPTION_KEY`; losing or changing that key makes saved memories unreadable, so keep a copy somewhere safe. Search embeddings are encrypted the same way and compared in the app after decrypting, which is fine up to several thousand memories; beyond that, move to pgvector.
- Sessions (History page at `/assistant/history`) are encrypted like memories and expire after `SESSION_RETENTION_DAYS` (default 90). The voice assistant can search them alongside memories and read a past conversation's transcript.
- Step 1 ships as a mobile web page (works in iPhone Safari) to test the voice loop before building a native app.

## Prototype progress

- [x] 1. Voice conversation with Start/Stop controls, visible listening status, elapsed time, and "mark important" (`/assistant/`). Verified live on iPhone Safari 2026-09-25.
- [x] 2. Conversation transcription and summary: live two-sided transcript, Quiet mode for meetings, notes on Stop with a review screen, and echo control on speakerphone (mic pauses while the assistant talks, Interrupt button, headphones option). Verified live on iPhone 2026-09-25. Speaker labels are only You/Assistant for now; others in the room appear as You.
- [x] 3. Review-and-save memory workflow: tick, edit and categorize notes on the review screen; Memories page at `/assistant/library` with filter, edit, delete, export; memory text encrypted in Render Postgres with an audit log. Verified live 2026-09-26.
- [ ] 4. Search and ask questions across saved memories: built (voice questions via a `search_memories` tool, meaning-based search box on the Memories page, encrypted embeddings with automatic backfill); awaiting live test.
- [ ] 5. Reminders and calendar integration
- [ ] 6. Winery-specific knowledge and commands
- [ ] 7. User-initiated camera mode
- [ ] 8. Wearable and smart-glasses experiments
