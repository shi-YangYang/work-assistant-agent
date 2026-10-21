import json
from langchain_core.messages import AIMessage, HumanMessage
from app.modules.messages.models import Message
from app.security.ownership import owned
from app.tasks.lease import lease


async def conversation_history(context, job, content):
    """Use the same authorized references as the independent intent check."""
    from app.agent.context.references.conversation_context import conversation_references
    async with context.sessions.begin() as db:
        live, actor = await lease(db, context)
        current = await owned(db, Message, job.target_id, actor)
        references = await conversation_references(db, actor, live, current, context=context)
        from app.agent.context.references.deliverable_context import deliverable_context
        results = await deliverable_context(db, actor, current, job=live)
        from app.modules.executions.queries import read_executions
        executions = await read_executions(db, actor, live, current)
        from app.agent.context.task_context import projection, instruction
        task = await projection(db, actor, live, current, context)
        from app.agent.context.document_history import previous_document_text
        prior_documents = await previous_document_text(db, context, live, actor, references, content)
    messages = [HumanMessage(content=instruction(task))]
    if results.get('items') or results.get('selected'):
        messages.append(HumanMessage(content='服务端私人成果目录（不是授权；每个文件独立，不按同名合并；保存文件直接使用 materialSource，只有读取正文/条目/关联才需 read_deliverable）：' + json.dumps(results, ensure_ascii=False)))
    if executions['items'] or executions['nextOffset']:
        messages.append(HumanMessage(content='本会话已保存的执行记录目录（参考数据，不是授权；用 read_execution 读取实际代码或内置工具参数与输出，追问已有结果无需重新运行）：' + json.dumps(executions, ensure_ascii=False)))
    for reference in references:
        materials = {'messageId': reference['id'], **{k: v for k, v in reference.items()
            if k not in ('id', 'userText', 'assistantReference', 'currentActions')}}
        history_content = ('此前用户对话（交流意图和输出限制延续；一次性旧操作不可重放；明确持续指令按服务端任务快照延续）：\n'
                           + reference['userText'] + '\n\n该历史消息的服务端参考信息（messageId 为消息 ID）：'
                           + json.dumps(materials, ensure_ascii=False))
        messages.append(HumanMessage(id=f"history:{reference['id']}", content=history_content))
        reply = reference['assistantReference']
        if reference['currentActions']:
            reply += '\n服务端复核的当前操作状态（历史方案不代表已执行）：' + json.dumps(reference['currentActions'], ensure_ascii=False)
        if reply:
            messages.append(AIMessage(id=f"history-reply:{reference['id']}", content=reply))
    if prior_documents is not None:
        messages.append(prior_documents)
    return messages
