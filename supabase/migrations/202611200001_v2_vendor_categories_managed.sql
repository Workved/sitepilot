-- Vendor categories become an Admin-managed list.
--
-- A vendor category is also a template phase: a vendor can be given a task
-- only when one of its categories matches the task's phase. So this one list
-- now feeds both the vendor pickers and the template task form's phases.
--
-- active = false hides a category from pickers while vendors that already
-- have it keep it (a category in use is hidden, never deleted).
--
-- Seeds the 31 standard phases (the list the template form offered), so
-- every trade is there from the start. Existing categories are kept; names
-- are matched case-insensitively.

alter table siteops_v2.capability_categories
  add column if not exists active boolean not null default true,
  add column if not exists created_by uuid references users(id) on delete set null;

insert into siteops_v2.capability_categories (name)
select seed.name
from (values
  ('Mobilisation'),
  ('Coordination'),
  ('Survey'),
  ('Planning'),
  ('Design & Planning'),
  ('Shop Drawings'),
  ('Procurement'),
  ('Off-Site Production'),
  ('Dismantling'),
  ('Civil'),
  ('Partitions'),
  ('MEP First Fix'),
  ('Floor Base'),
  ('Ceiling'),
  ('Carpentry'),
  ('Doors & Glass'),
  ('MEP Second Fix'),
  ('Fire Second Fix'),
  ('Flooring'),
  ('Painting'),
  ('Furniture'),
  ('IT & ELV'),
  ('Security'),
  ('Testing'),
  ('Inspection'),
  ('Snagging'),
  ('Rectification'),
  ('Cleaning'),
  ('Documentation'),
  ('Handover'),
  ('Demobilisation')
) as seed(name)
where not exists (
  select 1 from siteops_v2.capability_categories existing
  where lower(btrim(existing.name)) = lower(seed.name)
);
