from langchain.tools import ToolRuntime, tool
from app.tasks.context import RunContext
from app.modules.executions.builtin.schemas import Slide
from .common import invoke


@tool
async def create_slides(filename: str, title: str, pages: list[Slide], runtime: ToolRuntime[RunContext],
                        deliverable_id: str = '', expected_revision: int = 0, step: int = 1) -> str:
    """Create an editable Chinese PPTX directly, not Python or slide screenshots.
    pages contain title and structured blocks: paragraph{text}, heading{text},
    list{items}, table{table:{columns,rows}}, image{input_ref,caption}. Images must
    reference real authorized files. title sets document metadata; no extra cover.
    Content blocks may split into multiple titled slides; warnings report this.
    Max 6 table columns; oversized single rows/titles fail, never silently clip.
    Filename ends .pptx. Success privately saves a real file; use returned URLs.
    Revisions require reading previous deliverable and current expected_revision;
    step 1..8 is shared with other file tools/save_deliverable in this message.
    """
    return await invoke(runtime, 'create_slides', {'filename': filename, 'title': title, 'pages': pages}, title=title,
                        deliverable_id=deliverable_id, expected_revision=expected_revision, step=step)
