from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.database import SessionLocal
from app.routes import admin_visibility_v2, auth, broadcasts, channel_toggle, communication, dashboard, execution_tasks_v2, permissions, project_dashboard_v2, project_task_references_v2, project_read_models_v2, project_vendors_v2, projects_v2, reports_v2, telegram_connect_codes, telegram_webhook, templates_v2, users, vendors, dependencies_v2, whatsapp_webhook_v2
from app.seed import ensure_seed_data
from app.services.daily_task_prompts_scheduler import start_daily_task_prompts_scheduler, stop_daily_task_prompts_scheduler
from app.services.evidence_retention_scheduler import start_retention_scheduler, stop_retention_scheduler
from app.services.gate_reminder_scheduler import start_gate_reminder_scheduler, stop_gate_reminder_scheduler
from app.services.meeting_reminder_scheduler import start_meeting_reminder_scheduler, stop_meeting_reminder_scheduler
from app.services.outbox_scheduler import start_dispatcher, stop_dispatcher
from app.services.weekly_summary_scheduler import start_weekly_summary_scheduler, stop_weekly_summary_scheduler


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup, in the same order the old `@app.on_event("startup")` hooks
    # ran in (registration order == execution order for that decorator):
    # seed data first, then each background scheduler.
    with SessionLocal() as db:
        ensure_seed_data(db)
    start_dispatcher(app)
    start_retention_scheduler(app)
    start_daily_task_prompts_scheduler(app)
    start_gate_reminder_scheduler(app)
    start_weekly_summary_scheduler(app)
    start_meeting_reminder_scheduler(app)

    yield

    # Shutdown, in the same order the old `@app.on_event("shutdown")` hooks
    # ran in.
    await stop_dispatcher(app)
    await stop_retention_scheduler(app)
    await stop_daily_task_prompts_scheduler(app)
    await stop_gate_reminder_scheduler(app)
    await stop_weekly_summary_scheduler(app)
    await stop_meeting_reminder_scheduler(app)


def create_app() -> FastAPI:
    app = FastAPI(title="SiteOps API", lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    Path(settings.upload_dir).mkdir(parents=True, exist_ok=True)
    app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")

    app.include_router(dashboard.router)
    app.include_router(auth.router)
    app.include_router(users.router)
    app.include_router(vendors.router)
    app.include_router(communication.router)
    app.include_router(permissions.router)
    # Must precede projects_v2: both are mounted at /api/v2/projects, and
    # projects_v2's GET /{project_id} would otherwise match /summaries and
    # /attention first and reject them as invalid UUIDs.
    app.include_router(project_read_models_v2.router)
    app.include_router(projects_v2.router)
    app.include_router(execution_tasks_v2.router)
    app.include_router(project_task_references_v2.router)
    app.include_router(project_dashboard_v2.router)
    app.include_router(reports_v2.router)
    app.include_router(admin_visibility_v2.router)
    app.include_router(project_vendors_v2.router)
    app.include_router(project_vendors_v2.vendors_router)
    app.include_router(whatsapp_webhook_v2.router)
    app.include_router(telegram_webhook.router)
    app.include_router(telegram_connect_codes.router)
    app.include_router(channel_toggle.router)
    app.include_router(dependencies_v2.router)
    app.include_router(templates_v2.router)
    app.include_router(broadcasts.router)

    return app


app = create_app()
