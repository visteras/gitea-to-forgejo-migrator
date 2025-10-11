# Gitea to Forgejo Migrator

This repository contains two migration scripts:

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
- Minimal changes were made to existing logic; only messages and comments were translated, and README.md was added.
