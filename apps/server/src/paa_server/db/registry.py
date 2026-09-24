"""Register every ORM table before schema inspection or migration."""
import paa_server.db.idempotency
import paa_server.modules.attachments.models
import paa_server.modules.auth.models
import paa_server.modules.conversations.models
import paa_server.modules.members.models
import paa_server.modules.messages.models
import paa_server.modules.model_services.models
import paa_server.modules.operations.models
import paa_server.modules.reports.models
import paa_server.modules.support.models
import paa_server.modules.voiceprints.models
import paa_server.modules.work.models
import paa_server.tasks.models

from .base import Base

metadata = Base.metadata
