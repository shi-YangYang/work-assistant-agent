from app.core.schemas import Input
from pydantic import Field, model_validator


class SendMessage(Input):
    conversationId: str | None = None
    newConversation: bool = False
    text: str = Field(default='', max_length=8000)
    attachmentIds: list[str] = Field(default_factory=list, max_length=4)
    voiceCommandAttachmentId: str | None = None
    replyTo: str | None = None

    @model_validator(mode='after')
    def content_present(self):
        if self.newConversation and self.conversationId:
            raise ValueError('新会话不能同时指定已有会话')
        self.text = self.text.strip()
        if not self.text and not self.attachmentIds:
            raise ValueError('请输入文字或添加文件、图片、语音')
        if len(set(self.attachmentIds)) != len(self.attachmentIds):
            raise ValueError('附件重复')
        return self


class TranscriptEdit(Input):
    text: str = Field(max_length=8000)
    expectedRevision: int = Field(ge=0)
