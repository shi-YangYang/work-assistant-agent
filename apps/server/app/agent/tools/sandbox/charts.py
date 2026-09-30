from typing import Literal
from langchain.tools import ToolRuntime, tool
from app.tasks.context import RunContext
from app.modules.executions.builtin.schemas import TableData, TableSource
from .common import invoke


@tool
async def create_chart(filename: str, x: str, y: list[str], runtime: ToolRuntime[RunContext], kind: Literal['bar', 'line'] = 'bar',
                       data: TableData | None = None, source: TableSource | None = None,
                       title: str = '', x_label: str = '', y_label: str = '',
                       deliverable_id: str = '', expected_revision: int = 0, step: int = 1) -> str:
    """Create a Chinese bar/line PNG directly, without Python boilerplate.
    Provide exactly one of inline data={columns,rows} or source with real input_ref.
    x is the category column, y lists 1..6 numeric series. 1..60 rows with unique
    categories; no aggregation, missing-value filling or row removal. Explicit
    labels/units; Chinese fonts and legibility handled by the toolkit. Complex
    calculations/charts use run_python. Filename ends .png. Success privately
    saves the file. Revisions require reading the old deliverable and its current
    version; step 1..8 is shared with other file tools in this user message.
    """
    return await invoke(runtime, 'create_chart', {'filename': filename, 'x': x, 'y': y, 'kind': kind, 'data': data,
                        'source': source, 'title': title, 'x_label': x_label, 'y_label': y_label}, title=title or filename,
                        deliverable_id=deliverable_id, expected_revision=expected_revision, step=step)
