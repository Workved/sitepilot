-- Vendor work history: past projects a vendor did before (or outside)
-- SiteOps, entered by hand from the vendor's profile in Vendor Hub.
--
-- Projects the vendor worked on INSIDE SiteOps are not copied here - they
-- are read live from siteops_v2.project_vendors (ended mappings), so this
-- table only holds what the system could not otherwise know.
--
-- Months are stored as the first day of the month (`date`); the UI collects
-- month + year only. `category_id` reuses the capability vocabulary so a
-- past job can be tagged with the same trade the vendor is matched on; it is
-- optional and survives a category being removed (set null).
--
-- Additive only. Deleting a vendor deletes its history with it.

create table if not exists siteops_v2.vendor_past_projects (
  id uuid primary key default gen_random_uuid(),
  vendor_id uuid not null references siteops_v2.vendors(id) on delete cascade,
  project_name text not null,
  client_name text,
  location text,
  category_id uuid references siteops_v2.capability_categories(id) on delete set null,
  work_description text,
  start_month date,
  end_month date,
  approx_value numeric(14, 2),
  notes text,
  created_by uuid references users(id) on delete set null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint ck_v2_vendor_past_projects_name check (btrim(project_name) <> ''),
  constraint ck_v2_vendor_past_projects_months check (start_month is null or end_month is null or end_month >= start_month),
  constraint ck_v2_vendor_past_projects_value check (approx_value is null or approx_value >= 0)
);
create index if not exists ix_v2_vendor_past_projects_vendor
  on siteops_v2.vendor_past_projects(vendor_id);

alter table siteops_v2.vendor_past_projects enable row level security;
revoke all on table siteops_v2.vendor_past_projects from anon, authenticated;
