# Gitea to Forgejo Migrator

This repository contains three migration scripts:

- convert_gitea_dump_to_forgejo.py — best-effort partial migration of a Gitea SQLite dump into a Forgejo 17.0 database schema.
- migrate_gitea_to_forgejo.py — migrate users/organizations and repositories from a Gitea instance to a Forgejo instance via REST API.
- migrate_docker_skopeo.py — migrate container images between registries (e.g., Gitea/Forgejo registries) using skopeo and the OCI API.

Both scripts have been localized to English: all comments, docstrings, and user-facing messages are in English.

Attribution: These scripts and this documentation were generated with the assistance of AI Grok.

## Quick setup (dependencies)

- Create and activate a virtual environment (recommended):
  - Windows (PowerShell):
    - python -m venv .venv
    - .venv\\Scripts\\Activate.ps1
  - Linux/macOS:
    - python3 -m venv .venv
    - source .venv/bin/activate
- Install Python dependencies required by the scripts:
  - pip install --upgrade pip
  - pip install requests
- Install external tools required by migrate_docker_skopeo.py:
  - curl (usually preinstalled on macOS/Linux; Windows 10+ includes curl)
  - skopeo
    - Linux (Debian/Ubuntu): sudo apt-get update && sudo apt-get install -y skopeo
    - Linux (RHEL/CentOS/Fedora): sudo dnf install -y skopeo
    - macOS (Homebrew): brew install skopeo
    - Windows (winget): https://github.com/passcod/winskopeo/releases
    - Windows (Chocolatey): choco install skopeo
- Ensure skopeo and curl are available in PATH (e.g., skopeo --version, curl --version).


## convert_gitea_dump_to_forgejo.py

Create a **partial** Forgejo 17.0 dump from a Gitea SQLite dump and a Forgejo 17.0 dump used only as the target schema template:

    python convert_gitea_dump_to_forgejo.py gitea-dump.zip forgejo-17-template.zip forgejo-partial.zip

The output archive and its `.report.json` sidecar must not already exist. The template database is cleared and used for its schema and Forgejo migration metadata; source files and `app.ini` are retained except for Gitea's `data/indexers/issues.bleve` cache, which may use an incompatible analyzer mapping. The script copies common columns, imports completed Actions run/job/task/step history, flattens the supplied single-attempt-per-run model, and sets imported workflows to `.gitea/workflows`. It rewrites verifiable Gitea Actions commit-status URLs from run/job IDs to Forgejo's per-repository run indexes and zero-based job positions; links whose source run or job is missing are preserved and counted in the report. It rejects multi-attempt, unfinished, or unsupported Gitea-only Actions features rather than guessing. Pull-mirror rows are copied with `encrypted_remote_address` left empty for Forgejo's built-in recovery from the archived Git `origin`; it encrypts the configured URL and sanitizes Git config on first mirror access/sync. Until then, credentials remain in the preserved Git config files. One repository is marked as a mirror without a mirror row; that source inconsistency is retained and reported. Empty incompatible artifact/output tables are skipped. After restoring and starting Forgejo, rebuild the issue indexer from Admin → Monitor → Cron; see the [backup/restore guidance](https://forgejo.org/docs/v17.0/admin/setup/backup/#restoring-forgejo). It checks SQLite integrity and foreign keys, but does not verify the database by starting Forgejo. Review the report and [DB_MIGRATION_GAPS.md](DB_MIGRATION_GAPS.md) for every unmapped table/field.

This is a best-effort conversion, not an upstream-supported direct migration. Forgejo 17's documented transparent path is Gitea up to 1.22 via Forgejo 10.0, then upgrade Forgejo. For newer Gitea versions, Forgejo describes manual database/data changes as best effort. See the [Forgejo upgrade guide](https://forgejo.org/docs/v17.0/admin/upgrade/) and [compatibility note](https://forgejo.org/2024-12-gitea-compatibility/). Keep the source `[security].SECRET_KEY` when restoring encrypted data, retain the original dump, and test restoration on an isolated instance first.

## 1) migrate_gitea_to_forgejo.py

