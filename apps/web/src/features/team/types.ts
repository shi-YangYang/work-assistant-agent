import type { TeamReportRow, TeamWorkRow } from '@paa/api-contracts'

export type TeamRow = TeamWorkRow | TeamReportRow
export const isWork = (row: TeamRow): row is TeamWorkRow => 'work' in row
