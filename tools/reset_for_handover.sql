-- =============================================================================
-- SiteOps: reset the database for a fresh start (handover to admins).
--
-- DELETES, permanently:
--   * every project and everything inside it (tasks, plans, approvals, snags,
--     targets, team assignments, reports, activity history)
--   * every vendor, vendor contact, vendor history and feedback
--   * every template, trade/category and Communication message/broadcast
--   * every message log (WhatsApp deliveries, inbound replies, reminders)
--   * every user EXCEPT those with the Super Admin role, and their logins
--
-- KEEPS: Super Admin account(s) and their employee profile, and the schema
-- itself (tables, migrations) - the app keeps working and starts empty.
--
-- NOT covered by SQL: uploaded files. Supabase blocks deleting storage files
-- with SQL; empty the "evidence" bucket from Storage in the dashboard.
--
-- Run it in the Supabase SQL Editor for the right project, AFTER taking a
-- backup. It is one transaction: if anything fails, nothing is changed.
-- =============================================================================

begin;

do $$
declare
  keep_ids uuid[];
  keep_auth_ids uuid[];
  keep_emails text[];
  t record;
begin
  -- Who stays: every Super Admin.
  select array_agg(id), array_agg(supabase_user_id) filter (where supabase_user_id is not null), array_agg(lower(email))
    into keep_ids, keep_auth_ids, keep_emails
    from public.users where role = 'super_admin';

  if keep_ids is null or array_length(keep_ids, 1) = 0 then
    raise exception 'No Super Admin account found - refusing to run, or nobody could sign in afterwards.';
  end if;
  raise notice 'Keeping % Super Admin account(s): %', array_length(keep_ids, 1), array_to_string(keep_emails, ', ');

  -- 1. All SiteOps data tables (projects, tasks, vendors, templates,
  --    messages, history...) are emptied. CASCADE only reaches tables that
  --    point AT these, which are all in this same schema.
  for t in select schemaname, tablename from pg_tables where schemaname = 'siteops_v2' loop
    execute format('truncate table %I.%I restart identity cascade', t.schemaname, t.tablename);
  end loop;
  raise notice 'Emptied every siteops_v2 table.';

  -- 2. Access requests and permission settings (the permission table is not
  --    read by the app; menu access is decided in code).
  delete from public.access_request_events;
  delete from public.access_requests;
  delete from public.role_module_permissions;

  -- 3. People: everyone except the Super Admins. Their account history and
  --    employee profiles go with them (ON DELETE CASCADE).
  update public.users set created_by = null where id = any(keep_ids);
  delete from public.user_account_events where not (user_id = any(keep_ids));
  delete from public.users where not (id = any(keep_ids));
  raise notice 'Remaining app users: %', (select count(*) from public.users);

  -- 4. Logins: remove the sign-in accounts of everyone deleted above. A
  --    Super Admin is kept by login id AND by email, so a not-yet-linked
  --    Super Admin login is never removed.
  delete from auth.users
   where not (id = any(coalesce(keep_auth_ids, '{}')))
     and not (lower(email) = any(keep_emails));
  raise notice 'Remaining logins: %', (select count(*) from auth.users);
end $$;

-- Quick check before committing - every number except users/logins should be 0.
select 'projects' as what, count(*) from siteops_v2.projects
union all select 'tasks', count(*) from siteops_v2.tasks
union all select 'vendors', count(*) from siteops_v2.vendors
union all select 'templates', count(*) from siteops_v2.v2_templates
union all select 'audit events', count(*) from siteops_v2.audit_events
union all select 'files (metadata)', count(*) from siteops_v2.file_objects
union all select 'app users (Super Admins)', count(*) from public.users
union all select 'logins', count(*) from auth.users;

commit;
