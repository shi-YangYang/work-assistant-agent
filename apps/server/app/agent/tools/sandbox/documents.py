from typing import Literal
from langchain.tools import ToolRuntime, tool
from app.tasks.context import RunContext
from app.modules.executions.builtin.schemas import Block
from .common import invoke


@tool
async def create_document(filename: str, title: str, blocks: list[Block], runtime: ToolRuntime[RunContext],
                          format: Literal['docx', 'pdf'] = 'docx', deliverable_id: str = '', expected_revision: int = 0, step: int = 1) -> str:
    """Create a Chinese Word/PDF from structured blocks, without writing Python.
    blocks: heading{text,level1..3}, paragraph{text}, list{items}, table{table:{columns,rows}},
    image{input_ref,caption}; each block uses ONE type, no markup interpretation.
    Images use authorized attachment_id or {deliverable_id,revision,file_id}; never
    URLs or guessed paths. Font embedding for PDF, wrapping/pagination handled by
    toolkit. Tables max 8 columns; unsupported/overlong content fails honestly.
    Filename includes .docx/.pdf. ONLY succeeded plus delivery is proof of a saved
    file; font/format checks do not guarantee every layout was visually inspected.
    To revise, read previous deliverable then give id/current expected_revision.
    step 1..8 is shared with all file tools; distinct new outputs need distinct steps.
    """
    return await invoke(runtime, 'create_document', {'filename': filename, 'title': title, 'blocks': blocks, 'format': format},
                        title=title, deliverable_id=deliverable_id, expected_revision=expected_revision, step=step)
