"""Shared controlled fixtures extracted from test_prose_delivery."""
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from _support.agent.response_delivery import DeliveryModel


class ProseModel(DeliveryModel):
    task_value: dict | None = None
    requested_write: bool = False
    async def _agenerate(self,messages,stop=None,run_manager=None,**kwargs):
        self.calls+=1
        self.requests.append({'tools':[tool['function']['name'] for tool in kwargs.get('tools',[])],'tool_choice':kwargs.get('tool_choice')})
        if self.task_value and self.calls==1:
            assert self.requests[-1]['tools']==['load_tools']
            result=AIMessage(content='',tool_calls=[{'name':'load_tools','id':'load-context','args':{'groups':['task_context']}}])
        elif self.task_value and self.calls==2:
            assert 'set_task_context' in self.requests[-1]['tools']
            result=AIMessage(content='',tool_calls=[{'name':'set_task_context','id':'task-context','args':{'task':self.task_value,'business_requested':self.requested_write}}])
        else:
            result=AIMessage(content=self.answer)
        return ChatResult(generations=[ChatGeneration(message=result)])
