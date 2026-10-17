import json
import sqlite3
import tempfile
import unittest
import zipfile
from pathlib import Path

from convert_gitea_dump_to_forgejo import migrate_dump, validate_action_history


def create_database(path, schema, inserts):
    db = sqlite3.connect(path)
    db.executescript(schema)
    for statement, rows in inserts:
        db.executemany(statement, rows)
    db.commit()
    db.close()


def write_dump(path, database, sql_name):
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(sql_name, b"placeholder SQL dump")
        archive.write(database, "data/gitea.db")
        archive.writestr("app.ini", b"[security]\nSECRET_KEY = retained\n")
        archive.writestr("repos/example.git/HEAD", b"ref: refs/heads/main\n")
        archive.writestr(
            "repos/alice/project.git/config",
            b'[core]\n\trepositoryformatversion = 0\n\tbare = true\n[remote "origin"]\n\turl = https://alice:fake-token@upstream.example.test/repo.git\n',
        )
        archive.writestr("data/indexers/issues.bleve/index_meta.json", b"Gitea-only analyzer")


class MigrateGiteaDumpTests(unittest.TestCase):
    def test_migrates_common_fields_and_reports_unmapped_data(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            source_db, template_db = temp / "source.db", temp / "template.db"
            source_zip, template_zip, output_zip = temp / "gitea.zip", temp / "forgejo.zip", temp / "output.zip"
            create_database(
                source_db,
                """
                CREATE TABLE version (id INTEGER PRIMARY KEY, version INTEGER NOT NULL);
                CREATE TABLE user (id INTEGER PRIMARY KEY, name TEXT, email TEXT);
                CREATE TABLE repository (id INTEGER PRIMARY KEY, name TEXT, owner_name TEXT, default_wiki_branch TEXT, is_mirror INTEGER);
                CREATE TABLE watch (id INTEGER PRIMARY KEY, include_issues INTEGER, include_pull_requests INTEGER, include_releases INTEGER, mode INTEGER);
                CREATE TABLE issue (id INTEGER PRIMARY KEY, repo_id INTEGER, is_pull INTEGER, time_estimate INTEGER);
                CREATE TABLE issue_pin (repo_id INTEGER, issue_id INTEGER, is_pull INTEGER, pin_order INTEGER);
                CREATE TABLE action_run (
                    id INTEGER PRIMARY KEY, title TEXT, repo_id INTEGER, "index" INTEGER, workflow_id TEXT, commit_sha TEXT,
                    status INTEGER, trigger_user_id INTEGER, started INTEGER, stopped INTEGER, created INTEGER, updated INTEGER,
                    previous_duration INTEGER, latest_attempt_id INTEGER, workflow_repo_id INTEGER,
                    workflow_commit_sha TEXT, is_scoped_run INTEGER, raw_concurrency TEXT
                );
                CREATE TABLE action_run_attempt (
                    id INTEGER PRIMARY KEY, repo_id INTEGER, run_id INTEGER, attempt INTEGER, trigger_user_id INTEGER,
                    concurrency_group TEXT, concurrency_cancel INTEGER, status INTEGER, started INTEGER, stopped INTEGER,
                    created INTEGER, updated INTEGER
                );
                CREATE TABLE action_run_attempt_job_id_index (group_id INTEGER, max_index INTEGER);
                CREATE TABLE action_run_index (group_id INTEGER PRIMARY KEY, max_index INTEGER);
                CREATE TABLE commit_status (id INTEGER PRIMARY KEY, repo_id INTEGER, target_url TEXT);
                CREATE TABLE commit_status_summary (id INTEGER PRIMARY KEY, repo_id INTEGER, target_url TEXT);
                CREATE TABLE action_run_job (
                    id INTEGER PRIMARY KEY, run_id INTEGER, repo_id INTEGER, owner_id INTEGER, commit_sha TEXT,
                    is_fork_pull_request INTEGER, name TEXT, attempt INTEGER, workflow_payload TEXT, job_id TEXT,
                    needs TEXT, runs_on TEXT, task_id INTEGER, status INTEGER, started INTEGER, stopped INTEGER,
                    created INTEGER, updated INTEGER, run_attempt_id INTEGER, attempt_job_id INTEGER,
                    call_payload TEXT DEFAULT '', call_secrets TEXT DEFAULT '', call_uses TEXT DEFAULT '',
                    concurrency_cancel INTEGER DEFAULT 0, concurrency_group TEXT DEFAULT '',
                    continue_on_error INTEGER DEFAULT 0, deferred_matrix_payload TEXT DEFAULT '',
                    is_concurrency_evaluated INTEGER DEFAULT 0, is_expanded INTEGER DEFAULT 0,
                    is_matrix_deferred INTEGER DEFAULT 0, is_reusable_caller INTEGER DEFAULT 0,
                    max_parallel INTEGER DEFAULT 0, parent_job_id INTEGER DEFAULT 0,
                    raw_concurrency TEXT DEFAULT '', reusable_workflow_content TEXT DEFAULT '',
                    source_task_id INTEGER DEFAULT 0, token_permissions TEXT DEFAULT '',
                    workflow_source_repo_id INTEGER DEFAULT 0, workflow_source_commit_sha TEXT DEFAULT ''
                );
                CREATE TABLE action_task (
                    id INTEGER PRIMARY KEY, job_id INTEGER, attempt INTEGER, runner_id INTEGER, status INTEGER,
                    started INTEGER, stopped INTEGER, repo_id INTEGER, owner_id INTEGER, commit_sha TEXT,
                    is_fork_pull_request INTEGER, token_hash TEXT, token_salt TEXT, token_last_eight TEXT,
                    log_filename TEXT, log_in_storage INTEGER, log_length INTEGER, log_size INTEGER,
                    log_indexes BLOB, log_expired INTEGER, created INTEGER, updated INTEGER
                );
                CREATE TABLE action_task_step (
                    id INTEGER PRIMARY KEY, name TEXT, task_id INTEGER, "index" INTEGER, repo_id INTEGER,
                    status INTEGER, log_index INTEGER, log_length INTEGER, started INTEGER, stopped INTEGER,
                    created INTEGER, updated INTEGER
                );
                CREATE TABLE action_tasks_version (
                    id INTEGER PRIMARY KEY, owner_id INTEGER, repo_id INTEGER, version INTEGER,
                    created_unix INTEGER, updated_unix INTEGER
                );
                CREATE TABLE action_runner_token (id INTEGER PRIMARY KEY, owner_id INTEGER, repo_id INTEGER, token TEXT, deleted INTEGER);
                CREATE TABLE secret (id INTEGER PRIMARY KEY, data TEXT, description TEXT);
                CREATE TABLE repo_license (id INTEGER PRIMARY KEY, license TEXT);
                CREATE TABLE mirror (
                    id INTEGER PRIMARY KEY, repo_id INTEGER, interval INTEGER, enable_prune INTEGER,
                    updated_unix INTEGER, next_update_unix INTEGER, lfs_enabled INTEGER, lfs_endpoint TEXT,
                    remote_address TEXT, last_sync_unix INTEGER
                );
                """,
                [
                    ("INSERT INTO version VALUES (?, ?)", [(1, 358)]),
                    ("INSERT INTO user VALUES (?, ?, ?)", [(1, "alice", "alice@example.test")]),
                    ("INSERT INTO repository VALUES (?, ?, ?, ?, ?)", [
                        (7, "project", "alice", "main-wiki", 1),
                        (8, "orphan", "alice", "main-wiki", 1),
                    ]),
                    ("INSERT INTO watch VALUES (?, ?, ?, ?, ?)", [(1, 1, 1, 1, 1)]),
                    ("INSERT INTO issue VALUES (?, ?, ?, ?)", [(9, 7, 0, 0)]),
                    ("INSERT INTO issue_pin VALUES (?, ?, ?, ?)", [(7, 9, 0, 2)]),
                    (
                        "INSERT INTO action_run VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        [(1, "completed run", 7, 42, "ci.yml", "sha", 1, 1, 100, 200, 90, 200, 0, 1000, 7, "sha", 0, "")],
                    ),
                    (
                        "INSERT INTO action_run_attempt VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        [(1000, 7, 1, 1, 1, "", 0, 1, 100, 200, 90, 200)],
                    ),
                    ("INSERT INTO action_run_attempt_job_id_index VALUES (?, ?)", [(1, 1)]),
                    ("INSERT INTO action_run_index VALUES (?, ?)", [(7, 42)]),
                    ("INSERT INTO commit_status VALUES (?, ?, ?)", [
                        (1, 7, "/alice/project/actions/runs/1/jobs/2000"),
                        (2, 7, "/alice/project/actions/runs/404/jobs/999"),
                        (3, 7, "/alice/project/actions/runs/1/jobs/2001"),
                    ]),
                    ("INSERT INTO commit_status_summary VALUES (?, ?, ?)", [
                        (1, 7, "/alice/project/actions/runs/1/jobs/2001"),
                    ]),
                    (
                        "INSERT INTO action_run_job (id, run_id, repo_id, owner_id, commit_sha, is_fork_pull_request, name, attempt, workflow_payload, job_id, needs, runs_on, task_id, status, started, stopped, created, updated, run_attempt_id, attempt_job_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        [
                            (2000, 1, 7, 1, "sha", 0, "build", 2, "name: CI\\njobs:\\n  build:\\n    runs-on: linux\\n    steps: []\\n", "build", "[]", '["linux"]', 3000, 1, 110, 190, 100, 190, 1000, 3000),
                            (2001, 1, 7, 1, "sha", 0, "deploy", 2, "name: CI\\njobs:\\n  deploy:\\n    runs-on: linux\\n    steps: []\\n", "deploy", "[]", '["linux"]', 3001, 1, 110, 190, 100, 190, 1000, 3001),
                        ],
                    ),
                    (
                        "INSERT INTO action_task VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        [(3000, 2000, 2, 1, 1, 120, 180, 7, 1, "sha", 0, "hash", "salt", "12345678", "", 0, 0, 0, b"", 0, 110, 180)],
                    ),
                    (
                        "INSERT INTO action_task_step VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        [(4000, "Build", 3000, 0, 7, 1, 0, 1, 125, 175, 120, 175)],
                    ),
                    ("INSERT INTO action_tasks_version VALUES (?, ?, ?, ?, ?, ?)", [(1, 1, 7, 3, 90, 200)]),
                    ("INSERT INTO action_runner_token VALUES (?, ?, ?, ?, ?)", [(1, 0, 0, "token-hash", None)]),
                    ("INSERT INTO secret VALUES (?, ?, ?)", [(1, "encrypted", "description")]),
                    ("INSERT INTO repo_license VALUES (?, ?)", [(1, "MIT")]),
                    (
                        "INSERT INTO mirror VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        [(1, 7, 86400, 1, 100, 200, 0, "", "https://upstream.example.test/repo.git", 180)],
                    ),
                ],
            )
            create_database(
                template_db,
                """
                CREATE TABLE version (id INTEGER PRIMARY KEY, version INTEGER NOT NULL);
                CREATE TABLE forgejo_version (id INTEGER PRIMARY KEY, version INTEGER NOT NULL);
                CREATE TABLE forgejo_migration (id TEXT PRIMARY KEY, created_unix INTEGER);
                CREATE TABLE forgejo_sem_ver (version TEXT);
                CREATE TABLE user (id INTEGER PRIMARY KEY, name TEXT, pronouns TEXT);
                CREATE TABLE repository (id INTEGER PRIMARY KEY, name TEXT, owner_name TEXT, wiki_branch TEXT, is_mirror INTEGER);
                CREATE TABLE mirror (
                    id INTEGER PRIMARY KEY, repo_id INTEGER, interval INTEGER, enable_prune INTEGER,
                    updated_unix INTEGER, next_update_unix INTEGER, lfs_enabled INTEGER, lfs_endpoint TEXT,
                    encrypted_remote_address BLOB
                );
                CREATE TABLE watch (id INTEGER PRIMARY KEY, watch_selection_issues INTEGER DEFAULT TRUE, watch_selection_pull_requests INTEGER DEFAULT TRUE, watch_selection_releases INTEGER DEFAULT TRUE);
                CREATE TABLE issue (id INTEGER PRIMARY KEY, repo_id INTEGER, is_pull INTEGER, pin_order INTEGER DEFAULT 0);
                CREATE TABLE action_run (
                    id INTEGER PRIMARY KEY, title TEXT, repo_id INTEGER, "index" INTEGER, workflow_id TEXT, commit_sha TEXT,
                    status INTEGER, trigger_user_id INTEGER, started INTEGER, stopped INTEGER, created INTEGER, updated INTEGER,
                    previous_duration INTEGER, workflow_directory TEXT NOT NULL DEFAULT '.forgejo/workflows',
                    workflow_source_commit TEXT
                );
                CREATE TABLE action_run_index (group_id INTEGER PRIMARY KEY, max_index INTEGER);
                CREATE TABLE commit_status (id INTEGER PRIMARY KEY, repo_id INTEGER, target_url TEXT);
                CREATE TABLE commit_status_summary (id INTEGER PRIMARY KEY, repo_id INTEGER, target_url TEXT);
                CREATE TABLE action_run_job (
                    id INTEGER PRIMARY KEY, run_id INTEGER REFERENCES action_run(id), repo_id INTEGER,
                    owner_id INTEGER, commit_sha TEXT, is_fork_pull_request INTEGER, name TEXT, attempt INTEGER,
                    workflow_payload TEXT, job_id TEXT, needs TEXT, runs_on TEXT, task_id INTEGER, status INTEGER,
                    started INTEGER, stopped INTEGER, created INTEGER, updated INTEGER, handle TEXT UNIQUE,
                    job_namespace TEXT
                );
                CREATE TABLE action_task (
                    id INTEGER PRIMARY KEY, job_id INTEGER REFERENCES action_run_job(id), attempt INTEGER,
                    runner_id INTEGER, status INTEGER, started INTEGER, stopped INTEGER, repo_id INTEGER,
                    owner_id INTEGER, commit_sha TEXT, is_fork_pull_request INTEGER, token_hash TEXT UNIQUE,
                    token_salt TEXT, token_last_eight TEXT, log_filename TEXT, log_in_storage INTEGER,
                    log_length INTEGER, log_size INTEGER, log_indexes BLOB, log_expired INTEGER,
                    created INTEGER, updated INTEGER, runner_request_key TEXT
                );
                CREATE TABLE action_task_step (
                    id INTEGER PRIMARY KEY, name TEXT, task_id INTEGER REFERENCES action_task(id),
                    "index" INTEGER, repo_id INTEGER, status INTEGER, log_index INTEGER, log_length INTEGER,
                    started INTEGER, stopped INTEGER, created INTEGER, updated INTEGER
                );
                CREATE TABLE action_tasks_version (
                    id INTEGER PRIMARY KEY, owner_id INTEGER, repo_id INTEGER, version INTEGER,
                    created_unix INTEGER, updated_unix INTEGER
                );
                CREATE TABLE action_runner_token (id INTEGER PRIMARY KEY, owner_id INTEGER REFERENCES user(id), repo_id INTEGER REFERENCES repository(id), token TEXT);
                CREATE TABLE secret (id INTEGER PRIMARY KEY, data BLOB);
                INSERT INTO version VALUES (1, 305);
                INSERT INTO forgejo_version VALUES (1, 44);
                INSERT INTO forgejo_migration VALUES ('v17', 1);
                INSERT INTO forgejo_sem_ver VALUES ('17.0.0');
                INSERT INTO user VALUES (999, 'stale', NULL);
                INSERT INTO repository VALUES (999, 'stale', 'stale', NULL, 0);
                """,
                [],
            )
            write_dump(source_zip, source_db, "gitea-db.sql")
            write_dump(template_zip, template_db, "forgejo-db.sql")

            report = migrate_dump(source_zip, template_zip, output_zip)

            with zipfile.ZipFile(output_zip) as archive:
                self.assertIn("forgejo-db.sql", archive.namelist())
                self.assertNotIn("gitea-db.sql", archive.namelist())
                self.assertEqual(archive.read("app.ini"), b"[security]\nSECRET_KEY = retained\n")
                self.assertEqual(archive.read("repos/example.git/HEAD"), b"ref: refs/heads/main\n")
                self.assertIn(b"fake-token", archive.read("repos/alice/project.git/config"))
                self.assertFalse(any(name.startswith("data/indexers/issues.bleve/") for name in archive.namelist()))
                migrated_db_path = temp / "migrated.db"
                migrated_db_path.write_bytes(archive.read("data/gitea.db"))

            db = sqlite3.connect(migrated_db_path)
            self.assertEqual(db.execute("SELECT id, name, pronouns FROM user").fetchall(), [(1, "alice", None)])
            self.assertEqual(
                db.execute("SELECT id, wiki_branch, is_mirror FROM repository ORDER BY id").fetchall(),
                [(7, "main-wiki", 1), (8, "main-wiki", 1)],
            )
            self.assertEqual(
                db.execute("SELECT watch_selection_issues, watch_selection_pull_requests, watch_selection_releases FROM watch").fetchall(),
                [(1, 1, 1)],
            )
            self.assertEqual(db.execute("SELECT pin_order FROM issue WHERE id=9").fetchone(), (2,))
            self.assertEqual(
                db.execute("SELECT id, workflow_directory FROM action_run").fetchall(),
                [(1, ".gitea/workflows")],
            )
            self.assertEqual(db.execute('SELECT "index" FROM action_run WHERE id=1').fetchone(), (42,))
            self.assertEqual(db.execute("SELECT max_index FROM action_run_index WHERE group_id=7").fetchone(), (42,))
            self.assertEqual(
                db.execute("SELECT target_url FROM commit_status ORDER BY id").fetchall(),
                [
                    ("/alice/project/actions/runs/42/jobs/0",),
                    ("/alice/project/actions/runs/404/jobs/999",),
                    ("/alice/project/actions/runs/42/jobs/1",),
                ],
            )
            self.assertEqual(
                db.execute("SELECT target_url FROM commit_status_summary").fetchall(),
                [("/alice/project/actions/runs/42/jobs/1",)],
            )
            self.assertEqual(db.execute("SELECT attempt, handle FROM action_run_job").fetchall(), [(2, None), (2, None)])
            self.assertEqual(db.execute("SELECT attempt, runner_request_key FROM action_task").fetchall(), [(2, None)])
            self.assertEqual(db.execute("SELECT COUNT(*) FROM action_task_step").fetchone(), (1,))
            self.assertEqual(db.execute("SELECT version FROM action_tasks_version WHERE repo_id=7").fetchone(), (3,))
            self.assertEqual(db.execute("SELECT owner_id, repo_id, typeof(data) FROM action_runner_token JOIN secret").fetchone(), (None, None, "blob"))
            self.assertEqual(db.execute("SELECT version FROM version").fetchone(), (305,))
            self.assertEqual(db.execute("PRAGMA foreign_key_check").fetchall(), [])
            self.assertEqual(db.execute("PRAGMA integrity_check").fetchone(), ("ok",))
            self.assertEqual(
                db.execute("SELECT id, repo_id, interval, encrypted_remote_address FROM mirror").fetchall(),
                [(1, 7, 86400, None)],
            )
            db.close()

            self.assertEqual(report["converted_row_count"], 19)
            self.assertEqual(report["issue_pins_converted"], 1)
            self.assertEqual(report["action_status_urls_rewritten"], 3)
            self.assertEqual(report["action_status_urls_unmapped"], 1)
            self.assertNotIn("mirror_repositories_demoted", report)
            self.assertEqual(report["source_mirror_flags_without_config"], 1)
            self.assertEqual(report["converted_tables"]["mirror"], 1)
            self.assertEqual(report["source_only_columns"]["mirror"]["remote_address"]["non_null"], 1)
            self.assertIn("data/indexers/issues.bleve/index_meta.json", report["skipped_incompatible_index_paths"])
            self.assertNotIn("action_run", report["skipped_tables"])
            self.assertNotIn("mirror", report["skipped_tables"])
            self.assertEqual(report["flattened_source_tables"]["action_run_attempt"]["rows"], 1)
            self.assertEqual(report["action_workflow_directory_rows_set"], 1)
            self.assertIn("action_run_attempt", report["source_only_tables"])
            self.assertIn("repo_license", report["source_only_tables"])
            self.assertTrue((temp / "output.zip.report.json").exists())
            saved_report = json.loads((temp / "output.zip.report.json").read_text())
            self.assertEqual(saved_report["integrity_check"], "ok")

    def test_refuses_multiple_action_run_attempts(self):
        db = sqlite3.connect(":memory:")
        db.executescript(
            """
            CREATE TABLE action_run (
                id INTEGER PRIMARY KEY, latest_attempt_id INTEGER, status INTEGER, started INTEGER, stopped INTEGER,
                created INTEGER, updated INTEGER, trigger_user_id INTEGER
            );
            CREATE TABLE action_run_attempt (
                id INTEGER PRIMARY KEY, repo_id INTEGER, run_id INTEGER, attempt INTEGER, trigger_user_id INTEGER,
                concurrency_group TEXT, concurrency_cancel INTEGER, status INTEGER, started INTEGER, stopped INTEGER,
                created INTEGER, updated INTEGER
            );
            CREATE TABLE action_run_job (id INTEGER PRIMARY KEY, run_id INTEGER, run_attempt_id INTEGER, status INTEGER);
            INSERT INTO action_run VALUES (1, 1002, 1, 10, 20, 5, 20, 7);
            INSERT INTO action_run_attempt VALUES (1001, 7, 1, 1, 7, '', 0, 1, 10, 20, 5, 20);
            INSERT INTO action_run_attempt VALUES (1002, 7, 1, 2, 7, '', 0, 1, 10, 20, 5, 20);
            INSERT INTO action_run_job VALUES (1, 1, 1002, 1);
            """
        )
        with self.assertRaisesRegex(ValueError, "cannot be flattened safely"):
            validate_action_history(db, {"action_run", "action_run_attempt", "action_run_job"})
        db.close()

    def test_refuses_non_forgejo_17_schema_template(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            source_db, template_db = temp / "source.db", temp / "template.db"
            source_zip, template_zip, output_zip = temp / "gitea.zip", temp / "forgejo.zip", temp / "output.zip"
            create_database(
                source_db,
                "CREATE TABLE version (id INTEGER PRIMARY KEY, version INTEGER); INSERT INTO version VALUES (1, 358);",
                [],
            )
            create_database(
                template_db,
                """
                CREATE TABLE version (id INTEGER PRIMARY KEY, version INTEGER);
                CREATE TABLE forgejo_version (id INTEGER PRIMARY KEY, version INTEGER);
                CREATE TABLE forgejo_migration (id TEXT, created_unix INTEGER);
                CREATE TABLE forgejo_sem_ver (version TEXT);
                INSERT INTO version VALUES (1, 304);
                INSERT INTO forgejo_version VALUES (1, 44);
                """,
                [],
            )
            write_dump(source_zip, source_db, "gitea-db.sql")
            write_dump(template_zip, template_db, "forgejo-db.sql")

            with self.assertRaisesRegex(ValueError, "version 305"):
                migrate_dump(source_zip, template_zip, output_zip)

            self.assertFalse(output_zip.exists())

    def test_does_not_overwrite_existing_output(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            output = temp / "output.zip"
            output.write_bytes(b"keep me")

            with self.assertRaises(FileExistsError):
                migrate_dump(temp / "missing-gitea.zip", temp / "missing-forgejo.zip", output)

            self.assertEqual(output.read_bytes(), b"keep me")


if __name__ == "__main__":
    unittest.main()
