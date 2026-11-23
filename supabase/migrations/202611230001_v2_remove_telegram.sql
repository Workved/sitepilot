-- Remove the Telegram messaging channel. WhatsApp is the only channel.
--
-- Lives here rather than in Alembic on purpose: Alembic runs first and
-- 202611020001_v2_whatsapp_primary_channel.sql still reads
-- employee_profiles.telegram_chat_id, so the columns must outlive it.
--
-- Kept for history, deliberately:
--   * 'telegram' stays allowed in the source/channel CHECK constraints of
--     task_progress_updates, vendor_acknowledgements and audit_events, and
--     message_deliveries.channel keeps its 'telegram' rows, so records made
--     over Telegram remain readable.
--   * acknowledged_at on project memberships, project vendors and task
--     support assignments (only the Telegram Acknowledge button set them).

-- Deliveries that were still waiting to go out over Telegram (or failed
-- there) are given up rather than replayed over WhatsApp days later.
-- 'channel_removed' is a permanent failure code in message_dispatch.py, so
-- the dispatcher never retries these rows.
update siteops_v2.message_deliveries
   set status = 'failed',
       failure_code = 'channel_removed',
       failure_reason = 'The Telegram channel was removed before this message was delivered.'
 where channel = 'telegram'
   and status in ('queued', 'sending', 'failed');

-- Telegram-only tables.
drop table if exists siteops_v2.telegram_pending_inputs;
drop table if exists siteops_v2.telegram_connect_tokens;
drop table if exists siteops_v2.telegram_inbound_updates;

-- Per-person channel choice and linked Telegram chat. Dropping a column also
-- drops its unique index and the active_channel CHECK constraint.
alter table public.employee_profiles drop column if exists telegram_chat_id;
alter table public.employee_profiles drop column if exists active_channel;

alter table siteops_v2.vendor_contacts drop column if exists telegram_chat_id;
alter table siteops_v2.vendor_contacts drop column if exists active_channel;
