-- Targets: commitment dates layered on top of the plan. The plan (and so
-- delay variance) never changes when a target is set.
--
--  * kind 'task'    - "finish this task by <date>". One active target per
--                     task; setting a new one marks the old one 'replaced',
--                     so the history of who promised what stays.
--  * kind 'project' - a standalone commitment ("Client walkthrough on 12 Dec"),
--                     optionally linked to several tasks (met when all are
--                     done by the date), or marked achieved by hand.
--
-- Who may set/change/clear is enforced in the API (app/services/targets.py).
-- Additive only - safe to apply before the code that uses it is deployed.

create table if not exists siteops_v2.project_targets (
  id uuid primary key default gen_random_uuid(),
  project_id uuid not null references siteops_v2.projects(id) on delete cascade,
  kind text not null,
  task_id uuid references siteops_v2.tasks(id) on delete cascade,
  title text,
  target_date date not null,
  note text,
  status text not null default 'active',
  achieved_at timestamptz,
  achieved_by uuid references users(id) on delete set null,
  created_by uuid references users(id) on delete set null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  ended_at timestamptz,
  ended_by uuid references users(id) on delete set null,
  constraint ck_v2_project_targets_kind check (kind in ('task', 'project')),
  constraint ck_v2_project_targets_status check (status in ('active', 'replaced', 'cleared')),
  constraint ck_v2_project_targets_shape check (
    (kind = 'task' and task_id is not null) or (kind = 'project' and task_id is null and title is not null and btrim(title) <> '')
  )
);
create index if not exists ix_v2_project_targets_project on siteops_v2.project_targets(project_id);
create unique index if not exists uq_v2_project_targets_active_task
  on siteops_v2.project_targets(task_id) where status = 'active' and task_id is not null;

create table if not exists siteops_v2.project_target_tasks (
  target_id uuid not null references siteops_v2.project_targets(id) on delete cascade,
  task_id uuid not null references siteops_v2.tasks(id) on delete cascade,
  primary key (target_id, task_id)
);

alter table siteops_v2.project_targets enable row level security;
alter table siteops_v2.project_target_tasks enable row level security;
revoke all on table siteops_v2.project_targets from anon, authenticated;
revoke all on table siteops_v2.project_target_tasks from anon, authenticated;
