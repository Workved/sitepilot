-- Snag list: the small things left on a running project ("touch up paint
-- near cabin 3"), kept as a quick checklist per project, separate from the
-- schedule - a snag never moves progress or dates.
--
-- Each snag can be tagged to one SiteOps user, who may be outside the
-- project: they can then see and close that snag (and only that snag) from
-- "Tagged to you". Who may add, edit, close and delete is enforced in the
-- API (app/services/snags.py) because it depends on project membership.
--
-- Attachments reuse siteops_v2.file_objects and the private evidence
-- storage, with the same type/size checks as task reference files.
--
-- Additive only - safe to apply before the code that uses it is deployed.

create table if not exists siteops_v2.project_snags (
  id uuid primary key default gen_random_uuid(),
  project_id uuid not null references siteops_v2.projects(id) on delete cascade,
  title text not null,
  area text,
  notes text,
  due_date date,
  urgent boolean not null default false,
  assignee_user_id uuid references users(id) on delete set null,
  status text not null default 'open',
  created_by uuid references users(id) on delete set null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  closed_at timestamptz,
  closed_by uuid references users(id) on delete set null,
  closing_note text,
  constraint ck_v2_project_snags_title check (btrim(title) <> ''),
  constraint ck_v2_project_snags_status check (status in ('open', 'done')),
  constraint ck_v2_project_snags_closed check ((status = 'done') = (closed_at is not null))
);
create index if not exists ix_v2_project_snags_project on siteops_v2.project_snags(project_id);
create index if not exists ix_v2_project_snags_assignee_open
  on siteops_v2.project_snags(assignee_user_id) where status = 'open';

create table if not exists siteops_v2.project_snag_files (
  id uuid primary key default gen_random_uuid(),
  snag_id uuid not null references siteops_v2.project_snags(id) on delete cascade,
  file_id uuid not null references siteops_v2.file_objects(id) on delete cascade,
  uploaded_by uuid references users(id) on delete set null,
  created_at timestamptz not null default now()
);
create index if not exists ix_v2_project_snag_files_snag on siteops_v2.project_snag_files(snag_id);

alter table siteops_v2.project_snags enable row level security;
alter table siteops_v2.project_snag_files enable row level security;
revoke all on table siteops_v2.project_snags from anon, authenticated;
revoke all on table siteops_v2.project_snag_files from anon, authenticated;
