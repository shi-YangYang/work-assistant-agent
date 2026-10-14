from app.core.schemas import Input
from pydantic import Field, model_validator


class AnnouncementCreate(Input):
    title: str = Field(min_length=1, max_length=100)
    markdown: str = Field(min_length=1, max_length=20000)

    @model_validator(mode='after')
    def nonempty(self):
        self.title = self.title.strip()
        self.markdown = self.markdown.replace('\r\n', '\n').replace('\r', '\n').strip()
        if not self.title or not self.markdown:
            raise ValueError('请填写公告标题和正文')
        return self


class AnnouncementVersion(Input):
    expectedRevision: int = Field(ge=1, strict=True)


class AnnouncementPatch(AnnouncementCreate, AnnouncementVersion):
    pass
