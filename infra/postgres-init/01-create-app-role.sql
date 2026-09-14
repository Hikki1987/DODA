-- ADR-005 / NFR-ISO-001: FORCE ROW LEVEL SECURITY is meaningless unless the
-- role the application actually connects as is a plain, unprivileged role.
-- PostgreSQL's own bootstrap superuser (created via POSTGRES_USER by the
-- official postgres image) ALWAYS bypasses row security, FORCE or not —
-- that is a hard PostgreSQL rule, not a configuration option. So the
-- application must never connect as that bootstrap role in anything but
-- Alembic migrations (which need superuser to CREATE EXTENSION vector and
-- run arbitrary DDL). This script creates a second, deliberately
-- unprivileged role for the application's actual runtime connections.
--
-- Idempotent: docker-entrypoint-initdb.d only runs this once per fresh
-- data volume anyway, but CI also invokes it explicitly via psql (service
-- containers can't mount a repo file that hasn't been checked out yet),
-- so it must tolerate being run more than once.
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'doda_app') THEN
        CREATE ROLE doda_app LOGIN PASSWORD 'doda_app' NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
    END IF;
END
$$;

GRANT CONNECT ON DATABASE doda TO doda_app;
GRANT USAGE ON SCHEMA public TO doda_app;

-- Tables that already exist (e.g. when this runs again after migrations
-- already created some, as happens in CI).
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO doda_app;

-- Tables Alembic creates in the future, still owned by the bootstrap role
-- running migrations — without this, each new migration would silently
-- leave doda_app unable to touch its new table until someone remembered
-- to add a GRANT by hand.
ALTER DEFAULT PRIVILEGES FOR ROLE doda IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO doda_app;
