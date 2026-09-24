import json
from langchain_core.messages import AIMessage, HumanMessage
from paa_server.modules.messages.models import Message
from paa_server.security.ownership import owned
from paa_server.tasks.lease import lease


async def conversation_history(context, job, content):
    """Use the same authorized references as the independent intent check."""
    from paa_server.agent.conversation_context import conversation_references
    async with context.sessions.begin() as db:
        live, actor = await lease(db, context)
        current = await owned(db, Message, job.target_id, actor)
        references = await conversation_references(db, actor, live, current)
    messages = []
    for reference in references:
        messages.append(HumanMessage(id=f"history:{reference['id']}", content='此前用户请求与材料（仅当前请求明确承接时作为参考）：' + json.dumps({k: v for k, v in reference.items() if k not in ('assistantReference', 'currentActions')}, ensure_ascii=False)))
        reply = reference['assistantReference']
        if reference['currentActions']:
            reply += '\n服务端复核的当前操作状态（历史方案不代表已执行）：' + json.dumps(reference['currentActions'], ensure_ascii=False)
        if reply:
            messages.append(AIMessage(id=f"history-reply:{reference['id']}", content=reply))
    return messages
