BEGIN;

-- Bind each application user to the immutable Supabase Auth UUID used by
-- auth.uid(). Unmatched or ambiguous identities remain unable to use presence.
ALTER TABLE public.users
    ADD COLUMN IF NOT EXISTS supabase_auth_id UUID;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM public.users AS app_user
        JOIN auth.users AS auth_user
          ON lower(auth_user.email) = lower(app_user.email)
        GROUP BY app_user.id
        HAVING count(*) > 1
    ) THEN
        RAISE EXCEPTION 'Ambiguous Supabase identities exist for an MDQ+ user';
    END IF;
END
$$;

UPDATE public.users AS app_user
SET supabase_auth_id = auth_user.id
FROM auth.users AS auth_user
WHERE app_user.supabase_auth_id IS NULL
  AND lower(auth_user.email) = lower(app_user.email);

CREATE UNIQUE INDEX IF NOT EXISTS uq_users_supabase_auth_id
    ON public.users(supabase_auth_id)
    WHERE supabase_auth_id IS NOT NULL;

CREATE OR REPLACE FUNCTION public.set_public_user_supabase_auth_id()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
BEGIN
    SELECT auth_user.id
      INTO NEW.supabase_auth_id
      FROM auth.users AS auth_user
     WHERE lower(auth_user.email) = lower(NEW.email)
     LIMIT 1;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS set_public_user_supabase_auth_id ON public.users;
CREATE TRIGGER set_public_user_supabase_auth_id
BEFORE INSERT OR UPDATE OF email ON public.users
FOR EACH ROW
EXECUTE FUNCTION public.set_public_user_supabase_auth_id();

CREATE OR REPLACE FUNCTION public.sync_auth_user_to_public_user()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
BEGIN
    UPDATE public.users AS app_user
       SET supabase_auth_id = NEW.id
     WHERE lower(app_user.email) = lower(NEW.email)
       AND (
           app_user.supabase_auth_id IS NULL
           OR app_user.supabase_auth_id = NEW.id
       );
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS sync_auth_user_to_public_user ON auth.users;
CREATE TRIGGER sync_auth_user_to_public_user
AFTER INSERT OR UPDATE OF email ON auth.users
FOR EACH ROW
EXECUTE FUNCTION public.sync_auth_user_to_public_user();

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
               AND (
                   appointment.patient_id = app_user.id
                   OR doctor.user_id = app_user.id
               )
       );
$$;

REVOKE ALL ON FUNCTION public.is_consultation_realtime_member(text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.is_consultation_realtime_member(text) TO authenticated;

-- These restrictive guards prevent an existing broad permissive policy from
-- bypassing membership for consultation topics. Other Realtime topics retain
-- their existing policy behavior.
DROP POLICY IF EXISTS "consultation topics require presence membership for receive"
    ON realtime.messages;
CREATE POLICY "consultation topics require presence membership for receive"
ON realtime.messages
AS RESTRICTIVE
FOR SELECT
TO authenticated
USING (
    (SELECT realtime.topic()) !~ '^chat_room_'
    OR (
        realtime.messages.extension = 'presence'
        AND public.is_consultation_realtime_member((SELECT realtime.topic()))
    )
);

DROP POLICY IF EXISTS "consultation topics require presence membership for publish"
    ON realtime.messages;
CREATE POLICY "consultation topics require presence membership for publish"
ON realtime.messages
AS RESTRICTIVE
FOR INSERT
TO authenticated
WITH CHECK (
    (SELECT realtime.topic()) !~ '^chat_room_'
    OR (
        realtime.messages.extension = 'presence'
        AND public.is_consultation_realtime_member((SELECT realtime.topic()))
    )
);

DROP POLICY IF EXISTS "consultation members can receive presence"
    ON realtime.messages;
CREATE POLICY "consultation members can receive presence"
ON realtime.messages
FOR SELECT
TO authenticated
USING (
    realtime.messages.extension = 'presence'
    AND public.is_consultation_realtime_member((SELECT realtime.topic()))
);

DROP POLICY IF EXISTS "consultation members can publish presence"
    ON realtime.messages;
CREATE POLICY "consultation members can publish presence"
ON realtime.messages
FOR INSERT
TO authenticated
WITH CHECK (
    realtime.messages.extension = 'presence'
    AND public.is_consultation_realtime_member((SELECT realtime.topic()))
);

COMMIT;

-- Deployment requirement outside SQL: disable "Allow public access" in the
-- Supabase Realtime Settings after this migration is applied and clients with
-- private-channel support are released. This migration must not be executed by
-- application startup code.
