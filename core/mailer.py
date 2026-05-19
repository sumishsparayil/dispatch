"""
Mailer — sends emails via SMTP with TLS.

Wraps Python's smtplib with a clean interface:
  - send()      : single email with optional Excel attachment
  - send_test() : minimal connectivity test email

Settings dict expected keys:
  smtp_host, smtp_port, smtp_user, smtp_pass, from_name, use_tls

TLS is enabled by default (port 587). SSL (port 465) should set use_tls=False.
"""

import smtplib
import os
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication


class PantherMailer:
    """
    SMTP mailer for Dispatch.

    Parameters
    ----------
    settings : dict
        SMTP configuration. Keys: smtp_host, smtp_port, smtp_user, smtp_pass,
        from_name (display name), use_tls (bool, default True).
    """

    def __init__(self, settings: dict):
        self.host = settings.get('smtp_host', '')
        self.port = int(settings.get('smtp_port') or 587)
        self.user = settings.get('smtp_user', '')
        self.password = settings.get('smtp_pass', '')
        self.from_name = settings.get('from_name', 'KLM Axiva MIS')
        self.use_tls = settings.get('use_tls', True)

    def send(
        self,
        to: str,
        cc: str,
        subject: str,
        body: str,
        attachment_path: str = None,
    ) -> dict:
        """
        Send a single email with an optional Excel attachment.

        Parameters
        ----------
        to : str
            Primary recipient email address.
        cc : str
            Carbon-copy recipients. Comma-separated or empty string.
        subject : str
            Email subject line. Should already be rendered with branch-specific
            variables by the engine.
        body : str
            Plain-text email body. Rendered template from the engine.
        attachment_path : str, optional
            Absolute path to a per-branch .xlsx file to attach.
            The file is deleted after sending if auto_delete=True in engine settings.

        Returns
        -------
        dict
            {'ok': bool, 'error': str or None}
            'ok' is True on successful send; 'error' contains the SMTP exception
            message on failure.
        """
        try:
            msg = MIMEMultipart('mixed')
            msg['From'] = f"{self.from_name} <{self.user}>"
            msg['To'] = to
            if cc:
                msg['CC'] = cc
            msg['Subject'] = subject

            # Plain-text body (not HTML — plain text is more compatible)
            msg.attach(MIMEText(body, 'plain', 'utf-8'))

            # ── Attachment ──────────────────────────────────────────────
            if attachment_path and os.path.exists(attachment_path):
                with open(attachment_path, 'rb') as f:
                    part = MIMEApplication(
                        f.read(),
                        Name=os.path.basename(attachment_path)
                    )
                part['Content-Disposition'] = (
                    f'attachment; filename="{os.path.basename(attachment_path)}"'
                )
                msg.attach(part)

            # ── Connect and send ────────────────────────────────────────
            if self.use_tls:
                # STARTTLS on port 587 (standard Gmail / most SMTP providers)
                server = smtplib.SMTP(self.host, self.port, timeout=30)
                server.ehlo()
                server.starttls()
                server.ehlo()
            else:
                # Implicit SSL on port 465
                server = smtplib.SMTP(self.host, self.port, timeout=30)

            server.login(self.user, self.password)

            # Build full recipient list (To + CC recipients must all be in the SMTP RCPT list)
            recipients = [to]
            if cc:
                recipients.extend(
                    e.strip() for e in cc.split(',') if e.strip()
                )

            server.sendmail(self.user, recipients, msg.as_bytes())
            server.quit()
            return {'ok': True}

        except smtplib.SMTPException as e:
            return {'ok': False, 'error': str(e)}
        except Exception as e:
            return {'ok': False, 'error': str(e)}

    def send_test(self, to: str = None) -> dict:
        """
        Send a minimal test email to verify SMTP connectivity.

        The test email is sent to the operator's own SMTP address by default,
        confirming both that the server can reach the SMTP host AND that the
        username/password credentials are valid.

        Parameters
        ----------
        to : str, optional
            Override recipient. Defaults to self.user (operator's own email).

        Returns
        -------
        dict
            {'ok': bool, 'error': str or None}
        """
        test_recipient = to or self.user
        try:
            msg = MIMEMultipart('mixed')
            msg['From'] = f"{self.from_name} <{self.user}>"
            msg['To'] = test_recipient
            msg['Subject'] = f'{self.from_name} — Test Email'

            body = (
                f'This is a test email from {self.from_name}.\n'
                "If you received this, your SMTP settings are configured correctly.\n\n"
                f"SMTP Host: {self.host}\n"
                f"Port: {self.port}\n"
            )

            msg.attach(MIMEText(body, 'plain', 'utf-8'))

            if self.use_tls:
                server = smtplib.SMTP(self.host, self.port, timeout=30)
                server.ehlo()
                server.starttls()
                server.ehlo()
            else:
                server = smtplib.SMTP(self.host, self.port, timeout=30)

            server.login(self.user, self.password)
            server.sendmail(self.user, [test_recipient], msg.as_bytes())
            server.quit()
            return {'ok': True}

        except Exception as e:
            return {'ok': False, 'error': str(e)}