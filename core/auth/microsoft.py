"""Microsoft Entra ID (MSAL) client for sign-in. Configured from MS_* in .env (see docs/microsoft-signin-setup.md)."""

import os

SCOPES = ["User.Read"]  # openid/profile/offline_access are added by MSAL automatically

def msal_app():
    """Separated so tests can replace it with a fake."""
    import msal

    return msal.ConfidentialClientApplication(
        os.getenv("MS_CLIENT_ID", ""),
        authority=f"https://login.microsoftonline.com/{os.getenv('MS_TENANT_ID', '')}",
        client_credential=os.getenv("MS_CLIENT_SECRET", ""),
    )
