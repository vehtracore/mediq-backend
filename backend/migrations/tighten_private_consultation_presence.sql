BEGIN;

-- Replaces the membership predicate introduced by
-- add_private_consultation_presence.sql. Former participants and unpaid or
-- inactive rooms must not expose presence metadata after the HTTP/WS room is
-- no longer authorized.
CREATE OR REPLACE FUNCTION public.is_consultation_realtime_member(requested_topic text)
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = ''
AS $$
    SELECT requested_topic ~ '^chat_room_[1-9][0-9]*$'
       AND EXISTS (
            SELECT 1
              FROM public.users AS app_user
              JOIN public.appointments AS appointment
                ON appointment.id = substring(
                    requested_topic FROM '^chat_room_([1-9][0-9]*)$'
                )::integer
              LEFT JOIN public.doctors AS doctor
                ON doctor.id = appointment.doctor_id
             WHERE app_user.supabase_auth_id = (SELECT auth.uid())
               AND appointment.status = 'confirmed'
               AND appointment.payment_status = 'paid'
               AND (
                   appointment.patient_id = app_user.id
                   OR doctor.user_id = app_user.id
               )
       );
$$;

REVOKE ALL ON FUNCTION public.is_consultation_realtime_member(text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.is_consultation_realtime_member(text) TO authenticated;

COMMIT;

-- Apply after add_private_consultation_presence.sql. Then disable Supabase
-- Realtime "Allow public access" and run the staging matrix in the report.
