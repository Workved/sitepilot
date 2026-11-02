-- WhatsApp is the primary messaging channel again. Users invited during the
-- Telegram rollout were defaulted to active_channel = 'telegram' even though
-- most never connected a Telegram chat, which left them unreachable on every
-- channel. Move everyone who has no linked Telegram chat back to WhatsApp;
-- people who actually connected Telegram keep it.

update public.employee_profiles
   set active_channel = 'whatsapp'
 where active_channel = 'telegram'
   and telegram_chat_id is null;

update siteops_v2.vendor_contacts
   set active_channel = 'whatsapp'
 where active_channel = 'telegram'
   and telegram_chat_id is null;

-- Vendor numbers are now validated as E.164 (+<country code><number>) on
-- write. Strip the formatting characters older rows were saved with so they
-- match inbound WhatsApp replies. Numbers missing a country code are left
-- as they are - they need correcting by hand in Vendor Hub.

update siteops_v2.vendors
   set phone = regexp_replace(phone, '[\s().-]', '', 'g')
 where phone ~ '[\s().-]';

update siteops_v2.vendors
   set whatsapp = regexp_replace(whatsapp, '[\s().-]', '', 'g')
 where whatsapp ~ '[\s().-]';

update siteops_v2.vendor_contacts
   set phone = regexp_replace(phone, '[\s().-]', '', 'g')
 where phone ~ '[\s().-]';

update siteops_v2.vendor_contacts
   set whatsapp = regexp_replace(whatsapp, '[\s().-]', '', 'g')
 where whatsapp ~ '[\s().-]';
