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


def provision_role(
    connection: psycopg.Connection,
    role: str,
    password: str,
) -> None:
    exists = connection.execute(
        "SELECT 1 FROM pg_roles WHERE rolname = %s", (role,)
    ).fetchone()
    if not exists:
        connection.execute(sql.SQL("CREATE ROLE {}").format(sql.Identifier(role)))
    # Role DDL needs SQL quoting, never printed because it contains a password.
    connection.execute(
        sql.SQL(
            "ALTER ROLE {} WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE "
            "NOINHERIT NOREPLICATION NOBYPASSRLS PASSWORD {}"
        ).format(
            sql.Identifier(role),
            sql.Literal(password),
        )
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
        # Re-provisioning must preserve every protected business table's grants.
        for table in (
            "catalog_catalogitem",
            "orders_purchaseorder",
            "orders_purchaseorderline",
            "orders_orderdocument",
            "orders_orderdocumentreview",
        ):
            if (
                connection.execute(
                    "SELECT to_regclass(%s)", (f"public.{table}",)
                ).fetchone()[0]
                is not None
            ):
                connection.execute(
                    sql.SQL("REVOKE DELETE, TRUNCATE ON TABLE {}.{} FROM {}").format(
                        sql.Identifier("public"), sql.Identifier(table), app
                    )
                )
        # This receipt's identity is immutable to runtime callers. The broad
        # table grants above and any old column grants must both be reset.
        receipt = "catalog_catalogimportreceipt"
        if (
            connection.execute(
                "SELECT to_regclass(%s)", (f"public.{receipt}",)
            ).fetchone()[0]
            is not None
        ):
            columns = sql.SQL(", ").join(
                sql.Identifier(column)
                for column in (
                    "id",
                    "organization_id",
                    "initiating_user_id",
                    "idempotency_key",
                    "request_fingerprint",
                    "mode",
                    "contract_identifier",
                    "state",
                    "response_payload",
                    "created_at",
                    "completed_at",
                )
            )
            for statement in (
                sql.SQL("REVOKE ALL ON TABLE public.{} FROM PUBLIC, {}").format(
                    sql.Identifier(receipt), app
                ),
                sql.SQL("REVOKE ALL ({}) ON TABLE public.{} FROM PUBLIC, {}").format(
                    columns, sql.Identifier(receipt), app
                ),
                sql.SQL("GRANT SELECT, INSERT ON TABLE public.{} TO {}").format(
                    sql.Identifier(receipt), app
                ),
                sql.SQL(
                    "GRANT UPDATE (state, response_payload, completed_at) "
                    "ON TABLE public.{} TO {}"
                ).format(sql.Identifier(receipt), app),
            ):
                connection.execute(statement)

        draft_tables = (
            (
                "orders_draftorder",
                (
                    "id",
                    "organization_id",
                    "initiating_user_id",
                    "status",
                    "source_type",
                    "customer_name",
                    "customer_reference",
                    "original_intake_text",
                    "created_at",
                    "updated_at",
                ),
                (
                    "customer_name",
                    "customer_reference",
                    "original_intake_text",
                    "updated_at",
                ),
            ),
            (
                "orders_draftorderline",
                (
                    "id",
                    "organization_id",
                    "order_id",
                    "position",
                    "requested_sku",
                    "requested_description",
                    "quantity",
                    "unit",
                    "catalogue_item_id",
                    "catalogue_sku_snapshot",
                    "catalogue_description_snapshot",
                    "created_at",
                    "updated_at",
                ),
                (
                    "position",
                    "requested_sku",
                    "requested_description",
                    "quantity",
                    "unit",
                    "catalogue_item_id",
                    "catalogue_sku_snapshot",
                    "catalogue_description_snapshot",
                    "updated_at",
                ),
            ),
        )
        for table, all_columns, mutable_columns in draft_tables:
            if (
                connection.execute(
                    "SELECT to_regclass(%s)", (f"public.{table}",)
                ).fetchone()[0]
                is None
            ):
                continue
            name = sql.Identifier(table)
            columns = sql.SQL(", ").join(map(sql.Identifier, all_columns))
            updates = sql.SQL(", ").join(map(sql.Identifier, mutable_columns))
            for statement in (
                sql.SQL("REVOKE ALL ON TABLE public.{} FROM PUBLIC, {}").format(
                    name, app
                ),
                sql.SQL("REVOKE ALL ({}) ON TABLE public.{} FROM PUBLIC, {}").format(
                    columns, name, app
                ),
                sql.SQL("GRANT SELECT, INSERT ON TABLE public.{} TO {}").format(
                    name, app
                ),
                sql.SQL("GRANT UPDATE ({}) ON TABLE public.{} TO {}").format(
                    updates, name, app
                ),
            ):
                connection.execute(statement)


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
