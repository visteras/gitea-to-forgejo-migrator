# Gitea 28.1.0 → Forgejo 17.0 database gap inventory

This inventory compares the SQLite databases in the supplied archives:

- `/tmp/gitea-dump-1792260811.zip`
- `/tmp/forgejo-dump-1792260972.zip`

It is a **structural** comparison, not a statement that every missing same-name field is semantically impossible to map. “No direct target” means there is no same-named destination table/column; any alias or data transformation must be validated before it is used.

## Version markers

| Archive | `version.version` | Forgejo migration version |
| --- | ---: | ---: |
| Gitea 28.1.0 | 358 | — |
| Forgejo 17.0 | 305 | 44 |

The database migration version is not a field to rewrite to make the schemas compatible. Forgejo uses it to reject unsupported database downgrades.

## Gitea tables with no same-named Forgejo table

Fields shown are all source fields in that table. The row counts are from the supplied Gitea database.

| Gitea table | Rows | Fields with no direct target table |
| --- | ---: | --- |
| `action_run_attempt` | 43 | `id`, `repo_id`, `run_id`, `attempt`, `trigger_user_id`, `concurrency_group`, `concurrency_cancel`, `status`, `started`, `stopped`, `created`, `updated` |
| `action_run_attempt_job_id_index` | 43 | `group_id`, `max_index` |
| `action_run_job_summary` | 0 | `id`, `repo_id`, `run_id`, `run_attempt_id`, `job_id`, `step_index`, `content`, `content_type`, `content_size`, `created`, `updated` |
| `action_scoped_workflow_source` | 0 | `id`, `owner_id`, `source_repo_id`, `workflow_configs`, `created_unix`, `updated_unix` |
| `audit_event` | 0 | `id`, `action`, `actor_id`, `actor_name`, `actor_credential`, `impersonator_id`, `impersonator_name`, `scope_id`, `scope_type`, `scope_name`, `origin`, `message`, `metadata`, `ip_address`, `timestamp_unix` |
| `auth_token` | 0 | `id`, `token_hash`, `user_id`, `expires_unix` |
| `issue_pin` | 0 | `id`, `repo_id`, `issue_id`, `is_pull`, `pin_order` |
| `repo_license` | 17 | `id`, `repo_id`, `commit_id`, `license`, `created_unix`, `updated_unix`, `license_path` |
| `user_blocking` | 0 | `id`, `blocker_id`, `blockee_id`, `note`, `created_unix` |

The structural table-level gaps with rows are Gitea's 43 Actions attempts, its 43-row attempt-job allocation index, and 17 repository-license records. The converter now flattens the single Actions attempt per run into Forgejo's existing `action_run` rows; the attempt-job index is not used by Forgejo. `auth_token`, `issue_pin`, and `user_blocking` have no rows in this source dump.

## Gitea-only columns in tables that exist in both schemas

These source columns have no same-named column in the Forgejo table.

| Table | Gitea-only columns |
| --- | --- |
| `action` | `is_deleted` |
| `action_artifact` | `run_attempt_id` |
| `action_run` | `is_scoped_run`, `latest_attempt_id`, `raw_concurrency`, `workflow_commit_sha`, `workflow_repo_id` |
| `action_run_job` | `attempt_job_id`, `call_payload`, `call_secrets`, `call_uses`, `concurrency_cancel`, `concurrency_group`, `continue_on_error`, `deferred_matrix_payload`, `is_concurrency_evaluated`, `is_expanded`, `is_matrix_deferred`, `is_reusable_caller`, `max_parallel`, `parent_job_id`, `raw_concurrency`, `reusable_workflow_content`, `run_attempt_id`, `source_task_id`, `token_permissions`, `workflow_source_commit_sha`, `workflow_source_repo_id` |
| `action_runner` | `has_cancelling_support`, `is_disabled` |
| `action_runner_token` | `deleted` |
| `action_schedule` | `specs` |
| `action_variable` | `description` |
| `badge` | `slug` |
| `comment` | `comment_meta_data` |
| `deploy_key` | `key_type`, `token_hash` |
| `email_hash` | `hash_type` |
| `issue` | `time_estimate` |
| `label` | `exclusive_order` |
| `login_source` | `two_factor_policy` |
| `mirror` | `last_sync_unix`, `remote_address` |
| `notification` | `commit_id`, `updated_by` |
| `oauth2_application` | `skip_secondary_authorization` |
| `protected_branch` | `block_admin_merge_override`, `block_on_codeowner_reviews`, `bypass_allowlist_team_i_ds`, `bypass_allowlist_user_i_ds`, `can_force_push`, `enable_bypass_allowlist`, `enable_force_push_allowlist`, `force_push_allowlist_deploy_keys`, `force_push_allowlist_team_i_ds`, `force_push_allowlist_user_i_ds`, `priority` |
| `pull_auto_merge` | `merged_commit_id` |
| `release` | `published_unix` |
| `repo_transfer` | `recipient_access_granted` |
| `repo_unit` | `anonymous_access_mode`, `everyone_access_mode` |
| `repository` | `default_wiki_branch`, `num_action_runs`, `num_closed_action_runs`, `num_closed_issues`, `num_closed_pulls`, `num_issues`, `num_pulls` |
| `secret` | `description` |
| `team` | `visibility` |
| `watch` | `include_issues`, `include_pull_requests`, `include_releases`, `mode` |
| `webhook` | `name` |

