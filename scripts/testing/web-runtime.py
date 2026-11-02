"""Run real API/worker with a deterministic provider HTTP transport only."""
import asyncio
import json
import os
from pathlib import Path
import sys
import httpx

root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(root / 'scripts/company/web-acceptance'))
from environment import load_environment
metadata, private = load_environment(sys.argv[1])
assert metadata['suite'] == 'project'
os.environ.update(private['environment'])
from app.integrations.models import transport

scenario_calls = 0

async def controlled(self, request):
    global scenario_calls
    if request.url.host != 'project-provider.invalid':
        raise RuntimeError('Unexpected external provider request')
    payload = json.loads(request.content)
    messages = payload.get('messages', [])
    text = json.dumps(messages, ensure_ascii=False)
    structured = None
    for message in reversed(messages):
        try:
            value = json.loads(message.get('content', ''))
            if isinstance(value, dict) and 'proposedOperation' in value:
                structured = value
                break
        except (ValueError, TypeError):
            pass
    if structured:
        quote = structured['currentUserText']
        content = json.dumps({'allowed':True, 'quote':quote, 'reason':'', 'requireConfirmation':True,
            'quoteMessageId':structured['messageId'], 'materialSelection':{'mode':'none','quote':quote,'references':[], 'destination':'new','targetId':'','destinationEvidence':{'source':'user','messageId':structured['messageId'],'quote':quote}}})
        with Path(os.environ['PROJECT_TEST_OUTPUT'], 'provider.jsonl').open('a') as log:
            log.write(json.dumps({'request':payload,'content':content},ensure_ascii=False)+'\n')
        return httpx.Response(200,json={'choices':[{'message':{'role':'assistant','content':content},'finish_reason':'stop'}]},request=request)
    if 'PROJECT_CONVERSATION_FLOW' in text and payload.get('tools'):
        if scenario_calls == 0:
            name, args = 'request_user_input', {'questions':[{'id':'direction','prompt':'选择合成工作方向','type':'single','options':[{'id':'test','label':'测试整理'},{'id':'docs','label':'文档整理'}]}]}
        else:
            name, args = 'execute_business_action', {'step':1,'action':'create_work','changes':{'title':'分批材料确认工作','body':{'schemaVersion':1,'content':[{'type':'paragraph','content':[{'type':'text','text':'依据两批合成材料建立工作'}]}]}}}
        scenario_calls += 1
        call = {'id':f'controlled-{scenario_calls}', 'type':'function', 'function':{'name':name,'arguments':json.dumps(args,ensure_ascii=False)}}
        with Path(os.environ['PROJECT_TEST_OUTPUT'], 'provider.jsonl').open('a') as log:
            log.write(json.dumps({'request':payload,'tool':call},ensure_ascii=False)+'\n')
        return httpx.Response(200,json={'choices':[{'message':{'role':'assistant','content':'','tool_calls':[call]},'finish_reason':'tool_calls'}]},request=request)
    if 'report_fact_review' in text:
        content = '{"valid":true}'
    elif 'completed' in text and 'ongoing' in text:
        content = json.dumps({'completed':'已整理项目测试需求', 'ongoing':'核对工作正文和清单', 'blockers':'', 'next':'继续检查'}, ensure_ascii=False)
    else:
        content = '已收到合成测试消息。'
    record = {'path': str(request.url), 'request': payload, 'content': content}
    with Path(os.environ['PROJECT_TEST_OUTPUT'], 'provider.jsonl').open('a') as log:
        log.write(json.dumps(record, ensure_ascii=False) + '\n')
    if payload.get('stream'):
        chunks = [{'choices':[{'index':0,'delta':{'content': content}, 'finish_reason':None}]}, {'choices':[{'index':0,'delta':{},'finish_reason':'stop'}]}]
        data = ''.join('data: ' + json.dumps(chunk) + '\n\n' for chunk in chunks) + 'data: [DONE]\n\n'
        return httpx.Response(200, headers={'content-type':'text/event-stream'}, content=data.encode(), request=request)
    return httpx.Response(200, json={'choices':[{'message':{'role':'assistant','content':content},'finish_reason':'stop'}], 'usage':{'prompt_tokens':10,'completion_tokens':10}}, request=request)

transport.SafeTransport.handle_async_request = controlled
if sys.argv[2] == 'api':
    import uvicorn
    uvicorn.run('app.main:app', host='127.0.0.1', port=int(metadata['apiOrigin'].rsplit(':', 1)[1]))
else:
    from app.worker import main
    asyncio.run(main())
