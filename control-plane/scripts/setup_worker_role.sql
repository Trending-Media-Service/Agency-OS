-- setup_worker_role.sql
-- ---------------------------------------------------------------------------
-- Configure the privileged WORKER database role (the one in WORKER_DATABASE_URL)
-- so it can read and write ACROSS tenants — the "bypasses RLS" role the design
-- assumes (DEPLOY.md). Cloud SQL does NOT allow the Postgres BYPASSRLS attribute,
-- so we emulate it with: (a) table/sequence GRANTs, and (b) a PERMISSIVE policy
-- scoped TO the worker role on every RLS-enabled table.
--
-- WHY THIS EXISTS: the migrations create RLS policies but no GRANTs/roles, and the
-- worker role was never granted DML — so POST /tenants (create_tenant) failed in
-- prod with: asyncpg InsufficientPrivilegeError: permission denied for table tenants.
--
-- RUN AS: the table OWNER (the role that ran the migrations) or another role that
-- can GRANT on these tables. Connect, e.g.:
--   gcloud sql connect aos-db --user=aos_app --database=agency_os
-- (use the owner you find via the inspection queries below).
--
-- INSPECT FIRST (optional, to confirm roles / ownership / RLS):
--   SELECT rolname, rolsuper, rolbypassrls, rolcanlogin FROM pg_roles ORDER BY 1;
--   SELECT tablename, tableowner FROM pg_tables WHERE schemaname='public' ORDER BY 1;
--   SELECT relname, relrowsecurity, relforcerowsecurity
--     FROM pg_class WHERE relkind='r' AND relnamespace='public'::regnamespace ORDER BY 1;
--
-- IDEMPOTENT: safe to re-run (drops/recreates the worker_bypass policy; grants are additive).
-- ---------------------------------------------------------------------------

DO $$
DECLARE
  worker_role text := 'postgres';   -- <<< set to the role used in WORKER_DATABASE_URL
  r record;
BEGIN
  -- 1. Privileges on current AND future objects in the public schema.
  EXECUTE format('GRANT USAGE ON SCHEMA public TO %I', worker_role);
  EXECUTE format('GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO %I', worker_role);
  EXECUTE format('GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO %I', worker_role);
  EXECUTE format('ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO %I', worker_role);
  EXECUTE format('ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO %I', worker_role);

  -- 2. Emulated BYPASSRLS: a permissive policy for the worker role on every
  --    RLS-enabled table. PERMISSIVE policies are OR'd, so this grants the worker
  --    unconditional access while the app role (aos_app) stays tenant-isolated.
  FOR r IN
    SELECT c.relname
    FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = 'public' AND c.relkind = 'r' AND c.relrowsecurity
  LOOP
    EXECUTE format('DROP POLICY IF EXISTS worker_bypass ON public.%I', r.relname);
    EXECUTE format(
      'CREATE POLICY worker_bypass ON public.%I AS PERMISSIVE FOR ALL TO %I USING (true) WITH CHECK (true)',
      r.relname, worker_role);
  END LOOP;
END $$;
