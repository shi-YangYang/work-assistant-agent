from app.core.personas import PersonaId
from app.core.attachment_limits import MAX_ATTACHMENTS, MAX_AUDIO_ATTACHMENTS
from app.core.schemas import Input
from app.modules.operations.execution_policy import ExecutionMode
from app.modules.deliverables.schemas import DeliverableReference
from pydantic import Field, model_validator


class SendMessage(Input):
    conversationId: str | None = None
    personaId: PersonaId | None = None
    executionMode: ExecutionMode | None = None
    fullAccessConfirmed: bool = False
    newConversation: bool = False
    text: str = Field(default='', max_length=8000)
    attachmentIds: list[str] = Field(default_factory=list, max_length=MAX_ATTACHMENTS)
    voiceCommandAttachmentId: str | None = None
    voiceCommandAttachmentIds: list[str] | None = Field(default=None, max_length=MAX_AUDIO_ATTACHMENTS)
    replyTo: str | None = None
    deliverableReference: DeliverableReference | None = None

    @model_validator(mode='after')
    def content_present(self):
        if 'personaId' in self.model_fields_set and self.personaId is None:
            raise ValueError('请选择有效人设')
        if 'executionMode' in self.model_fields_set and self.executionMode is None:
            raise ValueError('请选择有效执行权限')
        if self.newConversation and self.conversationId:
            raise ValueError('新会话不能同时指定已有会话')
        self.text = self.text.strip()
        if not self.text and not self.attachmentIds:
            raise ValueError('请输入文字或添加文件、图片、语音')
        if len(set(self.attachmentIds)) != len(self.attachmentIds):
            raise ValueError('附件重复')
        if self.voiceCommandAttachmentIds is not None:
            if self.voiceCommandAttachmentId is not None or len(set(self.voiceCommandAttachmentIds)) != len(self.voiceCommandAttachmentIds):
                raise ValueError('语音指令附件不能重复或同时使用两种标记')
        return self


class TranscriptEdit(Input):
    text: str = Field(max_length=8000)
    expectedRevision: int = Field(ge=0)
