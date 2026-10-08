from typing import Literal
from langchain.tools import ToolRuntime, tool
from app.tasks.context import RunContext
from app.modules.executions.builtin.schemas import Block
from .common import invoke


@tool
async def create_document(filename: str, title: str, blocks: list[Block], runtime: ToolRuntime[RunContext],
                          format: Literal['docx', 'pdf'] = 'docx', deliverable_id: str = '', expected_revision: int = 0,
                          step: int = 1, max_pages: int | None = None) -> str:
    """Create a Chinese Word/PDF from structured blocks, without writing Python.
    title is rendered automatically; blocks contain the body, so do not repeat title as a heading.
    blocks: heading{text,level1..3}, paragraph{text}, list{items}, table{table:{columns,rows}},
    image{input_ref,caption}; each block uses ONE type, no markup interpretation.
    Images use authorized attachment_id or {deliverable_id,revision,file_id}; never
    URLs or guessed paths. Font embedding for PDF, wrapping/pagination handled by
    toolkit. Tables max 8 columns; unsupported/overlong content fails honestly.
    When the user specifies a page limit, pass max_pages (1..40), including on revisions/exports.
    A fixed readable compact layout is rendered and counted before publication; overflow fails
    without deleting content or shrinking text further. Do not omit the limit or shorten user
    content to bypass failure. DOCX counts use the image's LibreOffice and may vary elsewhere.
    Without max_pages, DOCX page count is NOT verified. Creating PDF from blocks rebuilds the
    layout; it is not layout-preserving DOCX conversion. Claim page counts only from receipts.
    Filename includes .docx/.pdf. ONLY succeeded plus delivery is proof of a saved
    file; font/format checks do not guarantee every layout was visually inspected.
    To revise, read previous deliverable then give id/current expected_revision.
    step 1..8 is shared with all file tools; distinct new outputs need distinct steps.
    """
    return await invoke(runtime, 'create_document', {'filename': filename, 'title': title, 'blocks': blocks,
                                                   'format': format, 'max_pages': max_pages},
                        title=title, deliverable_id=deliverable_id, expected_revision=expected_revision, step=step)
