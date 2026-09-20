import type { Member } from '@paa/api-contracts'
import { write } from '@web/api/client'

export function deleteMember(member: Member, body: undefined) {
  return write(`/members/${member.id}`, body, 'DELETE')
}

export function membersPath() {
  return '/members'
}

export function updateMember(member: Member, body: { active: boolean }) {
  return write(`/members/${member.id}`, body, 'PATCH')
}

export function resetMemberPassword(reset: Member, body: { password: FormDataEntryValue | null }) {
  return write(`/members/${reset.id}/reset-password`, body)
}

export function createMember(body: {
  name: FormDataEntryValue | null
  username: FormDataEntryValue | null
  role: string
  password: FormDataEntryValue | null
}) {
  return write('/members', body)
}
