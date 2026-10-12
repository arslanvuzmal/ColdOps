"""Warm-up, per mailbox per day.

The warm-up round reported one total for the whole pool, so nobody could see a
single mailbox falling behind -- or a single mailbox's warm-up mail being filed
as spam, the earliest warning there is. The operator's target is every mailbox
fully warmed by 25 Oct 2026; this is how each one is measured against it.

One row per (workspace, UTC day, mailbox), counters only: messages it sent,
messages it received, its own messages found in a junk folder and moved back
(``rescued``: the signal that matters most), and replies it wrote. No content,
no recipients.
"""

from __future__ import annotations

from alembic import op

revision = "c4e8a1f07d32"
down_revision = "b9f3d6a20e57"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE warmup_daily (
            workspace_id uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
            day date NOT NULL,
            mailbox text NOT NULL,
            sent integer NOT NULL DEFAULT 0,
            received integer NOT NULL DEFAULT 0,
            rescued integer NOT NULL DEFAULT 0,
            replied integer NOT NULL DEFAULT 0,
            updated_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (workspace_id, day, mailbox)
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS warmup_daily")
