"""Sign-in and identity: passwords, tokens, invitations, companies. See docs/auth.md for the design.

- passwords.py    rules for a new password (Django's validators), setting and checking it
- tokens.py       sessions, access tokens (signed JWT) and refresh tokens (rotated, stored as hashes)
- signin.py       email + password sign-in with a lock after repeated failures
- invitations.py  invite-only sign-up links
- companies.py    creating and changing companies
- audit.py        filling created_by / updated_by

Nothing here knows about HTTP: views in core/api/views/auth.py turn these results into cookies and responses.
"""


class AuthError(Exception):
    """Something about a sign-in, token or invitation is wrong. `code` is stable (the app and tests match on it),
    the message is safe to show to the person."""

    def __init__(self, code: str, message: str, status: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
