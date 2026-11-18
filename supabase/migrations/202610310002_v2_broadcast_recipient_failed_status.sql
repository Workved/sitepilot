-- Milestone 1 (Phase 2): Widen broadcast_recipients.delivery_status CHECK
-- constraint to include 'failed' so provider send failures are recorded
-- accurately instead of pretending delivery succeeded.

alter table siteops_v2.broadcast_recipients
    drop constraint if exists ck_v2_broadcast_recipients_delivery_status;

alter table siteops_v2.broadcast_recipients
    add constraint ck_v2_broadcast_recipients_delivery_status
    check (delivery_status in ('pending', 'sent', 'skipped_no_contact', 'failed'));

