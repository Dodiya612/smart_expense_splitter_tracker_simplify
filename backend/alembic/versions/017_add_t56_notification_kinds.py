"""Alembic migration to add T‑56 notification kinds.

Adds the new kinds (`weekly_summary`, `budget_overrun`, `congratulations`) to the
`ck_notifications_kind_valid` check constraint and to the same constraint on the
`notification_preferences` table.
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "017_add_t56_notification_kinds"
 down_revision = "016_budgets"  # adjust if the actual previous revision differs
branch_labels = None
depends_on = None


def upgrade():
    # Update the check constraint on the notifications table
    conn = op.get_bind()
    # Fetch the existing constraint definition
    result = conn.execute(
        sa.text(
            "SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint "
            "WHERE conrelid = 'notifications'::regclass AND contype = 'c'"
        )
    ).fetchall()
    # Drop the old constraint and recreate it with the new kinds
    op.drop_constraint('ck_notifications_kind_valid', 'notifications', type_='check')
    new_kinds = (
        "'group_expense_created','group_expense_updated','group_expense_deleted','settlement_recorded',"
        "'member_joined','invitation_received','invitation_accepted','invitation_declined',"
        "'member_removed','member_left','password_changed','recurring_expense_upcoming',"
        "'recurring_expense_skipped','budget_warning','budget_exceeded',"
        "'weekly_summary','budget_overrun','congratulations'"
    )
    op.create_check_constraint(
        "ck_notifications_kind_valid",
        "notifications",
        f"kind IN ({new_kinds})",
    )

    # Update the check constraint on the notification_preferences table
    op.drop_constraint('ck_notification_preferences_kind_valid', 'notification_preferences', type_='check')
    op.create_check_constraint(
        "ck_notification_preferences_kind_valid",
        "notification_preferences",
        f"kind IN ({new_kinds})",
    )


def downgrade():
    # Revert to the previous set of kinds (without T‑56)
    op.drop_constraint('ck_notifications_kind_valid', 'notifications', type_='check')
    old_kinds = (
        "'group_expense_created','group_expense_updated','group_expense_deleted','settlement_recorded',"
        "'member_joined','invitation_received','invitation_accepted','invitation_declined',"
        "'member_removed','member_left','password_changed','recurring_expense_upcoming',"
        "'recurring_expense_skipped','budget_warning','budget_exceeded'"
    )
    op.create_check_constraint(
        "ck_notifications_kind_valid",
        "notifications",
        f"kind IN ({old_kinds})",
    )

    op.drop_constraint('ck_notification_preferences_kind_valid', 'notification_preferences', type_='check')
    op.create_check_constraint(
        "ck_notification_preferences_kind_valid",
        "notification_preferences",
        f"kind IN ({old_kinds})",
    )
