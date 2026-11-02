# WhatsApp Notifications Rollout Checklist

Work top to bottom. Each checkpoint has a clear "done when" before moving on.
Owner: **You** = Meta/Render/Supabase/GitHub dashboards, **Code** = changes in this repo.

## Checkpoint 1 - Save the code fixes (Code) - DONE

- [x] Commit the WhatsApp-first fixes on a branch (Telegram default, empty template fields, retry cap, auto-reply removed, Super Admin profile, vendor phone format). Branch `fix/whatsapp-notifications`.
- [x] Run the frontend tests once (`npm install` + `npm test` in `frontend/`). 514 frontend + 1604 backend tests pass.

Done when: fixes are committed and all backend + frontend tests pass.

## Checkpoint 2 - Design the starter templates (Code)

- [ ] Pick the 6-8 most important notifications to launch with.
- [ ] Change those messages to send readable fields (task code, task name, project name, status, due date) instead of internal IDs.
- [ ] Write the exact Meta template spec for each: name, category (Utility), language (English `en`), body text with `{{1}}`, `{{2}}` ...

Done when: a template spec list exists and the code sends exactly those fields, with tests.

## Checkpoint 3 - Create templates in the Meta test account (You)

- [ ] Create each starter template in WhatsApp Manager -> Message templates, language **English** (not English US).
- [ ] Wait for status **Active/Approved**.
- [ ] Add your test phone numbers (max 5) under API Setup -> "To".

Done when: every starter template shows Active and test numbers are verified.

## Checkpoint 4 - End-to-end test locally (You + Code)

- [ ] Put your Meta test credentials in the local `.env` (`WHATSAPP_ACCESS_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID`).
- [ ] Run the connectivity script (`hello_world`) to a test number.
- [ ] Trigger each starter notification in the local app and confirm it arrives on the phone.

Done when: every starter notification arrives on a test phone from the local app.

## Checkpoint 5 - Take ownership of the infrastructure (You)

- [ ] GitHub: confirm push access to `Workved/sitepilot`, or create your own repo and push.
- [ ] Supabase: get owner access to the project (or a transferred project).
- [ ] Rotate the secrets shared by the previous developer.
- [ ] Take a database backup.

Done when: you control the repo, the database, and fresh secrets.

## Checkpoint 6 - Database migrations (You + Code)

- [ ] Run on production Supabase, in order: `202610310001`, `202610310002`, `202611020001`.
- [ ] List vendors/contacts whose numbers still lack a country code and fix them in Vendor Hub.

Done when: migrations applied and every vendor number starts with `+`.

## Checkpoint 7 - Deploy the backend on your Render (You)

- [ ] New Render web service from your repo (uses `render.yaml`).
- [ ] Fill all env vars, WhatsApp ones from your Meta app (permanent System User token, Phone Number ID, App Secret, a verify token).
- [ ] Add a keep-alive ping to `/api/health` every ~10 minutes (UptimeRobot / cron-job.org).
- [ ] Check startup logs: no "WhatsApp messages are NOT being sent" warning.

Done when: `/api/health` responds on your Render URL and logs are clean.

## Checkpoint 8 - Connect Meta webhook (You)

- [ ] Meta app -> WhatsApp -> Configuration: callback `https://<your-render-url>/api/v2/whatsapp/inbound` + your verify token.
- [ ] Subscribe to the `messages` field.

Done when: Meta verifies the webhook and sent messages move to delivered/read in the database.

## Checkpoint 9 - Switch the frontend and retire the old backend (You)

- [ ] Vercel: set `VITE_API_BASE` to your Render URL and redeploy (move the Vercel project to your account if needed).
- [ ] Ask the previous developer to suspend their Render service (prevents duplicate messages).

Done when: the live app talks only to your backend.

## Checkpoint 10 - Production test with test numbers (You + Code)

- [ ] Clear the old outbox backlog before the first real send (`python -m app.scripts.clear_whatsapp_backlog`).
- [ ] Run a real workflow in production (assign task, change status, approve, broadcast) to test numbers.

Done when: each starter notification arrives from production.

## Checkpoint 11 - Go live with a real WhatsApp Business account (You)

- [ ] Create the real WhatsApp Business account with your business number; complete business verification.
- [ ] Recreate the starter templates there and wait for approval.
- [ ] Switch Render env vars to the real account's token and Phone Number ID; update the webhook if the app changes.

Done when: real staff and vendors receive notifications.

## Checkpoint 12 - Remaining notifications (Code + You)

- [ ] Design and add templates for the rest of the 36 events, in small batches.
- [ ] Replace the 16 `TBD_` placeholders with real templates.

Done when: no `TBD_` templates remain and every event has an approved template.
