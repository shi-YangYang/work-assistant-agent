"""Register every ORM table before schema inspection or migration."""
import app.db.idempotency
import app.modules.attachments.models
import app.modules.auth.models
import app.modules.conversations.models
import app.modules.members.models
import app.modules.messages.models
import app.modules.model_services.models
import app.modules.operations.models
import app.modules.reports.models
import app.modules.support.models
import app.modules.voiceprints.models
import app.modules.work.models
import app.tasks.models

from .base import Base

metadata = Base.metadata
