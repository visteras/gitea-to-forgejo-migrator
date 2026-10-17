#!/usr/bin/env python3
"""Build a partial Forgejo 17 dump from a Gitea SQLite dump."""

from __future__ import annotations

import argparse
import copy
import json
import re
import shutil
import sqlite3
import sys
import tempfile
import zipfile
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

GITEA_SQL_DUMP = "gitea-db.sql"
FORGEJO_SQL_DUMP = "forgejo-db.sql"
DATABASE = "data/gitea.db"
DATABASE_SIDECARS = (DATABASE + "-wal", DATABASE + "-shm")
ISSUE_BLEVE_INDEX = "data/indexers/issues.bleve"
GITEA_DB_VERSION = 358
# Imported run records store only the workflow filename, not its directory.
ACTION_WORKFLOW_DIRECTORY = ".gitea/workflows"
FORGEJO_METADATA = {"version", "forgejo_version", "forgejo_migration", "forgejo_sem_ver"}
SKIP_TABLES = {"action_artifact", "action_task_output"}
ACTION_JOB_PATH = re.compile(
    r"(?P<prefix>.*?/actions/runs/)(?P<run_id>[0-9]+)/jobs/(?P<job_id>[0-9]+)(?P<attempt>/attempt/[0-9]+)?"
)
COLUMN_ALIASES = {
    "repository": {"wiki_branch": "default_wiki_branch"},
    "watch": {
        "watch_selection_issues": "include_issues",
        "watch_selection_pull_requests": "include_pull_requests",
        "watch_selection_releases": "include_releases",
    },
}


