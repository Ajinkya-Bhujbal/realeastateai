"""
End-to-end test: Gmail -> Parser -> DB -> Dashboard pipeline.
Tests:
  1. .env loading & credential presence
  2. IMAP connection to Gmail
  3. Email fetching (UNSEEN from portals)
  4. Lead parsing (name, phone, email, source, etc.)
  5. DB insertion (dedup check)
  6. Verification: reads back from DB
"""
import os
import sys
import io
import imaplib
import datetime

# Force UTF-8 output on Windows
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

# Ensure we can import sibling modules
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

# ── Colors for terminal output ────────────────────────────────────────
GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
CYAN   = "\033[96m"
BOLD   = "\033[1m"
RESET  = "\033[0m"

def ok(msg):   print(f"  {GREEN}[PASS]{RESET}  {msg}")
def fail(msg): print(f"  {RED}[FAIL]{RESET}  {msg}")
def info(msg): print(f"  {CYAN}[INFO]{RESET}  {msg}")
def warn(msg): print(f"  {YELLOW}[WARN]{RESET}  {msg}")
def header(msg): print(f"\n{BOLD}{'-'*50}\n  {msg}\n{'-'*50}{RESET}")


def test_env():
    """Test 1: .env loading & credential presence."""
    header("TEST 1: .env Configuration")
    gmail_user = os.getenv("GMAIL_USER", "")
    gmail_pass = os.getenv("GMAIL_APP_PASSWORD", "")

    if gmail_user and gmail_user != "your_email@gmail.com":
        ok(f"GMAIL_USER is set: {gmail_user}")
    else:
        fail("GMAIL_USER is not set or still placeholder!")
        print(f"    -> Open .env and set GMAIL_USER=youremail@gmail.com")
        return False

    if gmail_pass and gmail_pass != "your_app_password_here":
        ok(f"GMAIL_APP_PASSWORD is set: {'*' * len(gmail_pass)}")
    else:
        fail("GMAIL_APP_PASSWORD is not set or still placeholder!")
        print(f"    -> Open .env and set GMAIL_APP_PASSWORD=your_16_char_app_password")
        print(f"    -> Get app password: Google Account → Security → 2-Step Verification → App passwords")
        return False

    return True


def test_imap_connection():
    """Test 2: IMAP connection to Gmail."""
    header("TEST 2: Gmail IMAP Connection")
    gmail_user = os.getenv("GMAIL_USER", "")
    gmail_pass = os.getenv("GMAIL_APP_PASSWORD", "")

    try:
        info(f"Connecting to imap.gmail.com as {gmail_user}...")
        mail = imaplib.IMAP4_SSL("imap.gmail.com")
        mail.login(gmail_user, gmail_pass)
        ok("IMAP login successful!")

        # Check inbox
        status, data = mail.select("INBOX")
        if status == "OK":
            msg_count = int(data[0])
            ok(f"INBOX selected — {msg_count} total emails")
        else:
            fail(f"Could not select INBOX: {status}")

        mail.logout()
        return True
    except imaplib.IMAP4.error as e:
        fail(f"IMAP login failed: {e}")
        print(f"    -> Make sure you're using an App Password, not your regular Gmail password")
        print(f"    -> Enable 2-Step Verification first, then create App Password")
        print(f"    -> URL: https://myaccount.google.com/apppasswords")
        return False
    except Exception as e:
        fail(f"Connection error: {e}")
        return False


def test_email_fetch():
    """Test 3: Fetch UNSEEN emails from portals."""
    header("TEST 3: Fetch Portal Emails")
    gmail_user = os.getenv("GMAIL_USER", "")
    gmail_pass = os.getenv("GMAIL_APP_PASSWORD", "")

    try:
        mail = imaplib.IMAP4_SSL("imap.gmail.com")
        mail.login(gmail_user, gmail_pass)
        mail.select("INBOX")

        portals = {
            "Housing.com": '(FROM "housing.com")',
            "99acres": '(FROM "99acres.com")',
            "MagicBricks": '(FROM "magicbricks.com")',
        }

        total_found = 0
        unseen_found = 0
        for portal, query in portals.items():
            # All emails from portal
            status, data = mail.search(None, query)
            all_count = len(data[0].split()) if data[0] else 0
            total_found += all_count

            # Unseen emails from portal
            unseen_query = f'(UNSEEN FROM "{portal.lower().replace("housing.com","housing.com").replace("99acres","99acres.com").replace("magicbricks","magicbricks.com")}")'
            status2, data2 = mail.search(None, f'(UNSEEN {query.strip("()")})')
            unseen_count = len(data2[0].split()) if data2[0] else 0
            unseen_found += unseen_count

            if all_count > 0:
                ok(f"{portal}: {all_count} total emails, {unseen_count} unseen (new)")
            else:
                info(f"{portal}: no emails found in inbox")

        if total_found > 0:
            ok(f"Total portal emails found: {total_found} (unseen: {unseen_found})")
        else:
            warn("No portal emails found! The system will start picking up leads once you receive emails from Housing.com, 99acres, or MagicBricks.")

        mail.logout()
        return total_found, unseen_found
    except Exception as e:
        fail(f"Email fetch error: {e}")
        return 0, 0


