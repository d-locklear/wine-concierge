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
Planning document created. No portrait asset, voice clone, deployment or live website update is implied by this document.