Migrate repositories from a source Gitea to a target Forgejo. It can:
- Migrate all organizations and their repositories.
- Migrate repositories for a specific user (owner).
- Ensure the target user/organization exists (creating organizations if missing, and falling back to the current authenticated user if the specified target user is absent).

### Prerequisites
- Python 3.8+
- requests library (pip install requests)
- API tokens for both source (Gitea) and target (Forgejo) instances.
- Network access between the machine running the script and both instances.

### Parameters
Usage:

    python migrate_gitea_to_forgejo.py <source_url> <source_token> <target_url> <target_token> <owner_name> <target_owner>

Arguments:
- source_url: Base URL of the Gitea instance (e.g., https://gitea.example.com)
- source_token: Gitea API token with sufficient permissions to list orgs/users and read repositories
- target_url: Base URL of the Forgejo instance (e.g., https://forgejo.example.com)
- target_token: Forgejo API token with permissions to create orgs/repos and perform migrations
- owner_name: The source owner (username) to migrate user repositories from. If empty/blank, the user repo migration step is skipped.
- target_owner: The desired target user name in Forgejo. If this user does not exist, the script falls back to the current user associated with target_token. Repository existence in the target is checked by name and owner.

Notes:
- Organization migration does not require a mapping; organizations with the same names are created if they do not exist.
- For each repository, the script calls the Forgejo migrate endpoint (/api/v1/repos/migrate) with appropriate options (issues, pulls, releases, labels, milestones, wiki, LFS, etc.).

### Examples
Migrate all organizations and also migrate repositories for a particular user from Gitea to Forgejo:

    python migrate_gitea_to_forgejo.py https://gitea.example.com <GITEA_TOKEN> https://forgejo.example.com <FORGEJO_TOKEN> alice alice

Behavior:
- If user "alice" exists in Forgejo, her ID is used as the migration target.
- If user "alice" does not exist in Forgejo, the script falls back to the current user (determined by <FORGEJO_TOKEN>). The script prints messages about what it is doing.
- After the user repos migration, the script proceeds to migrate all organizations from the source Gitea and their repositories into the target Forgejo. Organizations are created if missing.


## 2) migrate_docker_skopeo.py

Migrate container images (all repos and their tags) from one registry to another using skopeo. The script uses a simple OCI API call to list repositories and tags, then performs skopeo copy for each tag.

### Prerequisites
- Python 3.8+
- curl (for fetching catalog and tags; can be replaced with requests if desired)
- skopeo installed and available in PATH
- Valid credentials for both source and target registries (username + token)
- Network access between the machine running the script and both registries

If your registries use self-signed certificates, the script presently passes:
- --src-tls-verify=false
- --dest-tls-verify=false

Remove those flags for production-grade secure verification.

### Parameters
Usage:

    python migrate_docker_skopeo.py <source_url> <source_user> <source_token> <target_url> <target_user> <target_token>

Arguments:
- source_url: Base URL of the source registry (e.g., https://git.example.com)
- source_user: Username for the source registry auth
- source_token: Token/password for the source registry
- target_url: Base URL of the target registry (e.g., https://forgejo.example.com)
- target_user: Username for the target registry auth
- target_token: Token/password for the target registry

### Example
Copy all images and their tags from source to target:

    python migrate_docker_skopeo.py https://git.example.com alice SRC_TOKEN https://forgejo.example.com alice DST_TOKEN

The script will:
- Fetch the repositories catalog via /v2/_catalog
- For each repository, fetch tags via /v2/<repo>/tags/list
- For each tag, run skopeo copy from source to target
- Print progress and a final summary

### Troubleshooting
- Ensure tokens are valid and have required permissions (read on source, write on target).
- If you get TLS/SSL errors, review whether to keep or remove the --*-tls-verify flags. For self-signed setups, they may be necessary.
- Make sure skopeo is installed and discoverable (e.g., skopeo --version works in your shell).
- If using Windows, run from a shell that can execute skopeo and curl commands (e.g., PowerShell with skopeo in PATH).


## Development notes
- All console output and comments are in English per project requirement.
- The dump converter uses only Python's standard library. Tests run with `python -m unittest discover -s tests`.