def test_parser():
    """Test 4: Parser with sample data."""
    header("TEST 4: Email Parser (sample data)")
    from parser import parse_lead_from_email

    # MagicBricks sample
    mb = parse_lead_from_email(
        subject='Response on your Property Listing',
        body='A user is interested in your Property, ID 80509613: 1 BHK, Multistorey Apartment in Siddharth Nagar Bavdhan, Pune.\n\nDetails of Contact Made:\nSender\'s Name: ajit (Individual)\nMobile: 9604092514\nEmail: ajito18@hotmail.com\nMessage: I am interested in your property.',
        sender='alerts@magicbricks.com'
    )

    checks = [
        ("MagicBricks - source", mb["source"] == "magicbricks"),
        ("MagicBricks - name", mb["name"] == "ajit"),
        ("MagicBricks - phone", mb["phone"] == "9604092514"),
        ("MagicBricks - email", mb["email"] == "ajito18@hotmail.com"),
    ]

    all_pass = True
    for label, result in checks:
        if result:
            ok(label)
        else:
            fail(label)
            all_pass = False

    # 99acres sample
    na = parse_lead_from_email(
        subject='Property Advertisement Query',
        body='You have received a query on Rs15,000 , Flat/Apartment in Yahavi Vanaha Bavdhan Patil Nagar (K88204044) on 99acres.com\n\nDetails of the Query\nDaksh Sharma\n+91-9958323859 (Verified)',
        sender='no-reply@99acres.com'
    )
    checks2 = [
        ("99acres - source", na["source"] == "99acres"),
        ("99acres - name", na["name"] == "Daksh Sharma"),
        ("99acres - phone", na["phone"] == "9958323859"),
    ]
    for label, result in checks2:
        if result:
            ok(label)
        else:
            fail(label)
            all_pass = False

    return all_pass


