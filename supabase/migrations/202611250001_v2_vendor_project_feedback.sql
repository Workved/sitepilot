-- Vendor feedback: how a vendor performed on a SiteOps project, recorded
-- once that work is over (the project is completed/archived, or the vendor
-- was removed from it). Shown on the vendor's Work history so anyone
-- choosing a vendor later can see how they did.
--
-- One review per person per vendor per project. Admins may review any
-- project; a PM or Site Supervisor only projects they were assigned to.
-- Those rules, and "only once the work is over", live in the API
-- (app/services/vendor_feedback.py) because they span several tables.
--
-- A low score always carries a reason: rating <= 2 or "would not rehire"
-- requires a comment (also enforced here so no client can skip it).
--
-- Additive only - safe to apply before the code that uses it is deployed.

create table if not exists siteops_v2.vendor_project_feedback (
  id uuid primary key default gen_random_uuid(),
  vendor_id uuid not null references siteops_v2.vendors(id) on delete cascade,
  project_id uuid not null references siteops_v2.projects(id) on delete cascade,
  author_user_id uuid references users(id) on delete set null,
  -- The author's standing when they wrote it: 'admin', 'super_admin',
  -- 'project_manager' or 'site_supervisor'. Kept so the label survives a
  -- later role change.
  author_role text not null,
  rating smallint not null,
  quality smallint,
  timeliness smallint,
  conduct smallint,
  would_rehire text not null,
  comment text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint ck_v2_vendor_feedback_rating check (rating between 1 and 5),
  constraint ck_v2_vendor_feedback_quality check (quality is null or quality between 1 and 5),
  constraint ck_v2_vendor_feedback_timeliness check (timeliness is null or timeliness between 1 and 5),
  constraint ck_v2_vendor_feedback_conduct check (conduct is null or conduct between 1 and 5),
  constraint ck_v2_vendor_feedback_rehire check (would_rehire in ('yes', 'conditional', 'no')),
  constraint ck_v2_vendor_feedback_reason check (
    (rating > 2 and would_rehire <> 'no') or (comment is not null and btrim(comment) <> '')
  ),
  constraint uq_v2_vendor_feedback_author unique (vendor_id, project_id, author_user_id)
);
create index if not exists ix_v2_vendor_feedback_vendor
  on siteops_v2.vendor_project_feedback(vendor_id);
create index if not exists ix_v2_vendor_feedback_project
  on siteops_v2.vendor_project_feedback(project_id);

alter table siteops_v2.vendor_project_feedback enable row level security;
revoke all on table siteops_v2.vendor_project_feedback from anon, authenticated;
