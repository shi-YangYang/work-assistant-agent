from datetime import date
from typing import Literal
from pydantic import Field, model_validator
from app.core.schemas import Input, Revision
from app.modules.work.content.document import WorkDocument


class MaterialSource(Input):
    attachmentId: str | None = None
    deliverableId: str | None = None
    revision: int | None = Field(default=None, ge=1)
    fileId: str | None = None

    @model_validator(mode='after')
    def one_source(self):
        if bool(self.attachmentId) == bool(self.deliverableId) or self.deliverableId and (not self.revision or not self.fileId):
            raise ValueError('请选择一个附件或成果文件的准确版本')
        if self.attachmentId and (self.revision is not None or self.fileId is not None):
            raise ValueError('附件引用不能同时指定成果版本或文件')
        return self


class RecordPatch(Input):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    status: Literal['in_progress', 'blocked', 'done'] | None = None
    dueDate: date | None = None
    blocker: str | None = Field(default=None, max_length=2000)
    nextStep: str | None = Field(default=None, max_length=2000)
    body: WorkDocument | None = None
    bodyEdits: list[dict] | None = Field(default=None, max_length=100)
    materials: list[MaterialSource] = Field(default_factory=list, max_length=9)
    materialIds: list[str] | None = Field(default=None, max_length=1000)

    @model_validator(mode='after')
    def valid_patch(self):
        if self.body is not None and self.bodyEdits is not None:
            raise ValueError('不能同时替换正文和修改内容块')
        for key in ('title', 'status', 'blocker', 'nextStep', 'body', 'bodyEdits', 'materialIds'):
            if key in self.model_fields_set and getattr(self, key) is None:
                raise ValueError(key + ' 不能为 null')
        if self.title is not None and not self.title.strip():
            raise ValueError('请输入工作标题')
        return self


class WorkPatch(RecordPatch, Revision):
    pass


class UpdateInput(Input):
    text: str = Field(default='', max_length=12000)
    materialIds: list[str] = Field(default_factory=list, max_length=9)
    materials: list[MaterialSource] = Field(default_factory=list, max_length=9)
    status: Literal['in_progress', 'blocked', 'done'] | None = None
    dueDate: date | None = None
    blocker: str | None = Field(default=None, max_length=2000)
    nextStep: str | None = Field(default=None, max_length=2000)

    @model_validator(mode='after')
    def nonempty(self):
        if not self.text.strip() and not self.materialIds and not self.materials and not isinstance(self, UpdateEdit):
            raise ValueError('请填写进展或添加材料')
        if len(self.materialIds) + len(self.materials) > 9:
            raise ValueError('每条进展最多添加 9 个附件')
        return self


class UpdateCreate(UpdateInput, Revision):
    pass


class UpdateEdit(UpdateInput, Revision):
    expectedUpdateRevision: int = Field(ge=1)


class UpdateDelete(Revision):
    expectedUpdateRevision: int = Field(ge=1)


class MaterialRemove(Revision):
    expectedMaterialRevision: int = Field(ge=1)


class UpdateChange(Input):
    action: Literal['create', 'edit', 'delete']
    id: str | None = None
    expectedRevision: int | None = Field(default=None, ge=1)
    text: str = Field(default='', max_length=12000)
    materialIds: list[str] = Field(default_factory=list, max_length=9)
    materials: list[MaterialSource] = Field(default_factory=list, max_length=9)

    @model_validator(mode='after')
    def valid_target(self):
        if self.action != 'create' and (not self.id or not self.expectedRevision):
            raise ValueError('修改进展需要条目 ID 和版本')
        if self.action == 'create':
            UpdateInput(text=self.text, materialIds=self.materialIds, materials=self.materials)
        return self


class RemoveMaterialChange(Input):
    id: str
    expectedRevision: int = Field(ge=1)


class AgentWorkChanges(RecordPatch):
    summary: str | None = Field(default=None, max_length=4000)
    update: UpdateChange | None = None
    removeMaterial: RemoveMaterialChange | None = None

    @model_validator(mode='after')
    def one_record_write(self):
        if any(key in self.model_fields_set and getattr(self, key) is None for key in ('summary', 'update', 'removeMaterial')):
            raise ValueError('工作变更不能为 null')
        if self.update and ('summary' in self.model_fields_set or self.body is not None or self.bodyEdits is not None or self.removeMaterial):
            raise ValueError('正文与进展请作为独立保存步骤')
        if self.removeMaterial and self.model_fields_set != {'removeMaterial'}:
            raise ValueError('材料移除请作为独立步骤')
        return self
