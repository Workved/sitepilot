-- Reference material added on a project (not the template): attached to a
-- draft project task while the project is being set up, or to a live task.
-- Template reference files stay where they are and are still read through
-- the template; these rows sit alongside them.
--
-- A draft-task row has project_task_id; at activation it also gets task_id
-- (the live task made from that draft task). A file added to a live task has
-- only task_id. The bytes live in file_objects, like every other upload.

create table if not exists siteops_v2.project_task_reference_files (
  id uuid primary key default gen_random_uuid(),
  project_id uuid not null references siteops_v2.projects(id) on delete cascade,
  project_task_id uuid references siteops_v2.project_tasks(id) on delete cascade,
  task_id uuid references siteops_v2.tasks(id) on delete restrict,
  file_id uuid not null references siteops_v2.file_objects(id) on delete restrict,
  description text,
  created_by uuid references users(id) on delete set null,
  created_at timestamptz not null default now(),
  constraint ck_v2_project_task_reference_files_owner check (project_task_id is not null or task_id is not null)
);

create index if not exists ix_v2_project_task_reference_files_task on siteops_v2.project_task_reference_files (task_id);
create index if not exists ix_v2_project_task_reference_files_project_task on siteops_v2.project_task_reference_files (project_task_id);
