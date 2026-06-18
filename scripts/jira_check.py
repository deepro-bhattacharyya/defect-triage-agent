"""Jira connectivity & discovery check (read-only, prints no secrets).

Run this to confirm your Jira credentials work and to discover your project
keys / issue types / priority values before wiring the integration:

    python scripts/jira_check.py

Reads JIRA_BASE_URL / JIRA_EMAIL / JIRA_API_TOKEN from .env.
"""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv()
from app.tools.certs import configure_corporate_tls  # noqa: E402

configure_corporate_tls()
import requests  # noqa: E402


def main():
    base = os.environ.get("JIRA_BASE_URL", "").rstrip("/")
    email = os.environ.get("JIRA_EMAIL", "")
    token = os.environ.get("JIRA_API_TOKEN", "")

    if not (base and email and token):
        print("Missing JIRA_BASE_URL / JIRA_EMAIL / JIRA_API_TOKEN in .env")
        return

    auth = (email, token)
    headers = {"Accept": "application/json"}

    print(f"Connecting to {base} as {email} …")
    r = requests.get(f"{base}/rest/api/3/myself", auth=auth, headers=headers, timeout=20)

    if r.status_code != 200:
        print(f"\n[FAILED] Auth failed (HTTP {r.status_code}): {r.text[:160]}")
        print("   The request reached Jira but the email+token was rejected. Check:")
        print("   1. The API token is current (regenerate at")
        print("      https://id.atlassian.com/manage-profile/security/api-tokens).")
        print("   2. JIRA_EMAIL is the exact email of the Atlassian account that owns the token.")
        print("   3. Your org allows REST API access with API tokens (enterprise policy).")
        return

    me = r.json()
    print(f"[OK] Authenticated as {me.get('displayName')} (accountId {me.get('accountId')})\n")

    print("Projects you can access:")
    r = requests.get(f"{base}/rest/api/3/project/search", auth=auth, headers=headers,
                     params={"maxResults": 50}, timeout=20)
    projects = r.json().get("values", []) if r.status_code == 200 else []
    for p in projects:
        print(f"  {p['key']:<10} {p['name']}  (type={p.get('projectTypeKey')})")
    if not projects:
        print("  (none found)")
        return

    pkey = projects[0]["key"]
    print(f"\nIssue types + priorities for project '{pkey}':")
    r = requests.get(f"{base}/rest/api/3/issue/createmeta", auth=auth, headers=headers,
                     params={"projectKeys": pkey, "expand": "projects.issuetypes.fields"}, timeout=20)
    if r.status_code == 200:
        for proj in r.json().get("projects", []):
            for it in proj.get("issuetypes", []):
                fields = it.get("fields", {})
                prio = [o["name"] for o in fields.get("priority", {}).get("allowedValues", [])]
                print(f"  - {it['name']:<14} priorities={prio}")
    else:
        print(f"  createmeta HTTP {r.status_code}")


if __name__ == "__main__":
    main()
