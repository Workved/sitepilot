-- Vendor status simplified to one thing: blacklisted or not.
--
-- Active / On hold / Inactive are gone. A vendor on the list is simply a
-- vendor, whether or not it is mapped to any project. The only status a
-- person can set is "blacklisted", which needs a reason.
--
-- `status` stays as the column the backend already gates on: 'active' now
-- only means "not blacklisted" and is never shown in the app. Existing
-- 'on_hold' / 'inactive' vendors become normal vendors (product decision).
-- Status changes made before this migration stay in the audit trail.
--
-- Blacklisting (VendorBlacklistService) ends the vendor's current project
-- mappings, task assignments and people-on-project rows (sub-vendors of a
-- blacklisted main vendor too), without messaging the vendor; history is
-- kept. Only Admin / Super Admin can remove a vendor from the blacklist.

update siteops_v2.vendors set status = 'active' where status <> 'active';

alter table siteops_v2.vendors
  add column if not exists blacklist_reason text,
  add column if not exists blacklisted_at timestamptz,
  add column if not exists blacklisted_by uuid references users(id) on delete set null;

alter table siteops_v2.vendors drop constraint if exists ck_v2_vendors_status;
alter table siteops_v2.vendors
  add constraint ck_v2_vendors_status check (status in ('active', 'blacklisted'));

alter table siteops_v2.vendors drop constraint if exists ck_v2_vendors_blacklist_reason;
alter table siteops_v2.vendors
  add constraint ck_v2_vendors_blacklist_reason
  check (status <> 'blacklisted' or (blacklist_reason is not null and btrim(blacklist_reason) <> ''));
