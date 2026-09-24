ACTIONS = frozenset({'create_work', 'update_work', 'delete_work', 'generate_report', 'edit_report', 'submit_report', 'delete_report'})


CONFIRM = frozenset({'delete_work', 'submit_report', 'delete_report'})


WORK_FIELDS = frozenset({'title', 'summary', 'status', 'blocker', 'nextStep', 'dueDate'})


REPORT_FIELDS = frozenset({'completed', 'ongoing', 'blockers', 'next'})


LABELS = {'create_work': '创建工作', 'update_work': '更新工作', 'delete_work': '删除工作', 'generate_report': '生成报告', 'edit_report': '编辑报告', 'submit_report': '提交报告', 'delete_report': '删除报告'}
