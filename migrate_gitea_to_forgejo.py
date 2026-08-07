# This script was generated with the assistance of AI Grok.
import requests
import json
import sys
from urllib.parse import urljoin


def get_current_user(target_url, target_token):
    """
    Get information about the current user using a Forgejo token.

    :param target_url: Base URL of the Forgejo instance
    :param target_token: Forgejo API token
    :return: Username of the current user or None on error
    """
    session = requests.Session()
    session.headers.update({'Authorization': f'token {target_token}'})

    user_url = urljoin(target_url, '/api/v1/user')
    response = session.get(user_url)
    if response.status_code == 200:
        return response.json().get('username')
    else:
        print(f"Error getting current user: {response.status_code} - {response.text}")
        return None


def get_current_user_id(target_url, target_token):
    """
    Get the ID of the current user using a Forgejo token.

    :param target_url: Base URL of the Forgejo instance
    :param target_token: Forgejo API token
    :return: ID of the current user or None on error
    """
    session = requests.Session()
    session.headers.update({'Authorization': f'token {target_token}'})

    user_url = urljoin(target_url, '/api/v1/user')
    response = session.get(user_url)
    if response.status_code == 200:
        return response.json().get('id')
    else:
        print(f"Error getting current user: {response.status_code} - {response.text}")
        return None


def get_user_id(target_url, target_token, username):
    """
    Get a user's ID by username in Forgejo.

    :param target_url: Base URL of the Forgejo instance
    :param target_token: Forgejo API token
    :param username: Username
    :return: User ID or None on error
    """
    session = requests.Session()
    session.headers.update({'Authorization': f'token {target_token}'})

    user_url = urljoin(target_url, f'/api/v1/users/{username}')
    response = session.get(user_url)
    if response.status_code == 200:
        return response.json().get('id')
    else:
        return None


def ensure_target_user(target_url, target_token, target_user):
    """
    Ensure the target user exists in Forgejo; if not, fall back to the current user's ID.

    :param target_url: Base URL of the Forgejo instance
    :param target_token: Forgejo API token
    :param target_user: Target username
    :return: Owner ID for migration (int) or None
    """
    user_id = get_user_id(target_url, target_token, target_user)
    if user_id:
        print(f"User '{target_user}' (ID: {user_id}) already exists.")
        return user_id
    else:
        # Fallback to current user
        current_user_id = get_current_user_id(target_url, target_token)
        current_username = get_current_user(target_url, target_token)
        if current_user_id and current_username:
            print(
                f"User '{target_user}' does not exist. Falling back to '{current_username}' (ID: {current_user_id}).")
            return current_user_id
        else:
            print("Could not determine a fallback user. Skipping user repositories migration.")
            return None


def get_org_id(target_url, target_token, org_name):
    """
    Get an organization ID by name in Forgejo.

    :param target_url: Base URL of the Forgejo instance
    :param target_token: Forgejo API token
    :param org_name: Organization name
    :return: Organization ID or None on error
    """
    session = requests.Session()
    session.headers.update({'Authorization': f'token {target_token}'})

    org_url = urljoin(target_url, f'/api/v1/orgs/{org_name}')
    response = session.get(org_url)
    if response.status_code == 200:
        return response.json().get('id')
    else:
        return None


def ensure_target_org(target_url, target_token, target_org):
    """
    Ensure the organization exists in Forgejo; create it if missing.

    :param target_url: Base URL of the Forgejo instance
    :param target_token: Forgejo API token
    :param target_org: Target organization name
    :return: Organization ID (int) or None
    """
    org_id = get_org_id(target_url, target_token, target_org)
    if org_id:
        print(f"Organization '{target_org}' (ID: {org_id}) already exists.")
        return org_id
    else:
        # Create organization
        session = requests.Session()
        session.headers.update({'Authorization': f'token {target_token}', 'Content-Type': 'application/json'})

        create_data = {
            'username': target_org,  # Required by CreateOrgOption schema
            'full_name': target_org,  # Optional: full name
            'description': 'Migrated organization from Gitea',
            'visibility': 'public',  # Or 'private', depending on needs
            'website': '',
            'location': '',
            'repo_admin_change_team_access': False
        }
        create_response = session.post(urljoin(target_url, '/api/v1/orgs'), data=json.dumps(create_data))
        if create_response.status_code == 201:
            created_id = create_response.json().get('id')
            print(f"Organization '{target_org}' (ID: {created_id}) created successfully.")
            return created_id
        else:
            print(f"Error creating organization '{target_org}': {create_response.status_code} - {create_response.text}")
            return None


def repo_exists(target_url, target_token, target_owner_name, repo_name):
    """
    Check if a repository exists by owner/name in Forgejo.

    :param target_url: Base URL of the Forgejo instance
    :param target_token: Forgejo API token
    :param target_owner_name: Target owner name
    :param repo_name: Repository name
    :return: True if the repository exists
    """
    session = requests.Session()
    session.headers.update({'Authorization': f'token {target_token}'})

    repo_url = urljoin(target_url, f'/api/v1/repos/{target_owner_name}/{repo_name}')
    response = session.get(repo_url)
    return response.status_code == 200


