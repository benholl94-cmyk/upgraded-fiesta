# Self-made GitHub App setup

Use this guide to create a self-owned GitHub App for the Heavy Metal control plane from GitHub's app registration page: <https://github.com/settings/apps/new>.

The repository includes a portable URL builder so mobile/Codex operators can generate a prefilled registration link without storing secrets in git.

## Generate the registration link

From the repository root, run:

```sh
python3 scripts/build_github_app_url.py \
  --name heavy-metal-control-plane \
  --homepage-url https://github.com/settings/apps \
  --webhook-url https://YOUR_PUBLIC_GATEWAY_HOST/github/webhook
```

For an organization-owned app, add:

```sh
--organization YOUR_ORG
```

Open the printed URL while signed in to GitHub. GitHub will load the same app registration flow as `https://github.com/settings/apps/new`, with the Heavy Metal defaults prefilled.

## Prefilled defaults

The generated link keeps the app private by default and requests only repository-level permissions needed for common automation:

| Setting | Value |
| --- | --- |
| App visibility | Private |
| Webhook active | Enabled only when `--webhook-url` is provided |
| Repository metadata | Read-only |
| Repository contents | Read-only |
| Checks | Read and write |
| Pull requests | Read and write |
| Events | `workflow_run`, `check_run`, `check_suite`, `pull_request`, `push` |

Review every field in GitHub before clicking **Create GitHub App**. Keep permissions minimal for the exact automation you plan to run.

## After GitHub creates the app

1. Generate a private key from the app settings page.
2. Save the PEM outside git, for example in your hosting platform secret store.
3. Save the App ID, Client ID, Installation ID, webhook secret, and private key as environment variables or platform secrets.
4. Install the app only on the repositories it needs to control.
5. Point the webhook URL at a public HTTPS endpoint that can verify GitHub webhook signatures before processing events.

Do not commit private keys, webhook secrets, `.env` files, tokens, or installation credentials.

## Environment variable names

Recommended deployment secret names:

```text
GITHUB_APP_ID
GITHUB_APP_CLIENT_ID
GITHUB_APP_INSTALLATION_ID
GITHUB_APP_PRIVATE_KEY_PEM
GITHUB_APP_WEBHOOK_SECRET
GITHUB_APP_WEBHOOK_URL
```

These names are intentionally generic so they can be used in GitHub Actions, Codex cloud, container platforms, or a mobile-managed secret store.

## Manual fallback

If you do not use the helper script, open <https://github.com/settings/apps/new> directly and enter the same values from the table above. For organization ownership, use `https://github.com/organizations/YOUR_ORG/settings/apps/new`.
