"""Invitation and password reset emails. Sent over SMTP when it is configured (core.conf.email_configured); otherwise the person who
invited copies the link from the app. A failed send never cancels the invitation: the link still works."""

import logging
from html import escape

from django.core.mail import EmailMultiAlternatives

from core.common.timeutil import now_utc, to_uae
from core.conf import email_configured
from core.models import ROLE_LABELS, Invitation

log = logging.getLogger("emails")

PRODUCT = "AVAIBE LinkedIn Intelligence"


def _html(heading: str, intro: str, button: str, link: str, note: str) -> str:
    """The shared email layout: product name, heading, one button, a note and the plain link."""
    return f"""<!doctype html>
<html><body style="margin:0;padding:24px;background:#f3f2f0;font-family:Segoe UI,Helvetica,Arial,sans-serif;color:#1c1b1a">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr><td align="center">
    <table role="presentation" width="520" cellpadding="0" cellspacing="0" style="max-width:520px;background:#ffffff;border-radius:16px;padding:32px">
      <tr><td style="font-size:13px;letter-spacing:.04em;text-transform:uppercase;color:#6b6865">{escape(PRODUCT)}</td></tr>
      <tr><td style="padding-top:16px;font-size:20px;font-weight:600">{escape(heading)}</td></tr>
      <tr><td style="padding-top:12px;font-size:15px;line-height:1.5">{escape(intro)}</td></tr>
      <tr><td style="padding-top:24px">
        <a href="{escape(link)}" style="display:inline-block;background:#c4482a;color:#ffffff;text-decoration:none;font-weight:600;font-size:15px;padding:12px 22px;border-radius:999px">{escape(button)}</a>
      </td></tr>
      <tr><td style="padding-top:24px;font-size:13px;line-height:1.5;color:#6b6865">{escape(note)}</td></tr>
      <tr><td style="padding-top:12px;font-size:12px;line-height:1.5;color:#8a8682;word-break:break-all">If the button does not work, open this link: {escape(link)}</td></tr>
    </table>
  </td></tr></table>
</body></html>"""


def _uae(dt) -> str:
    return to_uae(dt).strftime("%d %B %Y, %H:%M") + " (UAE time)"


def _content(inv: Invitation, link: str, inviter: str) -> tuple[str, str, str]:
    """(subject, plain text, html) for one invitation."""
    role = ROLE_LABELS[inv.role]
    where = inv.company.name if inv.company_id else PRODUCT
    subject = f"Invitation to join {where}" if inv.company_id else f"Invitation to join {PRODUCT} as an owner"
    intro = f"{inviter} has invited you to join {where} as {role}." if inv.company_id else f"{inviter} has invited you to join {PRODUCT} as an owner."
    note = f"This link can be used once and expires on {_uae(inv.expires_at)}. If you were not expecting this invitation, you can ignore this email."
    text = f"{intro}\n\nAccept the invitation and set up your account:\n{link}\n\n{note}\n"
    return subject, text, _html(subject, intro, "Accept invitation", link, note)


def _send(to: str, subject: str, text: str, html: str, what: str) -> bool:
    msg = EmailMultiAlternatives(subject, text, to=[to])
    msg.attach_alternative(html, "text/html")
    try:
        msg.send()
    except Exception as e:  # SMTP, network or authentication: the cause goes to the log only
        log.warning("%s: email not sent (%s)", what, type(e).__name__)
        return False
    return True


def send_invitation(inv: Invitation, link: str, inviter: str) -> bool:
    """Email the sign-up link. True when sent (and recorded on the invitation); False when email is off or the
    mail server refused. The reason is logged, never shown with server details."""
    if not email_configured():
        return False
    subject, text, html = _content(inv, link, inviter)
    if not _send(inv.email, subject, text, html, f"Invitation {inv.id}"):
        return False  # the link still works and is shown to copy
    inv.emailed_at = now_utc()
    inv.save(update_fields=["emailed_at"])
    return True


def send_password_reset(email: str, link: str, expires_at) -> bool:
    """Email a password reset link. False when email is off or the mail server refused."""
    if not email_configured():
        return False
    subject = "Reset your password"
    intro = f"A password reset was requested for your {PRODUCT} account ({email})."
    note = (
        f"This link can be used once and expires on {_uae(expires_at)}. If you did not request a password reset, "
        "you can ignore this email; your password will not change."
    )
    text = f"{intro}\n\nChoose a new password:\n{link}\n\n{note}\n"
    return _send(email, subject, text, _html(subject, intro, "Reset password", link, note), "Password reset")
