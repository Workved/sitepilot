-- Tasks added to a project after it started (or by a PM/Supervisor while it
-- is still a draft).
--
-- A running project's execution tasks were all copied from its locked
-- baseline (the original plan). A task added later is not part of that plan,
-- so it has no baseline_task row: baseline_task_id becomes nullable and
-- created_from_baseline = false marks it. The baseline itself is never
-- touched.
--
-- added_by / added_reason record who added a task and why, on both the
-- execution task and the draft project task.

alter table siteops_v2.tasks
  alter column baseline_task_id drop not null;

alter table siteops_v2.tasks
  add column if not exists added_by uuid references users(id) on delete set null,
  add column if not exists added_reason text;

alter table siteops_v2.tasks
  drop constraint if exists ck_v2_tasks_baseline_source;
alter table siteops_v2.tasks
  add constraint ck_v2_tasks_baseline_source check (
    (created_from_baseline and baseline_task_id is not null)
    or (not created_from_baseline and baseline_task_id is null)
  );

alter table siteops_v2.project_tasks
  add column if not exists added_by uuid references users(id) on delete set null;
