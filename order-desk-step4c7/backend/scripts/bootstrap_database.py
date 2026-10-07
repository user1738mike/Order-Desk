"""Local-only provisioning. Administrator secrets stay in this one-shot process."""

import os
import sys
from dataclasses import dataclass

import psycopg
from psycopg import sql


def required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ValueError(f"Set {name} before provisioning the database.")
    return value


@dataclass(frozen=True)
class Configuration:
    host: str
    port: int
    database: str
    admin: str
    admin_password: str
    app: str
    app_password: str
    migrator: str
    migrator_password: str
    test_database: str = "test_orderdesk"

    @classmethod
    def from_environment(cls) -> Configuration:
        config = cls(
            host=required("DATABASE_HOST"),
            port=int(required("DATABASE_PORT")),
            database=required("DATABASE_NAME"),
            admin=required("DATABASE_ADMIN_USER"),
            admin_password=required("DATABASE_ADMIN_PASSWORD"),
            app=required("DATABASE_APP_USER"),
            app_password=required("DATABASE_APP_PASSWORD"),
            migrator=required("DATABASE_MIGRATION_USER"),
            migrator_password=required("DATABASE_MIGRATION_PASSWORD"),
        )
        if config.database != "orderdesk":
            raise ValueError(
                "This local helper only provisions the orderdesk database."
            )
        if len({config.admin, config.app, config.migrator}) != 3:
            raise ValueError("Administrator, migration, and runtime roles must differ.")
        if any(
            len(role.encode("utf-8")) > 63 or role.lower().startswith("pg_")
            for role in (config.app, config.migrator)
        ):
            raise ValueError(
                "Application role names must be valid PostgreSQL identifiers."
            )
        if not 1 <= config.port <= 65535:
            raise ValueError("DATABASE_PORT must be a valid TCP port.")
        return config

    def connection(self, database: str) -> psycopg.Connection:
        return psycopg.connect(
            host=self.host,
            port=self.port,
            dbname=database,
            user=self.admin,
            password=self.admin_password,
            connect_timeout=3,
            autocommit=True,
        )


def provision_role(connection: psycopg.Connection, role: str, password: str) -> None:
    exists = connection.execute(
        "SELECT 1 FROM pg_roles WHERE rolname = %s", (role,)
    ).fetchone()
    if not exists:
        connection.execute(sql.SQL("CREATE ROLE {}").format(sql.Identifier(role)))
    # Role DDL needs SQL quoting rather than ordinary bind parameters. Never print
    # the resulting statement: it contains a password.
    connection.execute(
        sql.SQL(
            "ALTER ROLE {} WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE "
            "NOINHERIT NOREPLICATION NOBYPASSRLS PASSWORD {}"
        ).format(sql.Identifier(role), sql.Literal(password))
    )
    membership = connection.execute(
        "SELECT 1 FROM pg_auth_members m JOIN pg_roles r ON r.oid = m.member "
        "WHERE r.rolname = %s LIMIT 1",
        (role,),
    ).fetchone()
    if membership:
        raise ValueError("Application roles must not have memberships in other roles.")


def provision_grants(config: Configuration, database: str) -> None:
    with config.connection(database) as connection:
        db = sql.Identifier(database)
        app = sql.Identifier(config.app)
        migrator = sql.Identifier(config.migrator)
        statements = [
            sql.SQL("REVOKE ALL ON DATABASE {} FROM PUBLIC").format(db),
            sql.SQL("GRANT CONNECT ON DATABASE {} TO {}, {}").format(db, app, migrator),
            sql.SQL("REVOKE CREATE ON SCHEMA public FROM PUBLIC"),
            sql.SQL("GRANT USAGE, CREATE ON SCHEMA public TO {}").format(migrator),
            sql.SQL("REVOKE CREATE ON SCHEMA public FROM {}").format(app),
            sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(app),
            sql.SQL("REVOKE ALL ON ALL TABLES IN SCHEMA public FROM PUBLIC"),
            sql.SQL(
                "GRANT SELECT, INSERT, UPDATE, DELETE "
                "ON ALL TABLES IN SCHEMA public TO {}"
            ).format(app),
            sql.SQL(
                "GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {}"
            ).format(app),
            sql.SQL(
                "ALTER DEFAULT PRIVILEGES FOR ROLE {} IN SCHEMA public "
                "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {}"
            ).format(migrator, app),
            sql.SQL(
                "ALTER DEFAULT PRIVILEGES FOR ROLE {} IN SCHEMA public "
                "GRANT USAGE, SELECT ON SEQUENCES TO {}"
            ).format(migrator, app),
        ]
        for statement in statements:
            connection.execute(statement)
        # The first RLS migration narrows the default CRUD grant. Preserve that
        # restriction if local provisioning is run again after the table exists.
        if (
            connection.execute(
                "SELECT to_regclass('public.catalog_catalogitem')"
            ).fetchone()[0]
            is not None
        ):
            connection.execute(
                sql.SQL(
                    "REVOKE DELETE, TRUNCATE ON TABLE public.catalog_catalogitem "
                    "FROM {}"
                ).format(app)
            )


def bootstrap(config: Configuration) -> None:
    with config.connection(config.database) as connection:
        # Serialize repeated helper runs. Closing the connection releases the lock.
        connection.execute("SELECT pg_advisory_lock(714753829)")
        provision_role(connection, config.migrator, config.migrator_password)
        provision_role(connection, config.app, config.app_password)
        owner = connection.execute(
            "SELECT pg_get_userbyid(datdba) FROM pg_database WHERE datname = %s",
            (config.test_database,),
        ).fetchone()
        if owner is None:
            connection.execute(
                sql.SQL("CREATE DATABASE {} OWNER {}").format(
                    sql.Identifier(config.test_database),
                    sql.Identifier(config.migrator),
                )
            )
        elif owner[0] != config.migrator:
            raise ValueError("The existing test database has an unexpected owner.")
        provision_grants(config, config.database)
        provision_grants(config, config.test_database)


def main() -> int:
    try:
        bootstrap(Configuration.from_environment())
    except ValueError as error:
        print(str(error), file=sys.stderr)
        return 1
    except psycopg.Error:
        print(
            "Database setup failed. Check connectivity and administrator credentials.",
            file=sys.stderr,
        )
        return 1
    print("Provisioned local runtime, migration, and test database permissions.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
