from app.core.schemas import Input
from pydantic import Field, model_validator


class DeliverableItem(Input):
    id: str = Field(default='', max_length=36)
    title: str = Field(min_length=1, max_length=200)
    body: str = Field(default='', max_length=8000)


class DeliverableContent(Input):
    title: str = Field(min_length=1, max_length=200)
    body: str = Field(default='', max_length=32000)
    items: list[DeliverableItem] = Field(default_factory=list, max_length=80)

    @model_validator(mode='after')
    def nonempty(self):
        self.title = self.title.strip()
        if not self.title or not self.body.strip() and not self.items:
            raise ValueError('成果需要标题与内容')
        ids = [item.id for item in self.items if item.id]
        if len(ids) != len(set(ids)) or any(not item.title.strip() for item in self.items):
            raise ValueError('成果条目编号重复或标题为空')
        if len(self.body) + sum(len(item.body) + len(item.title) for item in self.items) > 60000:
            raise ValueError('成果过长，请拆成独立方案')
        return self


class DeliverableReference(Input):
    id: str = Field(min_length=1, max_length=36)
    revision: int = Field(ge=1)
    itemIds: list[str] = Field(default_factory=list, max_length=80)
