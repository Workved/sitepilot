-- Alembic creates these tables in `public`, which Supabase's Data API exposes
-- to anyone holding the publishable key. The original production project only
-- had RLS on them through a dashboard-level event trigger that a fresh project
-- doesn't have. No policies: the backend connects as the table owner, so only
-- the Data API loses access.
alter table public.access_request_events enable row level security;
alter table public.access_requests enable row level security;
alter table public.alembic_version enable row level security;
alter table public.employee_profiles enable row level security;
alter table public.role_module_permissions enable row level security;
alter table public.user_account_events enable row level security;
alter table public.users enable row level security;
