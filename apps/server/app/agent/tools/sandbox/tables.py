from typing import Literal
from langchain.tools import ToolRuntime, tool
from app.tasks.context import RunContext
from app.modules.executions.builtin.schemas import TableData, TableSource
from .common import invoke


@tool
async def inspect_table(source: TableSource, runtime: ToolRuntime[RunContext], sample_rows: int = 8) -> str:
    """Inspect an authorized CSV/XLSX without writing Python. Returns row/column
    counts, missing/duplicate counts, actual types and up to 20 sample rows; samples
    can be truncated explicitly. source.input_ref is a real attachment_id OR
    {deliverable_id,revision,file_id} from this conversation, never a path.
    CSV keeps strings/leading zeros unless column_types explicitly requests
    string/number/boolean. No implicit cleaning, aggregation or formula execution.
    Use this before choosing columns. Errors are corrective feedback, not evidence.
    """
    return await invoke(runtime, 'inspect_table', {'source': source, 'sample_rows': sample_rows}, title='检查表格')


@tool
async def export_table(filename: str, runtime: ToolRuntime[RunContext], format: Literal['csv', 'xlsx'] = 'xlsx',
                       data: TableData | None = None, source: TableSource | None = None,
                       deliverable_id: str = '', expected_revision: int = 0, step: int = 1) -> str:
    """Export CSV/XLSX directly; no Python needed for routine table delivery.
    Provide exactly one of data={columns:[...],rows:[[scalar,...],...]} or source
    with real input_ref. Filename includes .csv/.xlsx. Up to 2000 inline rows;
    larger tables use authorized files (max 20000 rows/40 columns). Preserves all
    rows; no aggregation or cleaning. Formula-like strings are stored as text.
    File is privately saved ONLY on success. To revise, read the old deliverable
    and provide deliverable_id/expected_revision. step 1..8 is shared with other
    file tools/save_deliverable within this user message; use distinct steps for
    distinct outputs, stable step on retry. Use real returned download URLs.
    """
    return await invoke(runtime, 'export_table', {'filename': filename, 'format': format, 'data': data, 'source': source},
                        title=filename, deliverable_id=deliverable_id, expected_revision=expected_revision, step=step)
