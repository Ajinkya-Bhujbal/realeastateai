"""Debug: Housing.com full HTML + 99acres name area."""
import os, sys, io, imaplib, email, re
from email.header import decode_header
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

mail = imaplib.IMAP4_SSL("imap.gmail.com")
mail.login(os.getenv("GMAIL_USER"), os.getenv("GMAIL_APP_PASSWORD"))
mail.select("INBOX")

# HOUSING.COM - full HTML around Contact/Call/Name
status, data = mail.search(None, '(FROM "housing.com")')
email_ids = data[0].split()
eid = email_ids[-1]
status, msg_data = mail.fetch(eid, "(RFC822)")
msg = email.message_from_bytes(msg_data[0][1])

html_body = ""
if msg.is_multipart():
    for part in msg.walk():
        if part.get_content_type() == "text/html" and not html_body:
            try: html_body = part.get_payload(decode=True).decode("utf-8", errors="replace")
            except: pass

# Find the Contact/Call area in HTML (3000-6000 chars is usually where it is)
html_clean = re.sub(r'\s+', ' ', html_body)
print(f"=== HOUSING.COM FULL HTML (chars 2000-5000) ===")
print(html_clean[2000:5000])

print(f"\n\n=== ALL HREF LINKS IN HOUSING EMAIL ===")
links = re.findall(r'href="([^"]+)"', html_body)
for link in links:
    if any(x in link.lower() for x in ['call', 'tel', 'wa.me', 'whatsapp', 'hsng.co', 'phone']):
        print(f"  {link[:150]}")

print(f"\n=== ALL 'Call' or 'Contact' text areas ===")
# Find text near Call Now, Send Email, Chat buttons
for m in re.finditer(r'(Call\s*Now|Send\s*Email|Chat\s*On|Contact)', html_body, re.IGNORECASE):
    start = max(0, m.start() - 200)
    end = min(len(html_body), m.end() + 100)
    snippet = re.sub(r'\s+', ' ', html_body[start:end])
    print(f"  Near '{m.group()}': ...{snippet}...")

# 99acres - find name area
print(f"\n\n=== 99ACRES - Name/Contact Area ===")
status, data = mail.search(None, '(FROM "99acres.com")')
email_ids = data[0].split()
eid = email_ids[-1]
status, msg_data = mail.fetch(eid, "(RFC822)")
msg = email.message_from_bytes(msg_data[0][1])

html_body = ""
if msg.is_multipart():
    for part in msg.walk():
        if part.get_content_type() == "text/html" and not html_body:
            try: html_body = part.get_payload(decode=True).decode("utf-8", errors="replace")
            except: pass

# Find area around "Contact Details" or "Details of the Query"
for keyword in ['Contact Details', 'Details of the Query', 'Buyer Name', 'tel:']:
    idx = html_body.find(keyword)
    if idx >= 0:
        start = max(0, idx - 100)
        end = min(len(html_body), idx + 500)
        snippet = re.sub(r'\s+', ' ', html_body[start:end])
        print(f"\n  Near '{keyword}':")
        print(f"  {snippet}")

mail.logout()