def test_full_pipeline():
    """Test 5: Full pipeline - fetch from Gmail -> parse -> save to DB -> read back."""
    header("TEST 5: Full Pipeline (Gmail -> DB)")
    from parser import fetch_gmail_leads
    from db import SessionLocal, init_db
    from models import Lead

    gmail_user = os.getenv("GMAIL_USER", "")
    gmail_pass = os.getenv("GMAIL_APP_PASSWORD", "")

    # Init DB
    init_db()
    ok("Database initialized")

    db = SessionLocal()
    try:
        # Count existing leads
        existing_count = db.query(Lead).count()
        info(f"Existing leads in DB: {existing_count}")

        # Fetch from Gmail
        info("Fetching leads from Gmail (UNSEEN portal emails)...")
        leads = fetch_gmail_leads(gmail_user, gmail_pass, max_emails=10)  # latest 10 per portal
        info(f"Parser returned {len(leads)} leads")

        if len(leads) == 0:
            warn("No new UNSEEN portal emails to process. This is normal if:")
            print("    -> You have no emails from Housing.com / 99acres / MagicBricks")
            print("    -> Or all portal emails have already been READ (marked as seen)")
            print()
            info("The auto-poller will check every 60 seconds for new (UNSEEN) emails")
        else:
            created = 0
            skipped = 0
            for parsed in leads:
                name = parsed.get("name", "").strip() or "Unknown"
                phone = parsed.get("phone", "").strip()
                lead_email = parsed.get("email", "").strip()

                # Dedup
                existing = None
                if phone:
                    existing = db.query(Lead).filter(Lead.phone == phone).first()
                if not existing and lead_email:
                    existing = db.query(Lead).filter(Lead.email == lead_email).first()

                if existing:
                    skipped += 1
                    info(f"  Skipped duplicate: {name} ({phone or lead_email})")
                    continue

                lead = Lead(
                    name=name,
                    phone=phone,
                    email=lead_email,
                    source=parsed.get("source", "email"),
                    status="new",
                    budget_min=parsed.get("budget_min"),
                    budget_max=parsed.get("budget_max"),
                    preferred_location=parsed.get("preferred_location", ""),
                    property_type=parsed.get("property_type", ""),
                    notes=parsed.get("notes", "")[:500],
                )
                db.add(lead)
                created += 1

            db.commit()

            if created > 0:
                ok(f"Created {created} new leads in database!")
            if skipped > 0:
                info(f"Skipped {skipped} duplicates")

        # Read back all leads from DB
        header("DATABASE CONTENTS")
        all_leads = db.query(Lead).order_by(Lead.created_at.desc()).limit(20).all()
        if all_leads:
            ok(f"Total leads in database: {db.query(Lead).count()}")
            print()
            print(f"  {'ID':<5} {'Name':<25} {'Phone':<15} {'Source':<15} {'Status':<12} {'Location'}")
            print(f"  {'-'*5} {'-'*25} {'-'*15} {'-'*15} {'-'*12} {'-'*20}")
            for l in all_leads:
                print(f"  {l.id:<5} {(l.name or '')[:24]:<25} {(l.phone or '')[:14]:<15} {(l.source or '')[:14]:<15} {(l.status or '')[:11]:<12} {(l.preferred_location or '')[:20]}")
        else:
            info("No leads in database yet. Leads will appear once portal emails arrive.")

        return True
    except Exception as e:
        fail(f"Pipeline error: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        db.close()


def test_scheduler_config():
    """Test 6: Verify scheduler will start correctly."""
    header("TEST 6: Auto-Polling Scheduler Config")

    gmail_user = os.getenv("GMAIL_USER", "")
    gmail_pass = os.getenv("GMAIL_APP_PASSWORD", "")

    if gmail_user and gmail_pass and gmail_user != "your_email@gmail.com":
        ok("Gmail credentials present → email poller WILL start")
        info("When the server starts, the email poller will:")
        print("    -> Run immediately on startup")
        print("    -> Then every 60 seconds")
        print("    -> Check for UNSEEN emails from Housing.com, 99acres, MagicBricks")
        print("    -> Parse and save new leads to the database")
        print("    -> Dashboard will show them automatically")
    else:
        fail("Gmail credentials missing → email poller will NOT start")

    return True


# ─── Main ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print(f"\n{BOLD}{'='*50}")
    print(f"  LeadPilot - Gmail Pipeline Test")
    print(f"  {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*50}{RESET}")

    results = {}

    # Test 1: .env
    results["env"] = test_env()
    if not results["env"]:
        print(f"\n{RED}{'='*50}")
        print(f"  STOPPED: Fix your .env file first!")
        print(f"{'='*50}{RESET}")
        sys.exit(1)

    # Test 2: IMAP connection
    results["imap"] = test_imap_connection()
    if not results["imap"]:
        print(f"\n{RED}{'='*50}")
        print(f"  STOPPED: Fix Gmail IMAP connection first!")
        print(f"{'='*50}{RESET}")
        sys.exit(1)

    # Test 3: Fetch emails
    total, unseen = test_email_fetch()

    # Test 4: Parser
    results["parser"] = test_parser()

    # Test 5: Full pipeline
    results["pipeline"] = test_full_pipeline()

    # Test 6: Scheduler
    results["scheduler"] = test_scheduler_config()

    # Summary
    print(f"\n{BOLD}{'='*50}")
    print(f"  TEST SUMMARY")
    print(f"{'='*50}{RESET}")
    for name, passed in results.items():
        status = f"{GREEN}PASS{RESET}" if passed else f"{RED}FAIL{RESET}"
        print(f"  {status}  {name}")

    all_pass = all(results.values())
    if all_pass:
        print(f"\n{GREEN}{BOLD}  All tests passed! Your pipeline is ready.{RESET}")
        print(f"  -> Start the server: python backend/main.py")
        print(f"  -> Open dashboard: http://localhost:8000")
        print(f"  -> Leads will auto-ingest every 60 seconds from Gmail")
    else:
        print(f"\n{RED}{BOLD}  Some tests failed. See details above.{RESET}")
