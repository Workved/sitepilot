-- Vendor people on projects and tasks.
--
-- A vendor's contacts (the people under a main vendor or sub-vendor) were
-- linked only to their company, so there was no record of which person
-- works on which project, trade or task, and every task message went to the
-- vendor's primary contact.
--
-- 1. vendor_contact_projects: a contact attached to a project, optionally
--    for one trade category (one row per category; category_id null means
--    "all of this vendor's work on the project"). Soft removal via ends_at,
--    same pattern as project_vendors, so the history stays.
-- 2. task_vendor_assignments.contact_id: the point person for a task
--    delegated to a vendor. Must be a contact of that vendor (enforced in
--    TaskVendorAssignmentService). Task messages go to the point person and
--    the vendor's primary contact. Null = primary contact only (as before).
--
-- Additive only.

create table if not exists siteops_v2.vendor_contact_projects (
  id uuid primary key default gen_random_uuid(),
  contact_id uuid not null references siteops_v2.vendor_contacts(id) on delete cascade,
  project_id uuid not null references siteops_v2.projects(id) on delete restrict,
  category_id uuid references siteops_v2.capability_categories(id) on delete set null,
  note text,
  assigned_by uuid references users(id) on delete set null,
  created_at timestamptz not null default now(),
  ends_at timestamptz
);
create index if not exists ix_v2_vendor_contact_projects_contact
  on siteops_v2.vendor_contact_projects(contact_id);
create index if not exists ix_v2_vendor_contact_projects_project
  on siteops_v2.vendor_contact_projects(project_id);
-- One active row per contact/project/category ("all work" counted as its own slot).
create unique index if not exists uq_v2_vendor_contact_projects_active
  on siteops_v2.vendor_contact_projects(contact_id, project_id, coalesce(category_id, '00000000-0000-0000-0000-000000000000'::uuid))
  where ends_at is null;

alter table siteops_v2.vendor_contact_projects enable row level security;
revoke all on table siteops_v2.vendor_contact_projects from anon, authenticated;

alter table siteops_v2.task_vendor_assignments
  add column if not exists contact_id uuid references siteops_v2.vendor_contacts(id) on delete set null;
