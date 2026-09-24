def member_dto(member):
    return {'id': member.id, 'name': member.name, 'username': member.username, 'role': member.role, 'active': member.active, 'deleted': member.deleted, 'hasPassword': bool(member.password_hash)}
