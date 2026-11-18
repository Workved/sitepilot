"""Creates the WhatsApp starter templates (WHATSAPP_TEMPLATES.md) in Meta.

Submits each template to the Graph API's
`POST /{waba_id}/message_templates`, the same thing WhatsApp Manager's
"Create template" form does. Meta then reviews each one; check their status
in WhatsApp Manager -> Message templates.

Standard library only, so it runs with the system Python - no backend
container or virtualenv needed. Reads WHATSAPP_ACCESS_TOKEN (and optionally
WHATSAPP_API_VERSION) from the environment or the repo-root .env.

Usage:

    python3 tools/create_whatsapp_templates.py --waba-id <WhatsApp Business Account ID> --dry-run
    python3 tools/create_whatsapp_templates.py --waba-id <WhatsApp Business Account ID>
    python3 tools/create_whatsapp_templates.py --waba-id <id> --only task_status_update

The WABA ID is shown in the developer dashboard under WhatsApp -> API Setup
("WhatsApp Business Account ID"); it is NOT the Phone Number ID. The token
needs the whatsapp_business_management permission (the API Setup page's
token has it).

Each body's variable count is checked against the `variable_order` the
backend sends (backend/app/services/message_templates.py) before anything
is submitted, so Meta and the code can't drift apart.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.services.message_templates import TEMPLATE_REGISTRY  # noqa: E402 - stdlib-only module

LANGUAGE = "en"
CATEGORY = "UTILITY"

# name -> (body, sample values in {{1}}, {{2}}, ... order). Keep in sync with
# WHATSAPP_TEMPLATES.md.
STARTER_TEMPLATES: dict[str, tuple[str, list[str]]] = {
    "task_status_update": (
        "SiteOps update for project {{1}}: task {{2}} has moved from {{3}} to {{4}}. Note: {{5}}. "
        "Open SiteOps for details.",
        ["Futurex Office", "T003 - Flooring", "Ready", "In progress", "Material delivered"],
    ),
    "task_approval_decision": (
        "SiteOps: task {{1}} on project {{2}} has been {{3}}. Remarks: {{4}}. Open SiteOps for details.",
        ["T003 - Flooring", "Futurex Office", "Approved", "Finish quality is good"],
    ),
    "task_blocker_alert": (
        "SiteOps alert: a blocker was raised on task {{1}} (project {{2}}). Type: {{3}}. Details: {{4}}. "
        "Please review it in SiteOps.",
        ["T003 - Flooring", "Futurex Office", "Material shortage", "Tiles not delivered yet"],
    ),
    "task_delay_recorded": (
        "SiteOps: task {{1}} on project {{2}} has a delay of {{3}} day(s) recorded. Responsibility: {{4}}. "
        "Please review it in SiteOps.",
        ["T003 - Flooring", "Futurex Office", "2", "Vendor"],
    ),
    "task_vendor_assigned": (
        "SiteOps: you have been assigned task {{1}} on project {{2}}. Reply ACCEPT {{3}} to accept this job, "
        "or reply DECLINE followed by the same code to decline.",
        ["T003 - Flooring", "Futurex Office", "1A2B3C4D"],
    ),
    "task_sla_overdue": (
        "SiteOps reminder: task {{1}} on project {{2}} was due on {{3}} and is still open. "
        "Please update it in SiteOps today.",
        ["T003 - Flooring", "Futurex Office", "05 Nov 2026"],
    ),
    "external_approval_assigned": (
        "SiteOps: you have been assigned the approval {{1}} for project {{2}}, due {{3}}. "
        "Reply GATEACCEPT {{4}} to accept, or reply GATEDECLINE followed by the same code to decline.",
        ["Fire NOC", "Futurex Office", "25 Dec 2026", "A1B2C3D4"],
    ),
    "project_broadcast_announcement": (
        "SiteOps announcement for project {{1}}: {{2}}. {{3}} - Sent by your SiteOps admin.",
        ["Futurex Office", "Site closed Saturday", "The site will be closed for inspection this Saturday."],
    ),
}


def read_env(key: str) -> str:
    if os.environ.get(key):
        return os.environ[key]
    env_file = REPO_ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            name, _, value = line.partition("=")
            if name.strip() == key:
                return value.strip().strip('"').strip("'")
    return ""


def check_against_backend() -> list[str]:
    """Every starter body must use exactly as many variables, numbered 1..N,
    as the backend sends for that template, with one sample per variable."""
    errors = []
    sent_counts = {spec.meta_template_name: len(spec.variable_order) for spec in TEMPLATE_REGISTRY.values()}
    for name, (body, samples) in STARTER_TEMPLATES.items():
        numbers = sorted({int(n) for n in re.findall(r"\{\{(\d+)\}\}", body)})
        if name not in sent_counts:
            errors.append(f"{name}: not a template name the backend sends")
        elif numbers != list(range(1, sent_counts[name] + 1)):
            errors.append(f"{name}: body uses {numbers}, backend sends {sent_counts[name]} variables")
        if len(samples) != len(numbers):
            errors.append(f"{name}: {len(numbers)} variables but {len(samples)} samples")
    return errors


def build_request(name: str) -> dict:
    body, samples = STARTER_TEMPLATES[name]
    return {
        "name": name,
        "language": LANGUAGE,
        "category": CATEGORY,
        "components": [{"type": "BODY", "text": body, "example": {"body_text": [samples]}}],
    }


def submit(url: str, token: str, payload: dict) -> tuple[bool, str]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            data = json.loads(response.read() or b"{}")
            return True, f"submitted (id={data.get('id')}, status={data.get('status')}, category={data.get('category')})"
    except urllib.error.HTTPError as exc:
        try:
            error = json.loads(exc.read() or b"{}").get("error", {})
        except json.JSONDecodeError:
            error = {}
        detail = error.get("error_user_msg") or error.get("message") or f"HTTP {exc.code}"
        return False, f"FAILED: {detail} (code {error.get('code')}, subcode {error.get('error_subcode')})"
    except urllib.error.URLError as exc:
        return False, f"FAILED: network error: {exc.reason}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--waba-id", required=True, help="WhatsApp Business Account ID (not the Phone Number ID)")
    parser.add_argument("--only", action="append", choices=sorted(STARTER_TEMPLATES), help="Create just this template (repeatable)")
    parser.add_argument("--dry-run", action="store_true", help="Print the requests without sending anything")
    args = parser.parse_args()

    errors = check_against_backend()
    if errors:
        print("Templates do not match what the backend sends - nothing submitted:")
        for error in errors:
            print(f"  - {error}")
        return 1

    names = args.only or list(STARTER_TEMPLATES)
    url = f"https://graph.facebook.com/{read_env('WHATSAPP_API_VERSION') or 'v21.0'}/{args.waba_id}/message_templates"

    if args.dry_run:
        print(f"Dry run - would POST to {url}:\n")
        for name in names:
            print(json.dumps(build_request(name), indent=2, ensure_ascii=False), end="\n\n")
        return 0

    token = read_env("WHATSAPP_ACCESS_TOKEN")
    if not token:
        print("WHATSAPP_ACCESS_TOKEN is not set (environment or repo-root .env).")
        return 1

    failures = 0
    for name in names:
        ok, message = submit(url, token, build_request(name))
        failures += not ok
        print(f"{name}: {message}")

    print(f"\n{len(names) - failures} of {len(names)} submitted. Meta reviews each one - check WhatsApp Manager -> Message templates.")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
