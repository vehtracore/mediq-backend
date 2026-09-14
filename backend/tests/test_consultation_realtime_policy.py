from pathlib import Path


MIGRATION = (
    Path(__file__).resolve().parents[1]
    / "migrations"
    / "add_private_consultation_presence.sql"
)
TIGHTENING_MIGRATION = (
    Path(__file__).resolve().parents[1]
    / "migrations"
    / "tighten_private_consultation_presence.sql"
)


def _migration_sql() -> str:
    return MIGRATION.read_text(encoding="utf-8").lower()


def test_policy_maps_auth_uid_to_patient_or_assigned_doctor() -> None:
    sql = _migration_sql()

    assert "app_user.supabase_auth_id = (select auth.uid())" in sql
    assert "appointment.patient_id = app_user.id" in sql
    assert "doctor.user_id = app_user.id" in sql
    assert "^chat_room_[1-9][0-9]*$" in sql


def test_policy_grants_presence_only_receive_and_publish() -> None:
    sql = _migration_sql()

    assert "on realtime.messages\nfor select\nto authenticated" in sql
    assert "on realtime.messages\nfor insert\nto authenticated" in sql
    assert sql.count("realtime.messages.extension = 'presence'") == 4
    assert "realtime.messages.extension = 'broadcast'" not in sql
    assert sql.count("as restrictive") == 2


def test_policy_denies_unlinked_identities_by_default() -> None:
    sql = _migration_sql()

    assert "add column if not exists supabase_auth_id uuid" in sql
    assert "create unique index if not exists uq_users_supabase_auth_id" in sql
    assert "grant execute on function public.is_consultation_realtime_member(text) to authenticated" in sql
    assert "grant select on public.appointments" not in sql


def test_policy_denies_former_or_unpaid_consultation_participants() -> None:
    sql = TIGHTENING_MIGRATION.read_text(encoding="utf-8").lower()

    assert "appointment.status = 'confirmed'" in sql
    assert "appointment.payment_status = 'paid'" in sql
    assert "create or replace function public.is_consultation_realtime_member" in sql
