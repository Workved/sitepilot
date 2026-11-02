-- Milestone 1 (Phase 1): WhatsApp delivery-status callback tracking columns
-- on siteops_v2.message_deliveries.

alter table siteops_v2.message_deliveries
    add column if not exists delivered_at timestamptz,
    add column if not exists read_at timestamptz,
    add column if not exists failed_at timestamptz,
    add column if not exists error_details jsonb;

