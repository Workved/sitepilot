"""Collection-level read models for the Projects split view.

IMPORTANT: this router must be registered BEFORE `projects_v2.router` in
app.main. Both live under `/api/v2/projects`, and projects_v2 defines
`GET /{project_id}` - FastAPI matches in registration order, so the
catch-all would otherwise swallow `/summaries` and `/attention` and reject
them as malformed UUIDs. `test_project_read_models_v2.py` pins this.

Access is per-actor, not Admin-only: a PM or Supervisor gets the same
shapes narrowed to the projects they are actually a member of, which is
what makes the list pane and the attention counter usable for them.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.auth import current_user
from app.database import get_db
from app.models import User
from app.schemas.project_read_models import AttentionItemOut, ProjectSummaryOut
from app.services.project_read_models import ProjectReadModelService

router = APIRouter(prefix="/api/v2/projects", tags=["v2-project-read-models"])


@router.get("/summaries", response_model=list[ProjectSummaryOut])
def project_summaries(actor: User = Depends(current_user), db: Session = Depends(get_db)):
    return ProjectReadModelService(db).summaries(actor)


@router.get("/attention", response_model=list[AttentionItemOut])
def project_attention(actor: User = Depends(current_user), db: Session = Depends(get_db)):
    return ProjectReadModelService(db).attention(actor)


@router.get("/timeline")
def portfolio_timeline(actor: User = Depends(current_user), db: Session = Depends(get_db)):
    """One row per visible project for the calendar's portfolio view: dates,
    progress, forecast finish, days late, health and approval markers. See
    app/services/portfolio_timeline.py."""
    from app.services.portfolio_timeline import PortfolioTimelineService

    return PortfolioTimelineService(db).rows(actor)
