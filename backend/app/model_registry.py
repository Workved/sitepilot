"""Central SQLAlchemy metadata registry for application and schema tests."""

from app import models as legacy_models  # noqa: F401
from app import project_models as project_models  # noqa: F401
from app import snag_models as snag_models  # noqa: F401
from app import target_models as target_models  # noqa: F401
from app import template_models as template_models  # noqa: F401

__all__ = ["legacy_models", "project_models", "snag_models", "target_models", "template_models"]
