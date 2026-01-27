BEGIN;

ALTER TABLE public."user" add column user_uuid uuid;
-- UPDATE "user" set user_uuid = '1b77cbd5-d300-4d15-9984-7818441a8161'::uuid where email='admin@odpem.gov.jm';


COMMIT;