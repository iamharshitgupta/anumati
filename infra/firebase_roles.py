"""Assign Anumati app roles to existing Firebase users from a trusted terminal.

    python -B infra/firebase_roles.py --project PROJECT_ID --uid FIREBASE_UID --role analyst
    python -B infra/firebase_roles.py --project PROJECT_ID --uid FIREBASE_UID --role analyst --apply

The default is an offline preview: no credentials, cloud calls or writes.
--apply uses Application Default Credentials and requires Firebase Auth user-edit
permissions in the explicit project. Look up the UID in Firebase Authentication
-> Users. Staff accounts must have a verified email and an identified sign-in
provider, not an anonymous browser session. This is an application permission,
not a Google Cloud IAM grant. There is no public role-assignment endpoint.

Existing custom claims are preserved. --role user removes only the role claim.
Every assignment revokes existing refresh tokens; the API checks revocation on
each request. Staff cross-account access is API-only; browser Firestore rules
grant no staff override. The user must sign out and sign in again.
Run one assignment at a time; Firebase's claims update replaces the claims map.
Never put service-account keys in the web folder or commit credentials.
"""

from __future__ import annotations

import argparse
import os
import sys


def assign_role(auth, uid: str, role: str, app) -> None:
    user = auth.get_user(uid, app=app)
    if role != "user" and not (user.email_verified and user.email and user.provider_data):
        raise ValueError("Staff roles require an identified account with a verified email")
    claims = dict(user.custom_claims or {})
    if role == "user":
        claims.pop("role", None)
    else:
        claims["role"] = role
    auth.set_custom_user_claims(uid, claims, app=app)
    auth.revoke_refresh_tokens(uid, app=app)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--project", required=True)
    parser.add_argument("--uid", required=True)
    parser.add_argument("--role", required=True, choices=("user", "analyst", "admin"))
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    if not args.project.strip() or "/" in args.project or not args.uid.strip():
        parser.error("An explicit project ID and non-empty Firebase UID are required")
    if os.getenv("FIREBASE_AUTH_EMULATOR_HOST"):
        parser.error("Unset FIREBASE_AUTH_EMULATOR_HOST; this tool targets the cloud")
    print(f"Target: project={args.project}, uid={args.uid}, role={args.role}")
    if not args.apply:
        print("PREVIEW: no cloud calls. Add --apply to assign the role and revoke existing sessions.")
        return 0
    app = None
    try:
        import firebase_admin
        from firebase_admin import auth

        app = firebase_admin.initialize_app(options={"projectId": args.project}, name="anumati-role-setup")
        assign_role(auth, args.uid, args.role, app)
        print("Role assigned; existing sessions revoked. Sign out and sign in again.")
        return 0
    except Exception as exc:
        print(f"ERROR: {exc}. Inspect the user's claims before retrying if assignment partially succeeded.", file=sys.stderr)
        return 1
    finally:
        if app is not None:
            firebase_admin.delete_app(app)


if __name__ == "__main__":
    raise SystemExit(main())
