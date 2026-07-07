#!/usr/bin/env python3
"""Build a prefilled GitHub App registration URL.

This helper targets the GitHub "new app" page so a mobile operator can open one
link, review the prefilled settings, and create a self-owned GitHub App without
committing credentials to the repository.
"""

from __future__ import annotations

import argparse
from urllib.parse import urlencode

DEFAULT_EVENTS = ["workflow_run", "check_run", "check_suite", "pull_request", "push"]
DEFAULT_PERMISSIONS = {
    "checks": "write",
    "contents": "read",
    "metadata": "read",
    "pull_requests": "write",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a GitHub App creation URL.")
    parser.add_argument("--name", default="heavy-metal-control-plane", help="GitHub App name.")
    parser.add_argument("--description", default="Self-made GitHub App for Heavy Metal repository automation.")
    parser.add_argument("--homepage-url", default="https://github.com/settings/apps", help="Public homepage URL for the app registration.")
    parser.add_argument("--webhook-url", default="", help="HTTPS webhook endpoint, for example https://example.com/github/webhook.")
    parser.add_argument("--callback-url", default="", help="Optional OAuth callback URL.")
    parser.add_argument("--setup-url", default="", help="Optional post-install setup URL.")
    parser.add_argument("--organization", default="", help="Register under this organization instead of the signed-in user.")
    parser.add_argument("--public", action="store_true", help="Make the app public. Defaults to private.")
    return parser.parse_args()


def base_url(organization: str) -> str:
    if organization:
        return f"https://github.com/organizations/{organization}/settings/apps/new"
    return "https://github.com/settings/apps/new"


def build_query(args: argparse.Namespace) -> str:
    params: dict[str, str] = {
        "name": args.name,
        "description": args.description,
        "url": args.homepage_url,
        "public": "true" if args.public else "false",
        "webhook_active": "true" if args.webhook_url else "false",
    }

    if args.webhook_url:
        params["webhook_url"] = args.webhook_url
    if args.callback_url:
        params["callback_urls[]"] = [args.callback_url]
    if args.setup_url:
        params["setup_url"] = args.setup_url

    for permission, access in DEFAULT_PERMISSIONS.items():
        params[permission] = access
    params["events[]"] = DEFAULT_EVENTS

    return urlencode(params, doseq=True)


def main() -> None:
    args = parse_args()
    print(f"{base_url(args.organization)}?{build_query(args)}")


if __name__ == "__main__":
    main()
