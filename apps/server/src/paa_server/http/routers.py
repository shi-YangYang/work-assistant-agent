"""Compose public routes by business domain."""
from paa_server.http.health import router as health_router
from paa_server.modules.attachments.router import router as attachments_router
from paa_server.modules.auth.desktop_router import router as auth_desktop_router
from paa_server.modules.auth.dingtalk.router import router as auth_dingtalk_router
from paa_server.modules.auth.router import router as auth_router
from paa_server.modules.conversations.router import router as conversations_router
from paa_server.modules.members.router import router as members_router
from paa_server.modules.messages.router import router as messages_router
from paa_server.modules.model_services.router import router as model_services_router
from paa_server.modules.model_services.usage_router import router as model_services_usage_router
from paa_server.modules.operations.router import router as operations_router
from paa_server.modules.reports.obligations_router import router as reports_obligations_router
from paa_server.modules.reports.router import router as reports_router
from paa_server.modules.reports.rules_router import router as reports_rules_router
from paa_server.modules.support.router import router as support_router
from paa_server.modules.team.router import router as team_router
from paa_server.modules.team.source_router import router as team_source_router
from paa_server.modules.team.workspace_router import router as team_workspace_router
from paa_server.modules.voiceprints.router import router as voiceprints_router
from paa_server.modules.work.router import router as work_router
from paa_server.tasks.router import router as tasks_router



def register_routes(app):
    app.include_router(model_services_router)
    app.include_router(support_router)
    app.include_router(auth_dingtalk_router)
    app.include_router(auth_desktop_router)
    app.include_router(voiceprints_router)
    app.include_router(team_workspace_router)
    app.include_router(health_router)
    app.include_router(auth_router)
    app.include_router(members_router)
    app.include_router(attachments_router)
    app.include_router(messages_router)
    app.include_router(team_source_router)
    app.include_router(tasks_router)
    app.include_router(work_router)
    app.include_router(operations_router)
    app.include_router(reports_obligations_router)
    app.include_router(reports_router)
    app.include_router(reports_rules_router)
    app.include_router(model_services_usage_router)
    app.include_router(team_router)
    app.include_router(conversations_router)
