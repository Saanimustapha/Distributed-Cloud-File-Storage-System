import argparse
import sys
from typing import Optional

import requests


def get_access_token(
    backend_url: str,
    email: str,
    password: str,
) -> str:
    """
    Get JWT access token from /auth/token using username (email) + password.
    """
    token_url = f"{backend_url.rstrip('/')}/auth/login"

    # FastAPI OAuth2PasswordRequestForm expects form data "username" and "password"
    data = {
        "username": email,
        "password": password,
    }

    resp = requests.post(token_url, data=data)
    if resp.status_code != 200:
        print(f"[ERROR] Failed to get token ({resp.status_code}): {resp.text}", file=sys.stderr)
        sys.exit(1)

    token = resp.json().get("access_token")
    if not token:
        print("[ERROR] No access_token in response", file=sys.stderr)
        sys.exit(1)

    return token


def check_node_health(base_url: str, timeout: float = 3.0) -> None:
    """
    Call GET {base_url}/health and fail if it's not OK.
    """
    health_url = f"{base_url.rstrip('/')}/health"
    try:
        resp = requests.get(health_url, timeout=timeout)
    except requests.RequestException as e:
        print(f"[ERROR] Could not reach node at {health_url}: {e}", file=sys.stderr)
        sys.exit(1)

    if resp.status_code != 200:
        print(f"[ERROR] Node health check failed ({resp.status_code}): {resp.text}", file=sys.stderr)
        sys.exit(1)

    print(f"[OK] Node at {base_url} is healthy.")


def register_node(
    backend_url: str,
    token: str,
    name: str,
    base_url: str,
    is_online: bool = True,
    capacity_bytes: Optional[int] = None,
) -> None:
    """
    POST /nodes to register a node in the main backend.
    """
    url = f"{backend_url.rstrip('/')}/nodes/create"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    payload = {
        "name": name,
        "base_url": base_url,
        "is_online": is_online,
        "capacity_bytes": capacity_bytes,
    }

    resp = requests.post(url, json=payload, headers=headers)
    if resp.status_code not in (200, 201):
        print(f"[ERROR] Failed to register node ({resp.status_code}): {resp.text}", file=sys.stderr)
        sys.exit(1)

    print(f"[OK] Registered node '{name}' with base_url={base_url}")
    print("Response:", resp.json())


def main():
    parser = argparse.ArgumentParser(description="Register a storage node with the main backend.")
    parser.add_argument(
        "--backend-url",
        default="http://localhost:8000",
        help="Base URL of the main backend API (default: http://localhost:8000)",
    )
    parser.add_argument(
        "--email",
        required=True,
        help="User email for authentication (same as /auth/register).",
    )
    parser.add_argument(
        "--password",
        required=True,
        help="User password for authentication.",
    )
    parser.add_argument(
        "--name",
        required=True,
        help="Name to give this node (e.g. node1, node2, vm-node1...).",
    )
    parser.add_argument(
        "--base-url",
        required=True,
        help="Base URL of the storage node (e.g. http://localhost:9001).",
    )
    parser.add_argument(
        "--capacity-bytes",
        type=int,
        default=None,
        help="Optional capacity hint in bytes.",
    )

    args = parser.parse_args()

    # 1) Check that the storage node is reachable and healthy
    check_node_health(args.base_url)

    # 2) Get access token for the main backend
    token = get_access_token(args.backend_url, args.email, args.password)

    # 3) Register the node in the main backend
    register_node(
        backend_url=args.backend_url,
        token=token,
        name=args.name,
        base_url=args.base_url,
        capacity_bytes=args.capacity_bytes,
    )


if __name__ == "__main__":
    main()


#Script run command
# python register_node.py \
#   --backend-url http://localhost:8000 \
#   --email mdsaani@example.com \
#   --password saanipass \
#   --name node1 \
#   --base-url http://localhost:9001
