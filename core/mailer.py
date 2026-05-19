"""Mailer — sends emails via SMTP with TLS."""
import smtplib
import os
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication


class PantherMailer:
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
        Send a single email with optional attachment.
        Returns {'ok': bool, 'error': str}.
        """
        try:
            msg = MIMEMultipart('mixed')
            msg['From'] = f"{self.from_name} <{self.user}>"
            msg['To'] = to
            if cc:
                msg['CC'] = cc
            msg['Subject'] = subject

            # Body as plain text
            msg.attach(MIMEText(body, 'plain', 'utf-8'))

            # Attachment
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

            # Connect and send
            if self.use_tls:
                server = smtplib.SMTP(self.host, self.port, timeout=30)
                server.ehlo()
                server.starttls()
                server.ehlo()
            else:
                server = smtplib.SMTP(self.host, self.port, timeout=30)

            server.login(self.user, self.password)

            # Build recipient list (To + CC)
            recipients = [to]
            if cc:
                cc_list = [e.strip() for e in cc.split(',') if e.strip()]
                recipients.extend(cc_list)

            server.sendmail(self.user, recipients, msg.as_bytes())
            server.quit()
            return {'ok': True}

        except smtplib.SMTPException as e:
            return {'ok': False, 'error': str(e)}
        except Exception as e:
            return {'ok': False, 'error': str(e)}

    def send_test(self, to: str = None) -> dict:
        """Send a minimal test email to the configured SMTP address."""
        test_recipient = to or self.user
        try:
            msg = MIMEMultipart('mixed')
            msg['From'] = f"{self.from_name} <{self.user}>"
            msg['To'] = test_recipient
            msg['Subject'] = f'{self.from_name} — Test Email'

            body = (
                f'This is a test email from {self.from_name}.\n'
                "If you received this, your SMTP settings are configured correctly.\n\n"
                "SMTP Host: {host}\nPort: {port}\n"
            ).format(host=self.host, port=self.port)

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