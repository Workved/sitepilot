from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg://siteops:siteops_password@localhost:5435/siteops"
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"
    upload_dir: str = "uploads/task-proofs"
    supabase_url: str = ""
    supabase_publishable_key: str = ""
    supabase_secret_key: str = ""
    # Phase 2 U6: HMAC secret used to verify `X-Hub-Signature-256` on
    # inbound WhatsApp webhook deliveries (see
    # backend/app/routes/whatsapp_webhook_v2.py). Sourced from
    # environment/`.env` only, mirroring `supabase_secret_key`'s pattern -
    # never hardcoded. Empty by default: with no configured secret, no
    # valid signature can ever be computed, so the route safely rejects
    # every inbound request until an operator configures this.
    whatsapp_webhook_secret: str = ""
    # Meta's webhook subscription handshake (GET .../inbound with
    # ?hub.mode=subscribe&hub.verify_token=...&hub.challenge=...), required
    # once when registering the callback URL in Meta for Developers. Distinct
    # from `whatsapp_webhook_secret` (which signs delivery payloads) - this
    # is a separate arbitrary string chosen by the operator and entered into
    # both Meta's dashboard and this setting. Empty by default: with no
    # configured token, the handshake can never match and always fails
    # closed (403), matching `whatsapp_webhook_secret`'s same fail-closed
    # default.
    whatsapp_webhook_verify_token: str = ""
    # Real Meta WhatsApp Cloud API credentials (see
    # backend/app/services/whatsapp_provider.py). Sourced from
    # environment/`.env` only, mirroring `supabase_secret_key`'s pattern -
    # never hardcoded. Empty by default: with no token/phone-number-id
    # configured, `MetaCloudApiAdapter.send` fails fast with
    # failure_code='not_configured' rather than attempting a doomed call.
    whatsapp_access_token: str = ""
    whatsapp_phone_number_id: str = ""
    whatsapp_api_version: str = "v21.0"
    # Which service sends WhatsApp templates: "meta" (Graph API, above) or
    # "doubletick" (see `DoubleTickAdapter` in whatsapp_provider.py), for a
    # number onboarded through DoubleTick, where Meta refuses sends from any
    # other app. Empty means "meta", so existing deployments are unchanged.
    whatsapp_provider: str = ""
    # DoubleTick public API key (DoubleTick -> Settings -> Developer API) and
    # the connected sender number in international format ("+91...").
    # Sourced from environment/`.env` only, never hardcoded.
    doubletick_api_key: str = ""
    doubletick_from_number: str = ""
    # U3 (R18): the outbox dispatcher. `OutboxService.emit` has been writing
    # pending events since Phase 2 and nothing has ever drained them, so
    # every notification the system decided to send is still sitting in the
    # table. These two settings are sourced from environment/`.env` like
    # every other setting here.
    #
    # Enabled by default because a queue nobody drains is the bug this unit
    # exists to fix; the switch is for an operator who needs to stop delivery
    # without redeploying, and for any process that must not dispatch (a
    # migration run, a second replica, a test harness).
    #
    # The wired adapter is still the sandbox one per KTD7 - this unit changes
    # only whether anything drains the outbox, never what is emitted or where
    # it goes. Turning on a REAL provider is a separate, deliberate decision.
    outbox_dispatch_enabled: bool = True
    # 30s: this is a notification queue, not a transaction path. Polling
    # faster costs a query per interval for no benefit anyone can perceive.
    outbox_dispatch_interval_seconds: float = 30.0
    # Evidence retention sweep (app.services.evidence_retention): deletes
    # evidence bytes N months after a project's actual completion
    # (V2Project.completed_at), so multi-project evidence storage does not
    # grow forever. Enabled by default for the same reason as
    # outbox_dispatch_enabled above - a policy nobody runs is not a policy.
    # The switch exists for an operator who needs to pause deletion without
    # redeploying (e.g. while validating the sweep against real data).
    evidence_retention_enabled: bool = True
    evidence_retention_months: int = 6
    # Once a day: this is housekeeping against a 6-month window, not a
    # time-sensitive path - polling more often than daily costs a query for
    # no one who could ever perceive the difference.
    evidence_retention_interval_seconds: float = 86400.0
    # Plan Phase 6 (second half): the merged daily task-prompt + task-side
    # escalation sweep (`daily_task_prompts_scheduler.py`). Enabled by
    # default for the same reason as the two schedulers above - a prompt
    # cadence nobody runs is not a cadence. The switch exists for an
    # operator who needs to pause it without redeploying.
    daily_task_prompts_enabled: bool = True
    # Every 5 minutes, so each Asia/Kolkata reminder (09:00, 13:30, 18:30,
    # ...; see `task_reminders.py`) goes out within 5 minutes of its time.
    # The reminder log makes extra passes harmless: each reminder is sent
    # at most once per task per IST day.
    daily_task_prompts_interval_seconds: float = 300.0
    # Plan Phase 6 (second half): the gate due-date reminder + approval-side
    # escalation sweep (`gate_reminder_scheduler.py`). Same enabled-by-
    # default rationale as above.
    gate_reminder_enabled: bool = True
    gate_reminder_interval_seconds: float = 3600.0
    # Plan Phase 8: the automated weekly report-summary pass
    # (`weekly_summary_scheduler.py`). Same enabled-by-default rationale as
    # the schedulers above.
    weekly_summary_enabled: bool = True
    # Hourly, same as `daily_task_prompts_interval_seconds`/
    # `gate_reminder_interval_seconds`: the real cadence gate is the 7-day
    # check inside the pass itself (against the latest weekly
    # `ReportSnapshot.period_start`), not this tick interval - a frequent
    # tick with an internal idempotency/cadence check doing the real
    # gating is the pattern every scheduler in this codebase already uses.
    weekly_summary_interval_seconds: float = 3600.0
    # Plan Phase 9: the automated meeting-reminder pass
    # (`meeting_reminder_scheduler.py`). Same enabled-by-default rationale as
    # the schedulers above.
    meeting_reminder_enabled: bool = True
    # 5 minutes, deliberately SHORTER than the other schedulers' hourly
    # default: a meeting reminder is time-sensitive to the actual clock in a
    # way the daily/weekly cadences aren't - someone scheduling a reminder
    # for "30 minutes before the meeting" needs better-than-hourly
    # granularity for that reminder to fire anywhere close to on time,
    # unlike a daily prompt or weekly report where being off by up to an
    # hour is invisible to anyone.
    meeting_reminder_interval_seconds: float = 300.0
    bootstrap_super_admin_email: str = ""
    bootstrap_super_admin_password: str = ""
    migration_temp_password: str = ""
    frontend_url: str = "http://localhost:3000"
    # Local-only "sign in as any local test account" shortcut (see
    # app/routes/auth.py's dev_login), for testing without real Google OAuth
    # credentials configured locally. Off by default; only docker-compose.yml
    # (local dev stack) sets this true - render.yaml (prod) never does, and
    # the route itself independently re-checks that supabase_url points at a
    # local host before doing anything, so a stray env var alone can't
    # expose it against a real deployment.
    local_dev_login_enabled: bool = False


settings = Settings()
