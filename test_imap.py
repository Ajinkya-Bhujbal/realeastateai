import sys
sys.path.insert(0, './backend')
from parser import parse_lead_from_email, _get_email_bodies
import imaplib, os, email
from dotenv import load_dotenv
load_dotenv()
m = imaplib.IMAP4_SSL('imap.gmail.com')
m.login(os.getenv('GMAIL_USER'), os.getenv('GMAIL_APP_PASSWORD'))
m.select('inbox')

print("\n--- Testing MagicBricks ---")
typ, data = m.fetch('11266,11268,11275,11276', '(RFC822)')
for item in data:
    if isinstance(item, tuple):
        msg = email.message_from_bytes(item[1])
        subject = msg.get('Subject', '')
        sender = msg.get('From', '')
        body, html_body = _get_email_bodies(msg)
        lead = parse_lead_from_email(subject, body, sender, html_body)
        print(subject)
        print(lead)

print("\n--- Testing 99acres ---")
typ, data = m.fetch('11274,11277,11278,11285', '(RFC822)')
for item in data:
    if isinstance(item, tuple):
        msg = email.message_from_bytes(item[1])
        subject = msg.get('Subject', '')
        sender = msg.get('From', '')
        body, html_body = _get_email_bodies(msg)
        lead = parse_lead_from_email(subject, body, sender, html_body)
        print(subject)
        print(lead)
