# This script was generated with the assistance of AI Grok.
import subprocess
import sys
import json
import base64
from urllib.parse import urljoin, quote


def normalize_url(base_url):
    """
    Remove the protocol (https:// or http://) from a base URL for an OCI registry.

    :param base_url: Full URL (e.g., 'https://git.visteras.ru')
    :return: Host (e.g., 'git.visteras.ru')
    """
    base_url = base_url.replace('https://', '').replace('http://', '')
    if ':' in base_url and not base_url.startswith('['):  # Port after the host
        host, port = base_url.rsplit(':', 1)
        return f"{host}:{port}"
    return base_url


def get_oci_auth_token(base_url, username, token):
    """
    Fetch the repositories catalog via the OCI API.
    """
    norm_url = normalize_url(base_url)
    auth = base64.b64encode(f"{username}:{token}".encode()).decode()
    headers = {'Authorization': f'Basic {auth}'}
    response = subprocess.run([
        'curl', '-s', '-H', f'Authorization: {headers["Authorization"]}',
        f'{base_url}/v2/_catalog?n=100'  # Pagination via 'n' and 'last'
    ], capture_output=True, text=True)
    if response.returncode != 0:
        print(f"Authentication error: {response.stderr}")
        return None
    try:
        data = json.loads(response.stdout)
        return data  # Returns {'repositories': [...]}
    except json.JSONDecodeError:
        print("Error parsing catalog.")
        return None


def get_repo_tags(base_url, repo_name, username, token):
    """
    Get a list of tags for a repository (repo_name already in 'owner/repo' format).
    """
    auth = base64.b64encode(f"{username}:{token}".encode()).decode()
    response = subprocess.run([
        'curl', '-s', '-H', f'Authorization: Basic {auth}',
        f'{base_url}/v2/{quote(repo_name)}/tags/list'
    ], capture_output=True, text=True)
    if response.returncode != 0:
        print(f"Error fetching tags for {repo_name}: {response.stderr}")
        return []
    try:
        data = json.loads(response.stdout)
        return data.get('tags', [])
    except json.JSONDecodeError:
        return []


def copy_image_skopeo(src_url, src_user, src_token, dst_url, dst_user, dst_token, repo, tag):
    """
    Copy an image using skopeo (repo is already in 'owner/repo' format).
    """
    norm_src = normalize_url(src_url)
    norm_dst = normalize_url(dst_url)
    src_ref = f'docker://{norm_src}/{repo}:{tag}'
    dst_ref = f'docker://{norm_dst}/{repo}:{tag}'
    cmd = [
        'skopeo', 'copy',
        '--src-tls-verify=false',  # If self-signed; remove for production
        '--dest-tls-verify=false',
        f'--src-creds={src_user}:{src_token}',
        f'--dest-creds={dst_user}:{dst_token}',
        src_ref, dst_ref
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode == 0:
        print(f"Copied successfully: {repo}:{tag}")
        return True
    else:
        print(f"Copy error {repo}:{tag}: {result.stderr}")
        return False


def migrate_all_images(source_url, source_user, source_token, target_url, target_user, target_token):
    """
    Main migration function: enumerate and copy all images.
    """
    catalog = get_oci_auth_token(source_url, source_user, source_token)
    if not catalog:
        return False

    repositories = catalog.get('repositories', [])
    print(f"Found {len(repositories)} image repositories.")

    migrated = 0
    for repo in repositories:
        tags = get_repo_tags(source_url, repo, source_user, source_token)
        print(f"Repository {repo}: {len(tags)} tags.")
        for tag in tags:
            if copy_image_skopeo(source_url, source_user, source_token, target_url, target_user, target_token, repo,
                                 tag):
                migrated += 1
            else:
                print(f"Skipping {repo}:{tag}")

    print(f"Migration finished: {migrated} images copied.")
    return True


if __name__ == "__main__":
    if len(sys.argv) != 7:
        print(
            "Usage: python migrate_docker_skopeo.py <source_url> <source_user> <source_token> <target_url> <target_user> <target_token>")
        print(
            "Example: python migrate_docker_skopeo.py https://git.visteras.ru visteras token1 https://forgejo.visteras.ru visteras token2")
        sys.exit(1)

    source_url, source_user, source_token, target_url, target_user, target_token = sys.argv[1:7]
    migrate_all_images(source_url, source_user, source_token, target_url, target_user, target_token)