def get_all_orgs(source_url, source_token):
    """
    Get a list of all organizations from Gitea.

    :param source_url: Base URL of the Gitea instance
    :param source_token: Gitea API token
    :return: List of organizations
    """
    session = requests.Session()
    session.headers.update({'Authorization': f'token {source_token}'})

    orgs = []
    page = 1
    
    while True:
        orgs_url = urljoin(source_url, f'/api/v1/orgs?page={page}&limit=50')
        response = session.get(orgs_url)
        
        if response.status_code != 200:
            print(f"Error fetching organizations list: {response.text}")
            break
            
        page_data = response.json()
        if not page_data:
            break
            
        orgs.extend(page_data)
        page += 1
        
    return orgs


def migrate_owner_repos(source_url, source_token, target_url, target_token, source_owner, target_uid, target_owner_name,
                        is_org=False):
    """
    Migrate an owner's repositories from Gitea to Forgejo.

    :param source_url: Base URL of the Gitea instance
    :param source_token: Gitea API token
    :param target_url: Base URL of the Forgejo instance
    :param target_token: Forgejo API token
    :param source_owner: Owner name in the source
    :param target_uid: Owner ID in the target (int)
    :param target_owner_name: Owner name in the target (for repo_exists check)
    :param is_org: True if the owner is an organization
    """
    if not target_uid:
        print("Skipping migration: owner ID is not defined.")
        return

    session_source = requests.Session()
    session_source.headers.update({'Authorization': f'token {source_token}'})

    session_target = requests.Session()
    session_target.headers.update({'Authorization': f'token {target_token}', 'Content-Type': 'application/json'})

    # Get the list of source repositories
# Get the list of source repositories (with pagination)
    repos = []
    page = 1
    
    while True:
        if is_org:
            repos_url = urljoin(source_url, f'/api/v1/orgs/{source_owner}/repos?page={page}&limit=50')
        else:
            repos_url = urljoin(source_url, f'/api/v1/users/{source_owner}/repos?page={page}&limit=50')

        response = session_source.get(repos_url)
        
        if response.status_code != 200:
            print(f"Error fetching repositories list for {source_owner}: {response.text}")
            break
            
        page_data = response.json()
        if not page_data:
            break
            
        repos.extend(page_data)
        page += 1
    print(f"Found {len(repos)} repositories for {source_owner}.")

    migrated_count = 0
    skipped_count = 0
    for repo in repos:
        repo_name = repo['name']
        print(f"Processing repository: {repo_name} from {source_owner}")

        # Check existence in target
        if repo_exists(target_url, target_token, target_owner_name, repo_name):
            print(f"Repository '{repo_name}' already exists in '{target_owner_name}', skipping.")
            skipped_count += 1
            continue

        # Git URL for cloning
        clone_addr = f"{source_url}/{source_owner}/{repo_name}.git"

        # Migration parameters (uid as int)
        migrate_data = {
            'clone_addr': clone_addr,
            'auth_username': source_owner,
            'auth_password': source_token,
            'uid': target_uid,
            'repo_name': repo_name,
            'description': repo.get('description', ''),
            'private': repo['private'],
            'mirror': False,
            'wiki': True,
            'issues': True,
            'pull_requests': True,
            'releases': True,
            'labels': True,
            'milestones': True,
            'mirror_interval': '',
            'lfs': True,  # Added per schema
            'service': 'git'  # Added per schema
        }

        # Perform migration
        migrate_url = urljoin(target_url, '/api/v1/repos/migrate')
        response = session_target.post(migrate_url, data=json.dumps(migrate_data))
        if response.status_code == 201:
            print(f"Successfully migrated: {repo_name} to {target_owner_name} (ID: {target_uid})")
            migrated_count += 1
        else:
            print(f"Migration error for {repo_name}: {response.status_code} - {response.text}")

    print(f"Migration for {source_owner} completed: {migrated_count} succeeded, {skipped_count} skipped.")


def migrate_all_orgs(source_url, source_token, target_url, target_token):
    """
    Migrate all organizations and their repositories.
    """
    orgs = get_all_orgs(source_url, source_token)
    print(f"Found {len(orgs)} organizations to migrate.")

    for org in orgs:
        org_name = org['username']
        print(f"\nProcessing organization: {org_name}")

        # Ensure the target organization exists and get its ID
        target_org_id = ensure_target_org(target_url, target_token, org_name)
        if not target_org_id:
            print(f"Aborting migration for {org_name} due to an organization error.")
            continue

        # Migrate repositories
        migrate_owner_repos(source_url, source_token, target_url, target_token, org_name, target_org_id, org_name,
                            is_org=True)


if __name__ == "__main__":
    if len(sys.argv) != 7:
        print(
            "Usage: python migrate_gitea_to_forgejo.py <source_url> <source_token> <target_url> <target_token> <owner_name> <target_owner>")
        sys.exit(1)

    source_url, source_token, target_url, target_token, owner_name, target_owner = sys.argv[1:7]

    # Migrate user repositories if owner_name is provided
    if owner_name and owner_name.strip():
        print(f"\nMigrating user repositories from {owner_name}")
        effective_uid = ensure_target_user(target_url, target_token, target_owner)
        if effective_uid:
            # Get a name for fallback (if fallback, use current user's name)
            effective_name = target_owner if get_user_id(target_url, target_token, target_owner) else get_current_user(
                target_url, target_token) or 'current user'
            migrate_owner_repos(source_url, source_token, target_url, target_token, owner_name, effective_uid,
                                effective_name, is_org=False)

    # Migrate all organizations
    print("\nMigrating all organizations...")
    migrate_all_orgs(source_url, source_token, target_url, target_token)