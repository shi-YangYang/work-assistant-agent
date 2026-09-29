import json
from fastapi import HTTPException
from langchain.tools import ToolRuntime, tool
from app.tasks.context import RunContext
from app.modules.executions.service import execute


@tool
async def run_python(code: str, title: str, runtime: ToolRuntime[RunContext], input_refs: list[dict] | None = None,
                     deliverable_id: str = '', expected_revision: int = 0, step: int = 1) -> str:
    """Run Python in a private CPU sandbox for actual computation, data analysis,
    charts or generating TXT/MD/JSON/CSV/XLSX/PNG/DOCX/PDF/PPTX files. Ordinary
    answers/writing/code explanations need no execution. No network or pip install.
    Libraries: pandas,numpy,openpyxl,matplotlib,python-docx,python-pptx,reportlab,
    Pillow,pypdf. LibreOffice/Poppler and Noto CJK fonts available for render checks.
    Input references: {attachment_id: real ID} or {deliverable_id,revision,file_id}
    from current conversation. Copied files are under /work/inputs; list this
    directory to get exact filenames. Write final files ONLY in /work/output.
    Use /work/tmp for intermediates; print compact computed results to stdout.
    Each call is a NEW environment, no persistent Python variables. Read previous
    deliverable then reference its files to continue. To publish a new version,
    provide its deliverable_id/expected_revision. step 1..8 is stable per user
    message and shared with save_deliverable. Success auto-saves generated files;
    never invent links or claim files exist before success. On code error inspect
    stderr and repair code; do not repeat identical failing code. Report actual
    calculations and limitations. Chinese plots need Noto CJK. Embed Chinese PDF fonts: ReportLab TTFont
    with /usr/share/fonts/truetype/wqy/wqy-microhei.ttc (subfontIndex=0). Do not
    use nonembedded UnicodeCIDFont/STSong; missing glyphs or fonts fail export.
    Validate documents by reopening/rendering inside sandbox before delivery.
    fileChecks states verified properties per file; do not generalize PDF font
    embedding to Word/PPTX or claim checks not actually performed.
    """
    try:
        result = await execute(runtime.context, code=code, title=title, references=input_refs or [], identifier=deliverable_id, revision=expected_revision, step=step)
        return json.dumps(result, ensure_ascii=False)
    except HTTPException as error:
        return json.dumps({'state': 'failed', 'message': error.detail['message']}, ensure_ascii=False)
    except ValueError as error:
        return json.dumps({'state': 'failed', 'message': str(error)}, ensure_ascii=False)
