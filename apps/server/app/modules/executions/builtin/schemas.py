"""Lightweight model-facing contracts. No document libraries run in the API."""
from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictFloat, StrictInt, StrictStr, model_validator

Text = Annotated[str, Field(max_length=12000)]
Scalar = Annotated[StrictStr, Field(max_length=2000)] | StrictInt | StrictFloat | StrictBool | None


class Contract(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)


class FileReference(Contract):
    attachment_id: str = Field(default='', max_length=80)
    deliverable_id: str = Field(default='', max_length=80)
    revision: int = Field(default=0, ge=0)
    file_id: str = Field(default='', max_length=80)

    @model_validator(mode='after')
    def reference(self):
        if self.attachment_id:
            if self.deliverable_id or self.file_id or self.revision:
                raise ValueError('附件与成果引用不能混用')
        elif not (self.deliverable_id and self.file_id and self.revision > 0):
            raise ValueError('提供真实 attachment_id 或完整的 deliverable_id/revision/file_id')
        return self


class TableSource(Contract):
    input_ref: FileReference
    sheet: str = Field(default='', max_length=120)
    encoding: Literal['utf-8-sig', 'utf-8', 'gb18030'] = 'utf-8-sig'
    column_types: dict[str, Literal['string', 'number', 'boolean']] = Field(default_factory=dict, max_length=40)


class TableData(Contract):
    columns: list[Annotated[str, Field(min_length=1, max_length=120)]] = Field(min_length=1, max_length=40)
    rows: list[list[Scalar]] = Field(default_factory=list, max_length=2000)

    @model_validator(mode='after')
    def shape(self):
        if len(set(self.columns)) != len(self.columns) or any(len(row) != len(self.columns) for row in self.rows):
            raise ValueError('列名不可重复，每行数据必须与列数一致')
        return self


class Block(Contract):
    type: Literal['heading', 'paragraph', 'list', 'table', 'image']
    text: Text = ''
    level: int = Field(default=1, ge=1, le=3)
    items: list[Annotated[str, Field(min_length=1, max_length=2000)]] = Field(default_factory=list, max_length=100)
    table: TableData | None = None
    input_ref: FileReference | None = None
    caption: str = Field(default='', max_length=300)

    @model_validator(mode='after')
    def content(self):
        if ((self.text and self.type not in ('heading', 'paragraph')) or
                (self.items and self.type != 'list') or (self.table is not None and self.type != 'table') or
                (self.input_ref is not None and self.type != 'image') or (self.caption and self.type != 'image')):
            raise ValueError('内容块包含其他类型的数据，请拆成独立内容块')
        if self.type in ('heading', 'paragraph') and not self.text.strip():
            raise ValueError('标题或段落不能为空')
        if self.type == 'heading' and len(self.text) > 300:
            raise ValueError('标题不能超过300字')
        if self.type == 'list' and not self.items:
            raise ValueError('列表不能为空')
        if self.type == 'table' and self.table is None:
            raise ValueError('表格块需要table')
        if self.type == 'image' and self.input_ref is None:
            raise ValueError('图片块需要真实文件引用')
        return self


class Slide(Contract):
    title: str = Field(min_length=1, max_length=200)
    blocks: list[Block] = Field(default_factory=list, max_length=20)


class InspectArguments(Contract):
    source: TableSource
    sample_rows: int = Field(default=8, ge=0, le=20)


class TabularArguments(Contract):
    data: TableData | None = None
    source: TableSource | None = None

    @model_validator(mode='after')
    def input(self):
        if (self.data is None) == (self.source is None):
            raise ValueError('data和source必须且只能提供一个')
        return self


class ExportArguments(TabularArguments):
    filename: str = Field(min_length=1, max_length=180)
    format: Literal['csv', 'xlsx'] = 'xlsx'


class ChartArguments(TabularArguments):
    filename: str = Field(min_length=1, max_length=180)
    kind: Literal['bar', 'line'] = 'bar'
    x: str = Field(min_length=1, max_length=120)
    y: list[Annotated[str, Field(min_length=1, max_length=120)]] = Field(min_length=1, max_length=6)
    title: str = Field(default='', max_length=200)
    x_label: str = Field(default='', max_length=120)
    y_label: str = Field(default='', max_length=120)


class DocumentArguments(Contract):
    filename: str = Field(min_length=1, max_length=180)
    format: Literal['docx', 'pdf'] = 'docx'
    title: str = Field(min_length=1, max_length=200)
    blocks: list[Block] = Field(min_length=1, max_length=200)


class SlidesArguments(Contract):
    filename: str = Field(min_length=1, max_length=180)
    title: str = Field(min_length=1, max_length=200)
    pages: list[Slide] = Field(min_length=1, max_length=40)


ARGUMENTS = {'inspect_table': InspectArguments, 'export_table': ExportArguments,
             'create_chart': ChartArguments, 'create_document': DocumentArguments, 'create_slides': SlidesArguments}
LABELS = {'inspect_table': '检查表格', 'export_table': '导出表格', 'create_chart': '生成图表',
          'create_document': '生成文档', 'create_slides': '生成演示文稿'}
EXECUTION_TOOLS = frozenset({'run_python', *ARGUMENTS})