The partial migrator currently applies these aliases: `repository.default_wiki_branch` → `repository.wiki_branch`; Gitea's `watch.include_*` → Forgejo's corresponding `watch.watch_selection_*`; and rows from `issue_pin` → `issue.pin_order`. The supplied `issue_pin` table is empty; all 56 `default_wiki_branch` values and all 56 watch-selection values are populated. These mappings are explicit but still need application-level validation. The converter also rewrites verifiable Actions commit-status URLs from Gitea's run/job IDs to Forgejo's index/position format.

## Source-only columns that contain data in this dump

Counts below are non-null source values; for numeric fields explicitly marked “nonzero”, the count excludes zero/default values. Values themselves are not printed (some fields may contain secrets).

- Actions have the largest structural differences, but the supplied completed history is now imported:
  - There are 122 runs and 43 `action_run_attempt` rows. Each run has at most one attempt (always attempt 1); every attempt is the run's `latest_attempt_id`, and status/timestamps/user match the parent run. `workflow_repo_id` equals `repo_id`; nonempty `workflow_commit_sha` equals `commit_sha`; concurrency fields are empty. The attempt table is therefore flattened into `action_run`; its IDs and `latest_attempt_id` pointers are not retained.
  - The 167 jobs preserve their common columns, including per-job `attempt`; the 171 tasks preserve task attempts, and all 836 steps are copied. Source `run_attempt_id`/`attempt_job_id` fields have no target equivalent. The 60 nonzero `workflow_source_repo_id` / `workflow_source_commit_sha` values equal their job's own repo/commit. Reusable-workflow payloads/flags are empty/default in this dump; `is_concurrency_evaluated` is true for 10 already-terminal jobs.
  - All run/job/task/step status values are terminal (1–4 in Forgejo's enum), every task has stopped, and all 167 stored workflow payloads parse with Forgejo's job parser. All 146 stored task-log files referenced by tasks are present in the archive.
- Gitea's Actions commit-status URLs use run/job database IDs, while Forgejo 17 expects repository-local run indexes and zero-based job positions. The converter rewrites verified links: 1,199 of 1,239 `commit_status` URLs and 122 of 141 `commit_status_summary` URLs in this dump. The remaining 59 refer to run IDs absent from the source `action_run` table, so they are preserved and reported rather than guessed.
- `mirror`: all 33 rows are copied. Gitea's `remote_address` is sanitized, and Forgejo 17 deliberately does not re-encrypt it during migration: with `encrypted_remote_address` NULL, Forgejo's `DecryptOrRecoverRemoteAddress` recovers the full URL from the repository's Git `origin`, encrypts it, and sanitizes the Git config on first mirror access/sync. In the supplied archive, all 33 repositories have an `origin` matching the source address apart from URL credentials; three origins contain credentials, which the Forgejo recovery path will encrypt. The converter relies on Forgejo's fallback and does not validate these files. `last_sync_unix` has 32 populated timestamps but no target field; 30 equal the common `updated_unix` value and two differ. The converter preserves `updated_unix` unchanged rather than overwriting it and losing those distinct values. The source marks 34 repositories as mirrors, but one has no `mirror` row; that orphan flag is retained as found and reported, despite lacking mirror scheduling configuration.
- `release.published_unix`: populated on all 612 releases. It is absent from Forgejo's release table. In this dump, 610 values equal `created_unix`; two differ (by up to 25 seconds), so dropping it loses those distinct timestamps.
- `secret.description`: populated on both source `secret` rows; Forgejo has no such column. `secret.data` is `TEXT` in Gitea and `BLOB` in Forgejo, and both source values are non-null. Preserve the Gitea `SECRET_KEY`; do not treat this as a plain text cast.
- `team.visibility`: populated on all 3 teams; no same-named target field.
- `login_source.two_factor_policy`: populated on both login sources; no same-named target field.
- `email_hash.hash_type`: populated on all 38 rows (one distinct value); no same-named target field.
- `action_variable.description`: populated on its one row; no same-named target field.
- Repository statistics `num_issues`, `num_closed_issues`, `num_pulls`, `num_closed_pulls`, and action-run counts are present; these look like derived counters and should be recomputed or deliberately omitted, not blindly copied.
- `watch.include_issues`, `watch.include_pull_requests`, `watch.include_releases`, and `mode` are populated on all 56 rows. Forgejo has differently named watch-selection fields; mapping needs validation.
- `action.is_deleted` is zero for all 6,144 rows; `issue.time_estimate` is zero for all 4 issues; the Gitea-only `repo_unit` access modes are zero on all 160 rows. Those values carry no non-default information in this dump.
- `comment.comment_meta_data`, all Gitea-only protected-branch columns, and several other fields are null/empty because their tables have no rows or the field is unused here. They remain schema gaps for other dumps.

## Forgejo-only tables

These tables have no Gitea source table: `abuse_report`, `abuse_report_shadow_copy`, `access_token_resource_repo`, `action_task_step_summary`, `action_user`, `authorized_integ_resource_repo`, `authorized_integration`, `federated_user`, `federated_user_activity`, `federated_user_follower`, `federation_host`, `following_repo`, `forgejo_auth_token`, `forgejo_blocked_user`, `forgejo_migration`, `forgejo_repo_flag`, `forgejo_sem_ver`, `forgejo_version`, `quota_group`, `quota_group_mapping`, `quota_group_rule_mapping`, `quota_rule`, and `repo_archive_download_count`.

Most are empty in the reference Forgejo dump. The `forgejo_version`/`forgejo_migration` records are Forgejo's migration bookkeeping, not Gitea data; a Forgejo-v17 schema template must retain the appropriate migration state, not copy source values into it.

## Forgejo-only columns in shared tables

These destination fields have no same-named Gitea source column. Every field listed below is nullable or has a database default in the Forgejo reference, so a basic insert can omit it; this does not prove a semantically correct application default.

| Table | Forgejo-only columns (default/constraint where relevant) |
| --- | --- |
| `access_token` | `resource_all_repos` (NOT NULL, default `TRUE`) |
| `action_run` | `concurrency_group`, `concurrency_type`, `notify_email`, `pre_execution_error`, `pre_execution_error_code`, `pre_execution_error_details`, `pre_execution_warning_codes`, `pre_execution_warning_details`, `pull_request_id`, `pull_request_poster_id`, `workflow_source_commit` (nullable); `prioritize`, `priority` (NOT NULL, default `0`); `workflow_directory` (NOT NULL, default `.forgejo/workflows`) |
| `action_run_job` | `handle`, `job_namespace` |
| `action_schedule` | `workflow_directory` (NOT NULL, default `.forgejo/workflows`) |
| `action_schedule_spec` | `time_zone` |
| `action_task` | `runner_request_key` |
| `attachment` | `external_url` |
| `comment` | `extra_lines_count` (NOT NULL, default `0`) |
| `issue` | `created`, `pin_order` (`pin_order` default `0`) |
| `mirror` | `encrypted_remote_address` |
| `package_blob` | `hash_blake2b` |
| `package_cleanup_rule` | `keep_last_download_days`, `remove_last_download_days` (NOT NULL, default `0`) |
| `package_version` | `last_download_unix`; `total_size` (NOT NULL, default `0`) |
| `protected_branch` | `apply_to_admins` (NOT NULL, default `0`) |
| `push_mirror` | `branch_filter`, `private_key`, `public_key` |
| `release` | `hide_archive_links` (NOT NULL, default `0`) |
| `repo_unit` | `default_permissions` (NOT NULL, default `0`) |
| `repository` | `wiki_branch` |
| `team_invite` | `expiry_unix`, `invited_id` |
| `user` | `pronouns`; `keep_pronouns_private` (NOT NULL, default `0`); `enable_repo_unit_hints` (NOT NULL, default `1`) |
| `user_redirect` | `created_unix` (NOT NULL, default `0`) |
| `watch` | `source`, `watch_selection_issues`, `watch_selection_pull_requests`, `watch_selection_releases` (defaults `TRUE`) |
| `webauthn_credential` | `backup_eligible` (NOT NULL, default `0`); `backup_state` (NOT NULL, default `0`); `legacy` (NOT NULL, default `1`) |

## Shared columns with changed SQLite declarations

| Table.field | Gitea declaration | Forgejo declaration | Source rows requiring attention |
| --- | --- | --- | --- |
| `project_issue.issue_id` | nullable INTEGER | NOT NULL INTEGER | table empty |
| `project_issue.project_board_id` | nullable INTEGER | NOT NULL INTEGER | table empty |
| `project_issue.project_id` | nullable INTEGER | NOT NULL INTEGER | table empty |
| `pull_auto_merge.delete_branch_after_merge` | nullable INTEGER, no default | NOT NULL INTEGER, default `0` | table empty |
| `repository.topics` | nullable TEXT | NOT NULL TEXT | no null source rows |
| `secret.data` | nullable TEXT | nullable BLOB | 2 non-null source values (SQLite stores both as TEXT) |
| `two_factor.secret` | nullable TEXT | nullable BLOB | no source rows |
| `webhook.header_authorization_encrypted` | nullable TEXT | nullable BLOB | no source rows |

Forgejo migration 304 (`MigrateTwoFactorToKeying`) is a semantic TOTP/keying migration, not a generic TEXT-to-BLOB conversion. The supplied Gitea database has no `two_factor` rows; that migration does not explain how to convert the two rows in Gitea's separate `secret` table.

## What the partial migrator currently does

The converter seeds a clean database from the Forgejo 17.0 template (keeping Forgejo's own migration metadata), copies common table/column data, applies the aliases above, converts `secret.data` text to its original UTF-8 bytes in the target BLOB column, and changes zero `action_runner_token.owner_id` / `repo_id` sentinels to `NULL` for Forgejo's foreign keys. It imports the supplied completed Actions runs/jobs/tasks/steps and their existing index/version rows. Gitea's one run attempt per run is flattened because the attempt state matches its parent run; attempts beyond the supported single-attempt case, non-terminal history, and unsupported Gitea-only workflow features are rejected. Imported run/schedule rows use `.gitea/workflows`; `handle`, `job_namespace`, and `runner_request_key` remain NULL for completed history, and Forgejo creates a new handle if a job is rerun.

It skips `action_artifact` and `action_task_output` (both empty in this dump). It copies the 33 pull-mirror rows' shared configuration fields and leaves Forgejo's nullable `encrypted_remote_address` empty for the supported lazy recovery from each archived Git `origin`. The one repository whose source `is_mirror` flag has no corresponding `mirror` row is retained as found and reported. Gitea's `last_sync_unix` has no target equivalent and is reported as unmapped. The converter emits a JSON report with actual row counts, Actions status URLs rewritten/unmapped, flattened source tables, skipped tables, unmapped source fields, target-only fields, and integrity checks.

The converter also omits the source `data/indexers/issues.bleve` directory: its stored analyzer mapping is incompatible with the target Bleve build (`camelCaseKeepWhole` is unregistered). The issue index is derived data; after startup, rebuild it using Admin → Monitor → Cron → “Rebuild issue indexer” as described in the [Forgejo restore guidance](https://forgejo.org/docs/v17.0/admin/setup/backup/#restoring-forgejo). The JSON report lists the skipped archive paths.

The no-direct-target inventory is exhaustive for these two SQLite schemas, but a successful SQLite/FK check does not prove Forgejo can use every imported row. The source `version=358` is not edited in place: the partial database is constructed on Forgejo's v17 schema and keeps the template's migration markers. Restore it only into an isolated Forgejo 17.0 test instance and validate the affected features before production use.
