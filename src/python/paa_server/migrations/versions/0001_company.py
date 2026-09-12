"""Frozen initial company schema, independent of future ORM model changes."""
from alembic import op

revision = '0001_company'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.execute('CREATE TABLE company (\n\tname VARCHAR(120) NOT NULL, \n\trules JSONB NOT NULL, \n\trevision INTEGER NOT NULL, \n\trules_effective_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tid VARCHAR(36) NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id)\n)')
    op.execute('CREATE TABLE company_login_attempt (\n\tidentity VARCHAR(64) NOT NULL, \n\tid VARCHAR(36) NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id)\n)')
    op.execute('CREATE INDEX ix_company_login_attempt_identity ON company_login_attempt (identity)')
    op.execute('CREATE TABLE company_member (\n\tcompany_id VARCHAR(36) NOT NULL, \n\tusername VARCHAR(80) NOT NULL, \n\tname VARCHAR(80) NOT NULL, \n\trole VARCHAR(12) NOT NULL, \n\tpassword_hash TEXT NOT NULL, \n\tactive BOOLEAN NOT NULL, \n\tmust_change_password BOOLEAN NOT NULL, \n\tid VARCHAR(36) NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tFOREIGN KEY(company_id) REFERENCES company (id), \n\tUNIQUE (username)\n)')
    op.execute('CREATE INDEX ix_company_member_company_id ON company_member (company_id)')
    op.execute('CREATE TABLE company_idempotency (\n\taction VARCHAR(160) NOT NULL, \n\tkey VARCHAR(100) NOT NULL, \n\tdigest VARCHAR(64) NOT NULL, \n\tresponse JSONB NOT NULL, \n\tcompany_id VARCHAR(36) NOT NULL, \n\towner_id VARCHAR(36) NOT NULL, \n\tid VARCHAR(36) NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tUNIQUE (owner_id, action, key), \n\tFOREIGN KEY(company_id) REFERENCES company (id), \n\tFOREIGN KEY(owner_id) REFERENCES company_member (id)\n)')
    op.execute('CREATE INDEX ix_company_idempotency_company_id ON company_idempotency (company_id)')
    op.execute('CREATE INDEX ix_company_idempotency_owner_id ON company_idempotency (owner_id)')
    op.execute('CREATE TABLE company_job (\n\tkind VARCHAR(12) NOT NULL, \n\ttarget_id VARCHAR(36) NOT NULL, \n\tstate VARCHAR(20) NOT NULL, \n\tphase VARCHAR(30) NOT NULL, \n\terror TEXT NOT NULL, \n\tfence INTEGER NOT NULL, \n\tlease_until TIMESTAMP WITH TIME ZONE, \n\trequest_started BOOLEAN NOT NULL, \n\tattempt INTEGER NOT NULL, \n\tresult JSONB NOT NULL, \n\tbase_revision INTEGER NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tcompany_id VARCHAR(36) NOT NULL, \n\towner_id VARCHAR(36) NOT NULL, \n\tid VARCHAR(36) NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tFOREIGN KEY(company_id) REFERENCES company (id), \n\tFOREIGN KEY(owner_id) REFERENCES company_member (id)\n)')
    op.execute("CREATE UNIQUE INDEX company_job_one_running_owner ON company_job (owner_id) WHERE state = 'running'")
    op.execute('CREATE INDEX ix_company_job_company_id ON company_job (company_id)')
    op.execute('CREATE INDEX ix_company_job_owner_id ON company_job (owner_id)')
    op.execute('CREATE INDEX ix_company_job_state ON company_job (state)')
    op.execute('CREATE INDEX ix_company_job_target_id ON company_job (target_id)')
    op.execute('CREATE TABLE company_message (\n\ttext TEXT NOT NULL, \n\treply TEXT NOT NULL, \n\tsuggestions JSONB NOT NULL, \n\ttranscript TEXT NOT NULL, \n\ttranscript_revision INTEGER NOT NULL, \n\ttranscript_history JSONB NOT NULL, \n\treply_to VARCHAR(36), \n\tcompany_id VARCHAR(36) NOT NULL, \n\towner_id VARCHAR(36) NOT NULL, \n\tid VARCHAR(36) NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tFOREIGN KEY(reply_to) REFERENCES company_message (id), \n\tFOREIGN KEY(company_id) REFERENCES company (id), \n\tFOREIGN KEY(owner_id) REFERENCES company_member (id)\n)')
    op.execute('CREATE INDEX ix_company_message_company_id ON company_message (company_id)')
    op.execute('CREATE INDEX ix_company_message_owner_id ON company_message (owner_id)')
    op.execute('CREATE TABLE company_report (\n\tkind VARCHAR(10) NOT NULL, \n\tperiod VARCHAR(10) NOT NULL, \n\tperiod_end VARCHAR(10) NOT NULL, \n\ttimezone VARCHAR(80) NOT NULL, \n\tcontent JSONB NOT NULL, \n\tcandidate JSONB, \n\tsource_ids JSONB NOT NULL, \n\trevision INTEGER NOT NULL, \n\tpublished_revision INTEGER NOT NULL, \n\tedited BOOLEAN NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tcompany_id VARCHAR(36) NOT NULL, \n\towner_id VARCHAR(36) NOT NULL, \n\tid VARCHAR(36) NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tUNIQUE (owner_id, kind, period), \n\tFOREIGN KEY(company_id) REFERENCES company (id), \n\tFOREIGN KEY(owner_id) REFERENCES company_member (id)\n)')
    op.execute('CREATE INDEX ix_company_report_company_id ON company_report (company_id)')
    op.execute('CREATE INDEX ix_company_report_owner_id ON company_report (owner_id)')
    op.execute('CREATE TABLE company_session (\n\tmember_id VARCHAR(36) NOT NULL, \n\ttoken_hash VARCHAR(64) NOT NULL, \n\tcsrf VARCHAR(64) NOT NULL, \n\texpires_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tid VARCHAR(36) NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tFOREIGN KEY(member_id) REFERENCES company_member (id), \n\tUNIQUE (token_hash)\n)')
    op.execute('CREATE INDEX ix_company_session_member_id ON company_session (member_id)')
    op.execute('CREATE TABLE company_work_item (\n\ttitle VARCHAR(200) NOT NULL, \n\tcontent JSONB NOT NULL, \n\trevision INTEGER NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tcompany_id VARCHAR(36) NOT NULL, \n\towner_id VARCHAR(36) NOT NULL, \n\tid VARCHAR(36) NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tFOREIGN KEY(company_id) REFERENCES company (id), \n\tFOREIGN KEY(owner_id) REFERENCES company_member (id)\n)')
    op.execute('CREATE INDEX ix_company_work_item_company_id ON company_work_item (company_id)')
    op.execute('CREATE INDEX ix_company_work_item_owner_id ON company_work_item (owner_id)')
    op.execute('CREATE TABLE company_attachment (\n\tmessage_id VARCHAR(36), \n\tkind VARCHAR(10) NOT NULL, \n\tmime VARCHAR(80) NOT NULL, \n\tname VARCHAR(180) NOT NULL, \n\tsize INTEGER NOT NULL, \n\tsha256 VARCHAR(64) NOT NULL, \n\tduration FLOAT, \n\tcompany_id VARCHAR(36) NOT NULL, \n\towner_id VARCHAR(36) NOT NULL, \n\tid VARCHAR(36) NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tFOREIGN KEY(message_id) REFERENCES company_message (id), \n\tFOREIGN KEY(company_id) REFERENCES company (id), \n\tFOREIGN KEY(owner_id) REFERENCES company_member (id)\n)')
    op.execute('CREATE INDEX ix_company_attachment_company_id ON company_attachment (company_id)')
    op.execute('CREATE INDEX ix_company_attachment_message_id ON company_attachment (message_id)')
    op.execute('CREATE INDEX ix_company_attachment_owner_id ON company_attachment (owner_id)')
    op.execute('CREATE TABLE company_model_usage (\n\tjob_id VARCHAR(36) NOT NULL, \n\tkind VARCHAR(16) NOT NULL, \n\tinput_tokens INTEGER NOT NULL, \n\toutput_tokens INTEGER NOT NULL, \n\tcompany_id VARCHAR(36) NOT NULL, \n\towner_id VARCHAR(36) NOT NULL, \n\tid VARCHAR(36) NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tFOREIGN KEY(job_id) REFERENCES company_job (id), \n\tFOREIGN KEY(company_id) REFERENCES company (id), \n\tFOREIGN KEY(owner_id) REFERENCES company_member (id)\n)')
    op.execute('CREATE INDEX ix_company_model_usage_company_id ON company_model_usage (company_id)')
    op.execute('CREATE INDEX ix_company_model_usage_owner_id ON company_model_usage (owner_id)')
    op.execute('CREATE TABLE company_progress_draft (\n\tmessage_id VARCHAR(36) NOT NULL, \n\twork_id VARCHAR(36), \n\tbase_revision INTEGER, \n\tcontent JSONB NOT NULL, \n\trevision INTEGER NOT NULL, \n\tstatus VARCHAR(16) NOT NULL, \n\ttool_key VARCHAR(200) NOT NULL, \n\tcompany_id VARCHAR(36) NOT NULL, \n\towner_id VARCHAR(36) NOT NULL, \n\tid VARCHAR(36) NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tFOREIGN KEY(message_id) REFERENCES company_message (id), \n\tFOREIGN KEY(work_id) REFERENCES company_work_item (id), \n\tUNIQUE (tool_key), \n\tFOREIGN KEY(company_id) REFERENCES company (id), \n\tFOREIGN KEY(owner_id) REFERENCES company_member (id)\n)')
    op.execute('CREATE INDEX ix_company_progress_draft_company_id ON company_progress_draft (company_id)')
    op.execute('CREATE INDEX ix_company_progress_draft_message_id ON company_progress_draft (message_id)')
    op.execute('CREATE INDEX ix_company_progress_draft_owner_id ON company_progress_draft (owner_id)')
    op.execute('CREATE TABLE company_report_revision (\n\treport_id VARCHAR(36) NOT NULL, \n\trevision INTEGER NOT NULL, \n\tcontent JSONB NOT NULL, \n\tsource_ids JSONB NOT NULL, \n\tcompany_id VARCHAR(36) NOT NULL, \n\towner_id VARCHAR(36) NOT NULL, \n\tid VARCHAR(36) NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tUNIQUE (report_id, revision), \n\tFOREIGN KEY(report_id) REFERENCES company_report (id), \n\tFOREIGN KEY(company_id) REFERENCES company (id), \n\tFOREIGN KEY(owner_id) REFERENCES company_member (id)\n)')
    op.execute('CREATE INDEX ix_company_report_revision_company_id ON company_report_revision (company_id)')
    op.execute('CREATE INDEX ix_company_report_revision_owner_id ON company_report_revision (owner_id)')
    op.execute('CREATE INDEX ix_company_report_revision_report_id ON company_report_revision (report_id)')
    op.execute('CREATE TABLE company_work_revision (\n\twork_id VARCHAR(36) NOT NULL, \n\trevision INTEGER NOT NULL, \n\tcontent JSONB NOT NULL, \n\tsource_ids JSONB NOT NULL, \n\tcompany_id VARCHAR(36) NOT NULL, \n\towner_id VARCHAR(36) NOT NULL, \n\tid VARCHAR(36) NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tUNIQUE (work_id, revision), \n\tFOREIGN KEY(work_id) REFERENCES company_work_item (id), \n\tFOREIGN KEY(company_id) REFERENCES company (id), \n\tFOREIGN KEY(owner_id) REFERENCES company_member (id)\n)')
    op.execute('CREATE INDEX ix_company_work_revision_company_id ON company_work_revision (company_id)')
    op.execute('CREATE INDEX ix_company_work_revision_owner_id ON company_work_revision (owner_id)')
    op.execute('CREATE INDEX ix_company_work_revision_work_id ON company_work_revision (work_id)')


def downgrade():
    raise RuntimeError('Restore a matching backup and application image; destructive downgrade is disabled')