def quote(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def extract_sqlite_database(archive: zipfile.ZipFile, directory: Path) -> Path:
    names = [entry.filename for entry in archive.infolist()]
    if names.count(DATABASE) != 1:
        raise ValueError(f"archive must contain exactly one {DATABASE}")

    directory.mkdir()
    for name in (DATABASE, *DATABASE_SIDECARS):
        if name in names:
            with archive.open(name) as source, (directory / Path(name).name).open("wb") as destination:
                shutil.copyfileobj(source, destination)
    return directory / "gitea.db"


def table_columns(db: sqlite3.Connection, table: str) -> dict[str, dict[str, object]]:
    return {
        row[1]: {"type": row[2], "notnull": bool(row[3]), "default": row[4]}
        for row in db.execute(f"PRAGMA table_info({quote(table)})")
    }


def table_names(db: sqlite3.Connection) -> set[str]:
    return {
        row[0]
        for row in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
    }


def database_version(db: sqlite3.Connection, table: str = "version") -> int:
    return db.execute(f"SELECT version FROM {quote(table)} WHERE id=1").fetchone()[0]


def copy_table_rows(
    source: sqlite3.Connection,
    target: sqlite3.Connection,
    table: str,
    source_columns: dict[str, dict[str, object]],
    target_columns: dict[str, dict[str, object]],
) -> int:
    aliases = COLUMN_ALIASES.get(table, {})
    pairs = [(column, column) for column in source_columns if column in target_columns]
    pairs.extend(
        (source_column, target_column)
        for target_column, source_column in aliases.items()
        if source_column in source_columns and target_column in target_columns
    )
    if not pairs:
        return 0

    source_names = ", ".join(quote(source_column) for source_column, _ in pairs)
    target_names = ", ".join(quote(target_column) for _, target_column in pairs)
    placeholders = ", ".join("?" for _ in pairs)
    cursor = source.execute(f"SELECT {source_names} FROM {quote(table)}")
    count = 0
    while rows := cursor.fetchmany(1000):
        converted_rows = []
        for row in rows:
            values = list(row)
            for index, (source_column, target_column) in enumerate(pairs):
                value = values[index]
                if table == "action_runner_token" and target_column in {"owner_id", "repo_id"} and value == 0:
                    values[index] = None
                elif table == "secret" and target_column == "data" and isinstance(value, str):
                    values[index] = sqlite3.Binary(value.encode("utf-8"))
            converted_rows.append(values)
        target.executemany(
            f"INSERT INTO {quote(table)} ({target_names}) VALUES ({placeholders})", converted_rows
        )
        count += len(converted_rows)
    return count


def column_gap_counts(db: sqlite3.Connection, table: str, column: str) -> dict[str, int]:
    qtable, qcolumn = quote(table), quote(column)
    total = db.execute(f"SELECT COUNT(*) FROM {qtable}").fetchone()[0]
    non_null = db.execute(f"SELECT COUNT(*) FROM {qtable} WHERE {qcolumn} IS NOT NULL").fetchone()[0]
    declared_type = next(row[2] for row in db.execute(f"PRAGMA table_info({qtable})") if row[1] == column).upper()
    result = {"rows": total, "non_null": non_null}
    if "INT" in declared_type or "BOOL" in declared_type:
        result["nonzero"] = db.execute(
            f"SELECT COUNT(*) FROM {qtable} WHERE {qcolumn} IS NOT NULL AND {qcolumn} != 0"
        ).fetchone()[0]
    return result


def migrate_issue_pins(source: sqlite3.Connection, target: sqlite3.Connection, source_tables: set[str]) -> int:
    if "issue_pin" not in source_tables:
        return 0
    count = 0
    for repo_id, issue_id, is_pull, pin_order in source.execute(
        "SELECT repo_id, issue_id, is_pull, pin_order FROM issue_pin"
    ):
        cursor = target.execute(
            "UPDATE issue SET pin_order=? WHERE id=? AND repo_id=? AND is_pull=?",
            (pin_order, issue_id, repo_id, is_pull),
        )
        if cursor.rowcount != 1:
            raise ValueError(f"issue_pin refers to an issue that was not migrated: issue id {issue_id}")
        count += 1
    return count


def migrate_action_status_urls(
    source: sqlite3.Connection,
    target: sqlite3.Connection,
    source_tables: set[str],
    target_tables: set[str],
) -> tuple[int, int]:
    runs = {}
    if "action_run" in source_tables:
        runs = {
            run_id: (repo_id, run_index)
            for run_id, repo_id, run_index in source.execute('SELECT id, repo_id, "index" FROM action_run')
        }

    jobs = {}
    if "action_run_job" in source_tables:
        next_job_index = {}
        for job_id, run_id in source.execute("SELECT id, run_id FROM action_run_job ORDER BY run_id, id"):
            jobs[job_id] = (run_id, next_job_index.get(run_id, 0))
            next_job_index[run_id] = jobs[job_id][1] + 1

    rewritten = 0
    unmapped = 0
    for table in ("commit_status", "commit_status_summary"):
        if table not in source_tables or table not in target_tables:
            continue
        columns = {row[1] for row in source.execute(f"PRAGMA table_info({quote(table)})")}
        if not {"id", "repo_id", "target_url"} <= columns:
            continue
        for row_id, repo_id, target_url in source.execute(
            f"SELECT id, repo_id, target_url FROM {quote(table)} WHERE target_url IS NOT NULL"
        ):
            parsed = urlsplit(target_url)
            if "/actions/runs/" not in parsed.path:
                continue
            match = ACTION_JOB_PATH.fullmatch(parsed.path)
            # shortcut: only relative status URLs are rewritten, map absolute hosts if a future dump needs it.
            if match is None or parsed.scheme or parsed.netloc:
                unmapped += 1
                continue
            run_id = int(match["run_id"])
            job_id = int(match["job_id"])
            run = runs.get(run_id)
            job = jobs.get(job_id)
            if run is None or run[0] != repo_id or job is None or job[0] != run_id:
                unmapped += 1
                continue

            new_url = urlunsplit(
                parsed._replace(path=f'{match["prefix"]}{run[1]}/jobs/{job[1]}{match["attempt"] or ""}')
            )
            if new_url == target_url:
                continue
            cursor = target.execute(
                f"UPDATE {quote(table)} SET target_url=? WHERE id=?", (new_url, row_id)
            )
            if cursor.rowcount != 1:
                raise ValueError(f"could not update Actions target URL in {table}: id {row_id}")
            rewritten += 1
    return rewritten, unmapped


def validate_action_history(source: sqlite3.Connection, source_tables: set[str]) -> int:
    if "action_run" not in source_tables:
        return 0
    if "action_run_attempt" not in source_tables:
        raise ValueError("Gitea Actions schema is missing action_run_attempt")

    attempt_count = source.execute("SELECT COUNT(*) FROM action_run_attempt").fetchone()[0]
    duplicate_attempts = source.execute(
        "SELECT COUNT(*) FROM (SELECT run_id FROM action_run_attempt GROUP BY run_id "
        "HAVING COUNT(*) != 1 OR MIN(attempt) != 1 OR MAX(attempt) != 1)"
    ).fetchone()[0]
    mismatched_attempts = source.execute(
        "SELECT COUNT(*) FROM action_run_attempt a LEFT JOIN action_run r ON r.id=a.run_id "
        "WHERE r.id IS NULL OR r.latest_attempt_id IS NOT a.id OR r.status IS NOT a.status "
        "OR r.started IS NOT a.started OR r.stopped IS NOT a.stopped "
        "OR r.created IS NOT a.created OR r.updated IS NOT a.updated "
        "OR r.trigger_user_id IS NOT a.trigger_user_id "
        "OR COALESCE(a.concurrency_group, '') != '' OR COALESCE(a.concurrency_cancel, 0) != 0"
    ).fetchone()[0]
    orphaned_attempt_pointers = source.execute(
        "SELECT COUNT(*) FROM action_run r WHERE COALESCE(r.latest_attempt_id, 0) != 0 "
        "AND NOT EXISTS (SELECT 1 FROM action_run_attempt a WHERE a.id=r.latest_attempt_id AND a.run_id=r.id)"
    ).fetchone()[0]
    invalid_job_attempts = source.execute(
        "SELECT COUNT(*) FROM action_run_job j WHERE COALESCE(j.run_attempt_id, 0) != 0 "
        "AND NOT EXISTS (SELECT 1 FROM action_run_attempt a WHERE a.id=j.run_attempt_id AND a.run_id=j.run_id)"
    ).fetchone()[0]
    if duplicate_attempts or mismatched_attempts or orphaned_attempt_pointers or invalid_job_attempts:
        raise ValueError("Actions run attempts cannot be flattened safely into the Forgejo run model")

    unsupported_runs = source.execute(
        "SELECT COUNT(*) FROM action_run WHERE COALESCE(is_scoped_run, 0) != 0 "
        "OR COALESCE(raw_concurrency, '') != '' "
        "OR COALESCE(workflow_repo_id, 0) NOT IN (0, repo_id) "
        "OR COALESCE(workflow_commit_sha, '') NOT IN ('', commit_sha)"
    ).fetchone()[0]
    unsupported_jobs = source.execute(
        "SELECT COUNT(*) FROM action_run_job WHERE COALESCE(call_payload, '') != '' "
        "OR COALESCE(call_secrets, '') != '' OR COALESCE(call_uses, '') != '' "
        "OR COALESCE(is_reusable_caller, 0) != 0 OR COALESCE(parent_job_id, 0) != 0 "
        "OR COALESCE(is_expanded, 0) != 0 OR COALESCE(is_matrix_deferred, 0) != 0 "
        "OR COALESCE(deferred_matrix_payload, '') != '' OR COALESCE(reusable_workflow_content, '') != '' "
        "OR COALESCE(max_parallel, 0) != 0 OR COALESCE(continue_on_error, 0) != 0 "
        "OR COALESCE(concurrency_cancel, 0) != 0 OR COALESCE(concurrency_group, '') != '' "
        "OR COALESCE(raw_concurrency, '') != '' OR COALESCE(token_permissions, '') != '' "
        "OR COALESCE(source_task_id, 0) != 0 "
        "OR COALESCE(workflow_source_repo_id, 0) NOT IN (0, repo_id) "
        "OR COALESCE(workflow_source_commit_sha, '') NOT IN ('', commit_sha)"
    ).fetchone()[0]
    if unsupported_runs or unsupported_jobs:
        raise ValueError("Actions history uses Gitea-only workflow features without a verified Forgejo mapping")

    for table in ("action_run", "action_run_job", "action_task", "action_task_step"):
        if table in source_tables:
            unfinished = source.execute(
                f"SELECT COUNT(*) FROM {quote(table)} WHERE status NOT IN (1, 2, 3, 4)"
            ).fetchone()[0]
            if unfinished:
                raise ValueError(f"cannot migrate non-terminal Actions history in {table}")
    if "action_task" in source_tables and source.execute(
        "SELECT COUNT(*) FROM action_task WHERE stopped=0"
    ).fetchone()[0]:
        raise ValueError("cannot migrate Actions tasks that have not stopped")
    return attempt_count


def set_gitea_workflow_directory(
    target: sqlite3.Connection, source_tables: set[str], target_tables: set[str]
) -> int:
    rows_updated = 0
    for table in ("action_run", "action_schedule"):
        if table in source_tables and table in target_tables:
            rows_updated += target.execute(
                f"UPDATE {quote(table)} SET workflow_directory=?", (ACTION_WORKFLOW_DIRECTORY,)
            ).rowcount
    return rows_updated


def migrate_dump(source_path: Path, template_path: Path, output_path: Path) -> dict[str, object]:
    source_path, template_path, output_path = map(Path, (source_path, template_path, output_path))
    report_path = output_path.with_suffix(output_path.suffix + ".report.json")
    resolved_inputs = {source_path.resolve(), template_path.resolve()}
    if output_path.resolve() in resolved_inputs:
        raise ValueError("output must be different from both input archives")
    if source_path.resolve() == template_path.resolve():
        raise ValueError("Gitea dump and Forgejo schema template must be different files")
    if output_path.exists() or report_path.exists():
        raise FileExistsError("output archive or migration report already exists")

    output_created = False
    report_created = False
    try:
        with tempfile.TemporaryDirectory(prefix="gitea-forgejo-") as temporary_directory:
            temporary_directory = Path(temporary_directory)
            with zipfile.ZipFile(source_path) as source_archive, zipfile.ZipFile(template_path) as template_archive:
                source_names = [entry.filename for entry in source_archive.infolist()]
                if source_names.count(GITEA_SQL_DUMP) != 1:
                    raise ValueError(f"Gitea archive must contain exactly one {GITEA_SQL_DUMP}")
                if FORGEJO_SQL_DUMP in source_names:
                    raise ValueError(f"Gitea archive already contains {FORGEJO_SQL_DUMP}")

                source_db_path = extract_sqlite_database(source_archive, temporary_directory / "source")
                template_db_path = extract_sqlite_database(template_archive, temporary_directory / "template")
                migrated_db_path = temporary_directory / "converted.db"
                sql_dump_path = temporary_directory / FORGEJO_SQL_DUMP

                source_db = sqlite3.connect(source_db_path)
                source_db.row_factory = sqlite3.Row
                template_db = sqlite3.connect(template_db_path)
                migrated_db = sqlite3.connect(migrated_db_path)
                template_db.backup(migrated_db)
                template_db.close()

                source_tables = table_names(source_db)
                target_tables = table_names(migrated_db)
                if not FORGEJO_METADATA <= target_tables:
                    raise ValueError("Forgejo template is missing v17 migration metadata tables")
                if database_version(migrated_db) != 305:
                    raise ValueError("Forgejo schema template must have database version 305 (Forgejo 17.0)")
                if migrated_db.execute("SELECT version FROM forgejo_version WHERE id=1").fetchone()[0] != 44:
                    raise ValueError("Forgejo schema template must have legacy migration version 44")
                if not {"version"} <= source_tables:
                    raise ValueError("Gitea SQLite database is missing its version table")

                source_schema = {table: table_columns(source_db, table) for table in source_tables}
                target_schema = {table: table_columns(migrated_db, table) for table in target_tables}
                target_version = database_version(migrated_db)
                source_version = database_version(source_db)
                if source_version != GITEA_DB_VERSION:
                    raise ValueError(f"Gitea source database must have version {GITEA_DB_VERSION}")
                flattened_run_attempts = validate_action_history(source_db, source_tables)

                migrated_db.execute("PRAGMA foreign_keys=OFF")
                with migrated_db:
                    for table in target_tables - FORGEJO_METADATA:
                        migrated_db.execute(f"DELETE FROM {quote(table)}")
                    if "sqlite_sequence" in {
                        row[0] for row in migrated_db.execute("SELECT name FROM sqlite_master WHERE type='table'")
                    }:
                        migrated_db.execute("DELETE FROM sqlite_sequence")

                    converted_rows: dict[str, int] = {}
                    skipped_tables: dict[str, dict[str, object]] = {}
                    source_only_tables: dict[str, dict[str, object]] = {}
                    source_only_columns: dict[str, dict[str, object]] = {}
                    for table in sorted(source_tables - target_tables):
                        source_only_tables[table] = {
                            "rows": source_db.execute(f"SELECT COUNT(*) FROM {quote(table)}").fetchone()[0],
                            "fields": list(source_schema[table]),
                        }
                    for table in sorted(source_tables & target_tables - FORGEJO_METADATA - {"version"}):
                        if table in SKIP_TABLES:
                            skipped_tables[table] = {
                                "rows": source_db.execute(f"SELECT COUNT(*) FROM {quote(table)}").fetchone()[0],
                                "reason": "schema/model diverges; not copied without a verified mapping",
                                "fields": list(source_schema[table]),
                            }
                            continue

                        source_columns = source_schema[table]
                        target_columns = target_schema[table]
                        aliases = COLUMN_ALIASES.get(table, {})
                        mapped_sources = set(source_columns) & set(target_columns)
                        mapped_sources.update(source for target, source in aliases.items() if target in target_columns)
                        unmapped = sorted(set(source_columns) - mapped_sources)
                        if unmapped:
                            source_only_columns[table] = {
                                column: column_gap_counts(source_db, table, column) for column in unmapped
                            }
                        converted_rows[table] = copy_table_rows(
                            source_db, migrated_db, table, source_columns, target_columns
                        )

                    action_status_urls_rewritten, action_status_urls_unmapped = migrate_action_status_urls(
                        source_db, migrated_db, source_tables, target_tables
                    )
                    pinned_issues = migrate_issue_pins(source_db, migrated_db, source_tables)
                    workflow_directories_set = set_gitea_workflow_directory(
                        migrated_db, source_tables, target_tables
                    )
                    mirror_flags_without_config = 0
                    if "mirror" in source_tables:
                        mirror_flags_without_config = source_db.execute(
                            "SELECT COUNT(*) FROM repository r WHERE r.is_mirror=1 "
                            "AND NOT EXISTS (SELECT 1 FROM mirror m WHERE m.repo_id=r.id)"
                        ).fetchone()[0]

                migrated_db.execute("PRAGMA foreign_keys=ON")
                foreign_key_errors = migrated_db.execute("PRAGMA foreign_key_check").fetchall()
                if foreign_key_errors:
                    raise ValueError(
                        f"converted database has {len(foreign_key_errors)} foreign-key violations; "
                        f"first: {tuple(foreign_key_errors[0])}"
                    )
                integrity = migrated_db.execute("PRAGMA integrity_check").fetchone()[0]
                if integrity != "ok":
                    raise ValueError(f"converted database integrity check failed: {integrity}")

                target_only_tables = sorted(target_tables - source_tables - FORGEJO_METADATA)
                target_only_columns = {
                    table: {
                        column: target_schema[table][column]
                        for column in sorted(set(target_schema[table]) - set(source_schema.get(table, {})))
                    }
                    for table in sorted(source_tables & target_tables)
                    if set(target_schema[table]) - set(source_schema.get(table, {}))
                }
                flattened_source_tables = {}
                if "action_run_attempt" in source_tables:
                    flattened_source_tables["action_run_attempt"] = {
                        "rows": flattened_run_attempts,
                        "strategy": "single attempt per run; current state is already stored in action_run",
                    }
                if "action_run_attempt_job_id_index" in source_tables:
                    flattened_source_tables["action_run_attempt_job_id_index"] = {
                        "rows": source_db.execute(
                            "SELECT COUNT(*) FROM action_run_attempt_job_id_index"
                        ).fetchone()[0],
                        "strategy": "Gitea-only allocation index; not used by Forgejo's job-handle model",
                    }

                report: dict[str, object] = {
                    "source_database_version": source_version,
                    "target_database_version": target_version,
                    "target_forgejo_migration_version": 44,
                    "converted_tables": converted_rows,
                    "converted_row_count": sum(converted_rows.values()),
                    "issue_pins_converted": pinned_issues,
                    "action_status_urls_rewritten": action_status_urls_rewritten,
                    "action_status_urls_unmapped": action_status_urls_unmapped,
                    "flattened_source_tables": flattened_source_tables,
                    "action_workflow_directory_rows_set": workflow_directories_set,
                    "source_mirror_flags_without_config": mirror_flags_without_config,
                    "skipped_tables": skipped_tables,
                    "source_only_tables": source_only_tables,
                    "source_only_columns": source_only_columns,
                    "target_only_tables": target_only_tables,
                    "target_only_columns": target_only_columns,
                    "foreign_key_violations": 0,
                    "integrity_check": integrity,
                    "transforms": [
                        "repository.default_wiki_branch -> repository.wiki_branch",
                        "watch.include_* -> watch.watch_selection_*",
                        "issue_pin -> issue.pin_order",
                        "action_run_attempt -> action_run after validating a single, matching attempt per run",
                        "Gitea Actions workflow directory -> .gitea/workflows",
                        "action_run_job.handle/job_namespace and action_task.runner_request_key remain NULL for terminal history",
                        "verified Gitea Actions status URLs (run/job IDs) -> Forgejo run indexes/job positions",
                        "action_runner_token owner_id/repo_id zero sentinel -> NULL",
                        "secret.data TEXT -> UTF-8 BLOB bytes; source app.ini is preserved",
                        "mirror.remote_address -> Forgejo's encrypted recovery from the archived Git origin URL",
                        "mirror.encrypted_remote_address remains NULL until Forgejo performs that recovery",
                        "mirror.last_sync_unix has no target column; mirror.updated_unix is copied unchanged",
                    ],
                }

                with sql_dump_path.open("w", encoding="utf-8", newline="\n") as sql_dump:
                    for line in migrated_db.iterdump():
                        sql_dump.write(line + "\n")
                migrated_db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                migrated_db.close()
                source_db.close()

                skipped_index_paths = []
                with zipfile.ZipFile(source_path) as source_archive, zipfile.ZipFile(
                    output_path, "x", compression=zipfile.ZIP_DEFLATED, allowZip64=True
                ) as output_archive:
                    output_created = True
                    output_archive.comment = source_archive.comment
                    replaced = {GITEA_SQL_DUMP, FORGEJO_SQL_DUMP, DATABASE, *DATABASE_SIDECARS}
                    for entry in source_archive.infolist():
                        if entry.filename in replaced:
                            continue
                        if (
                            entry.filename.rstrip("/") == ISSUE_BLEVE_INDEX
                            or entry.filename.startswith(ISSUE_BLEVE_INDEX + "/")
                        ):
                            skipped_index_paths.append(entry.filename)
                            continue
                        with source_archive.open(entry) as source_file:
                            with output_archive.open(copy.copy(entry), "w") as output_file:
                                shutil.copyfileobj(source_file, output_file, length=1024 * 1024)
                    output_archive.write(migrated_db_path, DATABASE, compress_type=zipfile.ZIP_DEFLATED)
                    output_archive.write(sql_dump_path, FORGEJO_SQL_DUMP, compress_type=zipfile.ZIP_DEFLATED)

                report["skipped_incompatible_index_paths"] = skipped_index_paths
                with report_path.open("x", encoding="utf-8") as report_file:
                    report_created = True
                    json.dump(report, report_file, indent=2)
                    report_file.write("\n")
                return report
    except BaseException:
        if output_created:
            output_path.unlink(missing_ok=True)
        if report_created:
            report_path.unlink(missing_ok=True)
        raise


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Create a partial Forgejo 17.0 dump by importing same-name SQLite tables/columns "
            "from Gitea. Unmapped and skipped data is reported; this is a best-effort migration."
        )
    )
    parser.add_argument("gitea_dump", type=Path, help="input Gitea dump ZIP (SQLite)")
    parser.add_argument("forgejo_template", type=Path, help="Forgejo 17.0 dump ZIP used for its schema")
    parser.add_argument("output_dump", type=Path, help="output ZIP (must not already exist)")
    args = parser.parse_args()

    try:
        report = migrate_dump(args.gitea_dump, args.forgejo_template, args.output_dump)
    except (OSError, RuntimeError, ValueError, sqlite3.Error, zipfile.BadZipFile, zipfile.LargeZipFile) as error:
        parser.error(str(error))

    print(f"Partial Forgejo dump written to {args.output_dump}")
    print(f"Migrated {report['converted_row_count']} rows; report: {args.output_dump}.report.json")
    print("This is a best-effort database conversion; test the restored instance before use.", file=sys.stderr)


if __name__ == "__main__":
    main()
