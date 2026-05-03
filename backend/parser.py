"""
Email parser - extracts lead info from Housing.com, 99acres, MagicBricks emails.
Handles actual notification email formats from each portal.
Also supports Gmail API ingestion.
"""
import re
import imaplib
import email
from email.header import decode_header
from typing import Optional
from html.parser import HTMLParser


def parse_lead_from_email(subject: str, body: str, sender: str = "", html_body: str = "") -> dict:
    """
    Parse lead information from a real estate portal email.
    Returns dict with: name, phone, email, source, budget, location, property_type, notes
    """
    source = detect_source(sender, subject, body)

    result = {
        "name": "",
        "phone": "",
        "email": "",
        "source": source,
        "budget_min": None,
        "budget_max": None,
        "preferred_location": "",
        "property_type": "",
        "configuration": "",
        "price": "",
        "notes": "",
    }

    # Use portal-specific parsers for precise extraction
    if source == "magicbricks":
        result = _parse_magicbricks(subject, body, html_body, result)
    elif source == "99acres":
        result = _parse_99acres(subject, body, html_body, result)
    elif source == "housing":
        result = _parse_housing(subject, body, html_body, result)
    else:
        # Generic fallback
        result["name"] = extract_name(body, subject)
        result["phone"] = extract_phone(body + " " + html_body)
        result["email"] = extract_email(body, sender)
        result["budget_min"], result["budget_max"] = extract_budget(body)
        result["preferred_location"] = extract_location(body, subject)
        result["property_type"] = extract_property_type(body, subject)

    # Notes = trimmed raw body
    result["notes"] = body[:500] if body else ""

    # Generic extractions for configuration and price
    combined = (subject + " " + body + " " + html_body).replace("\n", " ")
    
    # Extract Configuration (e.g., 1BHK, 2BHK, 3BHK)
    if not result.get("configuration"):
        config_match = re.search(r'([1-4])\s*BHK', combined, re.IGNORECASE)
        if config_match:
            result["configuration"] = f"{config_match.group(1)}BHK"

    # Extract Price (e.g., Rs 5200000, ₹ 18.0k, ₹ 1.2 Cr)
    if not result.get("price"):
        # Look for currency symbols followed by numbers and optional multipliers like k, L, Cr, Lac, Lakh
        price_match = re.search(r'(?:Rs\.?|₹|INR)\s*([\d,.]+\s*(?:k|L|Cr|Lac|Lakhs|Crores|Lakh)?)', combined, re.IGNORECASE)
        if price_match:
            result["price"] = price_match.group(0).strip()
        else:
            # Maybe price is just mentioned with Budget: or Price:
            price_match2 = re.search(r'(?:Price|Budget|Rent)\s*[:\-]\s*([\d,.]+\s*(?:k|L|Cr|Lac|Lakhs|Crores|Lakh)?)', combined, re.IGNORECASE)
            if price_match2:
                result["price"] = price_match2.group(1).strip()

    return result


# ─── MagicBricks Parser ──────────────────────────────────────────────
# Format:
#   "Response on your Property Listing"
#   "A user is interested in your Property, ID 80509613: 1 BHK, Multistorey Apartment in
#    Siddharth Nagar Bavdhan, Pune."
#   "Details of Contact Made:"
#   "Sender's Name: ajit (Individual)"
#   "Mobile: 9604092514"
#   "Email: ajito18@hotmail.com"
#   "Message: I am interested in your property."

def _parse_magicbricks(subject: str, body: str, html_body: str, result: dict) -> dict:
    # Strip HTML tags to get clean text for matching
    clean_html = _html_to_text(html_body) if html_body else ""
    combined = body + "\n" + clean_html

    # Name: "Sender's Name: ajit (Individual)" or "Sender's Name: ajit"
    match = re.search(r"Sender'?s?\s*Name\s*[:\-–]\s*(.+?)(?:\(|$|\n)", combined, re.IGNORECASE)
    if match:
        result["name"] = match.group(1).strip().rstrip(".,")
    else:
        match = re.search(r"Name\s*[:\-–]\s*(.+?)(?:\n|$)", combined, re.IGNORECASE)
        if match:
            result["name"] = match.group(1).strip().rstrip(".,")

    # Phone: "Mobile: 9604092514" — now works because HTML tags are stripped
    match = re.search(r"(?:Mobile|Phone|Contact|Cell)\s*[:\-–]\s*\+?(\d[\d\s\-]{8,14})", combined, re.IGNORECASE)
    if match:
        phone = re.sub(r"[\s\-]", "", match.group(1))[-10:]
        result["phone"] = phone if is_valid_indian_phone(phone) else ""
    if not result["phone"]:
        result["phone"] = extract_phone(combined + "\n" + (html_body or ""))

    # Email: "Email: ajito18@hotmail.com"
    match = re.search(r"Email\s*[:\-–]\s*([\w.+-]+@[\w-]+\.[\w.-]+)", combined, re.IGNORECASE)
    if match:
        result["email"] = match.group(1).lower()

    # Property: "1 BHK, Multistorey Apartment in Siddharth Nagar Bavdhan, Pune"
    match = re.search(
        r"Property.*?:\s*(.+?)(?:\.|Details|$)",
        combined, re.IGNORECASE | re.DOTALL,
    )
    if match:
        prop_text = match.group(1).strip()
        # Extract BHK
        bhk = re.search(r"([1-4])\s*BHK", prop_text, re.IGNORECASE)
        if bhk:
            result["configuration"] = f"{bhk.group(1)}BHK"
            result["property_type"] = "apartment"
        else:
            result["property_type"] = extract_property_type(prop_text, subject)
        # Extract location: after "in" or "at"
        loc = re.search(r"(?:in|at)\s+(.+?)(?:\.|$)", prop_text, re.IGNORECASE)
        if loc:
            result["preferred_location"] = loc.group(1).strip().rstrip(".,")

    # Message from lead
    match = re.search(r"Message\s*[:\-–]\s*(.+?)(?:Click|$)", combined, re.IGNORECASE | re.DOTALL)
    if match:
        msg = match.group(1).strip()
        if msg:
            result["notes"] = f"Message: {msg[:300]}"

    if not result["property_type"]:
        result["property_type"] = extract_property_type(combined, subject)
    if not result["preferred_location"]:
        result["preferred_location"] = extract_location(combined, subject)

    return result


# ─── 99acres Parser ──────────────────────────────────────────────────
# Format:
#   "Property Advertisement Query"
#   "You have received a query on Rs15,000 , Flat/Apartment in Yahavi Vanaha
#    Bavdhan Patil Nagar (K88204044) on 99acres.com"
#   "Details of the Query"
#   "Daksh Sharma"
#   "+91-9958323859 (Verified)"

def _parse_99acres(subject: str, body: str, html_body: str, result: dict) -> dict:
    combined = body + "\n" + html_body

    # Phone: from HTML tel: links like tel:+91-8871817930
    phone_match = re.search(r'href="tel:\+?91[\s\-]?(\d{10})"', html_body or "", re.IGNORECASE)
    if phone_match:
        phone = phone_match.group(1)
        if is_valid_indian_phone(phone):
            result["phone"] = phone
    if not result["phone"]:
        # Fallback: "+91-9958323859 (Verified)" in text
        match = re.search(r"\+?91[\s\-]?(\d{10})", combined)
        if match and is_valid_indian_phone(match.group(1)):
            result["phone"] = match.group(1)
    if not result["phone"]:
        result["phone"] = extract_phone(combined)

    # Name: from text body
    if not result["name"]:
        clean_text = _html_to_text(html_body) if html_body else body
        lines = clean_text.split('\n')
        for i, line in enumerate(lines):
            if "details of the response" in line.lower() or "details of the query" in line.lower():
                for j in range(i + 1, min(i + 40, len(lines))):
                    name_line = lines[j].strip()
                    if name_line and not re.match(r'^[\+\d\-\(\)\s]+$', name_line) and "@" not in name_line and "verified" not in name_line.lower():
                        result["name"] = name_line.split('[')[0].strip()
                        break
                break

    # Property + Price: "query on Rs15,000 , Flat/Apartment in Yahavi Vanaha Bavdhan Patil Nagar"
    # Or "response on Rs21,500 , 2 BHK, Flat/Apartment in Yahavi"
    match = re.search(
        r"(?:query|response)\s+on\s+(?:Rs\.?\s*)?(\d[\d,]+(?:\.\d+)?)\s*,?\s*(.+?)(?:\(|on\s+99acres|$)",
        combined, re.IGNORECASE,
    )
    if match:
        price_str = match.group(1).replace(",", "")
        price = float(price_str)
        prop_text = match.group(2).strip()

        # Determine if rent or sale price
        if price < 100000:  # Under 1 lakh = monthly rent
            result["notes"] = f"Monthly Rent: ₹{price_str}"
        else:
            result["budget_min"] = price / 100000  # Convert to lakhs
            result["budget_max"] = result["budget_min"]

        # Property type from text like "Flat/Apartment in Yahavi..."
        bhk = re.search(r"([1-4])\s*BHK", prop_text, re.IGNORECASE)
        if bhk:
            result["configuration"] = f"{bhk.group(1)}BHK"
            result["property_type"] = "apartment"
        elif "flat" in prop_text.lower() or "apartment" in prop_text.lower():
            result["property_type"] = "apartment"
        else:
            result["property_type"] = extract_property_type(prop_text, subject)

        # Location: after "in"
        loc = re.search(r"(?:in|at)\s+(.+?)$", prop_text, re.IGNORECASE)
        if loc:
            result["preferred_location"] = loc.group(1).strip().rstrip(".,")

    # Email from combined
    email_match = re.search(r"[\w.+-]+@[\w-]+\.[\w.-]+", combined)
    if email_match:
        found = email_match.group(0).lower()
        if "99acres" not in found and "ravindrabhujbal" not in found: # avoid agent email in tracker url
            result["email"] = found
    
    # Check text body specifically for email since combined has tracking URLs
    if not result.get("email") or "ravindrabhujbal" in result["email"]:
        clean_text = _html_to_text(html_body) if html_body else body
        email_match2 = re.search(r"[\w.+-]+@[\w-]+\.[\w.-]+", clean_text)
        if email_match2:
            found = email_match2.group(0).lower()
            if "99acres" not in found:
                result["email"] = found

    if not result["property_type"]:
        result["property_type"] = extract_property_type(combined, subject)
    if not result["preferred_location"]:
        result["preferred_location"] = extract_location(combined, subject)

    return result


# ─── Housing.com Parser ──────────────────────────────────────────────
# Format:
#   Subject: "Upasana Satpathy would like to talk to you"
#   "Name: Upasana Satpathy"
#   "Email:" [Send Email button — mailto link in HTML]
#   "Contact:" [Call Now button — tel: link] [Chat On WhatsApp — wa.me link]
#   "who would like to talk to you regarding your 1 BHK Apartment:"
#   "1 BHK Apartment"
#   "Shapoorji Palonji Vanaha Bavdhan"
#   "₹ 18.0k"
#
# Phone is HIDDEN in HTML links: wa.me/91XXXXXXXXXX or tel:+91XXXXXXXXXX
# Solution: follow the hsng.co redirect URLs to get the actual phone number


def _follow_housing_redirect(html_body: str) -> str:
    """Follow Housing.com's hsng.co redirect URLs to extract lead phone number.
    
    The redirect chain is:
      awstrack.me/L0/https://hsng.co/HOUSNG/xxx/...
        -> pahal.housing.com/lead/cta/number?phone=+91XXXXXXXXXX
        -> or api.whatsapp.com/send?phone=+91XXXXXXXXXX
    
    We extract the inner hsng.co URL and follow it to get the phone.
    """
    from urllib.request import urlopen, Request
    from urllib.parse import unquote
    
    # Extract inner hsng.co URLs from the awstrack.me tracking wrappers
    # This avoids hitting the awstrack.me server (which often returns 400)
    awstrack_urls = re.findall(r'href="([^"]*awstrack[^"]*HOUSNG[^"]*)"', html_body, re.IGNORECASE)
    redirect_urls = []
    for aw_url in awstrack_urls:
        match = re.search(r'/L0/(https?[^/]+)/1/', aw_url)
        if match:
            redirect_urls.append(unquote(match.group(1)))
    
    # Fallback: direct hsng.co URLs
    if not redirect_urls:
        redirect_urls = re.findall(r'href="(https?://hsng\.co/HOUSNG/[^"]*)"', html_body, re.IGNORECASE)
    
    # Try URLs until we find a phone
    for rurl in redirect_urls:
        try:
            req = Request(rurl, headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            })
            resp = urlopen(req, timeout=4)
            final_url = resp.geturl()
            
            # Extract phone from final URL
            phone_match = re.search(r'phone=(?:%2B|\+)?(\d{10,13})', final_url)
            if not phone_match:
                phone_match = re.search(r'wa\.me/(\d{10,13})', final_url)
            
            if phone_match:
                phone = phone_match.group(1)[-10:]
                if is_valid_indian_phone(phone):
                    return phone
        except Exception as e:
            # Check error message just in case
            err_str = str(e)
            phone_match = re.search(r'phone=(?:%2B|\+)?(\d{10,13})', err_str)
            if phone_match:
                phone = phone_match.group(1)[-10:]
                if is_valid_indian_phone(phone):
                    return phone
    
    return ""

def _parse_housing(subject: str, body: str, html_body: str, result: dict) -> dict:
    combined = body + "\n" + html_body

    # Name: from HTML: <div>Name:</div>...<div style="...bold">Priya</div>
    if html_body:
        # Pattern: Name: label followed by bold div with the actual name
        name_match = re.search(r'Name:\s*</div>\s*</td>\s*<td>\s*<div[^>]*>\s*([A-Za-z][A-Za-z\s]{1,40})\s*</div>', html_body, re.IGNORECASE)
        if name_match:
            result["name"] = name_match.group(1).strip()
    # Fallback: from header text "Priya would like to talk to you"
    if not result["name"]:
        match = re.search(r"([A-Za-z][A-Za-z\s]{1,40})\s+would\s+like\s+to\s+talk", html_body or combined, re.IGNORECASE)
        if match:
            name = match.group(1).strip()
            if name.lower() not in ('a user', 'someone', 'buyer'):
                result["name"] = name
    # Fallback: from subject
    if not result["name"]:
        match = re.search(r"^(.+?)\s+would\s+like\s+to\s+talk", subject, re.IGNORECASE)
        if match:
            result["name"] = match.group(1).strip()
    # Fallback: "Name: X" in text
    if not result["name"]:
        match = re.search(r"Name\s*[:\-]\s*([A-Za-z][A-Za-z ]{1,40})", combined, re.IGNORECASE)
        if match:
            result["name"] = match.group(1).strip()

    # Phone: Housing.com hides phone behind redirect URLs (hsng.co/HOUSNG/...)
    # Strategy: find hsng.co URLs in HTML, follow redirects to get final wa.me or tel URL
    phone_found = False
    if html_body:
        # First: try direct wa.me or tel links (in case they exist)
        wa_match = re.search(r"wa\.me/(\d{10,13})", html_body)
        if not wa_match:
            wa_match = re.search(r"api\.whatsapp\.com/send\?phone=(\d{10,13})", html_body)
        if wa_match:
            phone = wa_match.group(1)[-10:]
            if is_valid_indian_phone(phone):
                result["phone"] = phone
                phone_found = True

        if not phone_found:
            tel_match = re.search(r"tel:\+?(\d{10,13})", html_body)
            if tel_match:
                phone = tel_match.group(1)[-10:]
                if is_valid_indian_phone(phone):
                    result["phone"] = phone
                    phone_found = True

        # Follow hsng.co redirect URLs to get the phone number
        if not phone_found:
            phone = _follow_housing_redirect(html_body)
            if phone:
                result["phone"] = phone
                phone_found = True

        # Mailto link for email
        mailto_match = re.search(r"mailto:([\w.+-]+@[\w-]+\.[\w.-]+)", html_body)
        if mailto_match:
            found = mailto_match.group(1).lower()
            if "housing.com" not in found:
                result["email"] = found

    # Email fallback
    if not result["email"]:
        result["email"] = extract_email(combined, "")

    # Property: "regarding your 1 BHK Apartment" or standalone "1 BHK Apartment"
    match = re.search(r"regarding\s+your\s+(.+?):", combined, re.IGNORECASE)
    if match:
        prop_text = match.group(1).strip()
        bhk = re.search(r"(\d)\s*BHK", prop_text, re.IGNORECASE)
        if bhk:
            result["configuration"] = f"{bhk.group(1)} BHK"
            result["property_type"] = "apartment"
        else:
            result["property_type"] = extract_property_type(prop_text, subject)
    else:
        bhk = re.search(r"(\d)\s*BHK", combined, re.IGNORECASE)
        if bhk:
            result["configuration"] = f"{bhk.group(1)} BHK"
            result["property_type"] = "apartment"

    # Location: project name + area (e.g., "Shapoorji Palonji Vanaha Bavdhan")
    # Appears after BHK line in the property card
    match = re.search(r"(?:\d\s*BHK\s*Apartment\s*\n?\s*)([A-Za-z][A-Za-z\s]+(?:Bavdhan|Nagar|Road|Colony|Society|Layout|Phase|Park|Enclave|Heights|Tower|Residency|City)[A-Za-z\s]*)", combined, re.IGNORECASE)
    if match:
        result["preferred_location"] = match.group(1).strip()
    else:
        # Fallback: Capture the line before the price
        match = re.search(r"([A-Za-z0-9\s\-,&]+)\s*\n\s*[₹Rs\.]+\s*[\d,.]+\s*(?:k|K|lakh|lakhs|lac|lacs|cr|crore|crores)?", combined)
        if match:
            potential_loc = match.group(1).strip()
            if len(potential_loc) > 3 and "BHK" not in potential_loc.upper():
                result["preferred_location"] = potential_loc
        
        if not result["preferred_location"]:
            result["preferred_location"] = extract_location(combined, subject)

    # Price: "₹ 18.0k" or "Rs. 18,000" or "₹ 1.5 Cr"
    match = re.search(r"[₹Rs\.]+\s*([\d,.]+)\s*(k|K|lakh|lakhs|lac|lacs|cr|crore|crores)?", combined)
    if match:
        price_str = match.group(1).replace(",", "")
        unit = (match.group(2) or "").lower()
        try:
            price = float(price_str)
            if unit in ("k",):
                price_inr = price * 1000
                result["notes"] = f"Monthly Rent: ₹{int(price_inr)}"
            elif unit in ("cr", "crore", "crores"):
                result["budget_min"] = price * 100  # crore to lakhs
                result["budget_max"] = result["budget_min"]
            elif unit in ("lakh", "lakhs", "lac", "lacs"):
                result["budget_min"] = price
                result["budget_max"] = price
            else:
                if price < 100000:
                    result["notes"] = f"Monthly Rent: ₹{int(price)}"
                else:
                    result["budget_min"] = price / 100000
                    result["budget_max"] = result["budget_min"]
        except ValueError:
            pass

    return result


# ─── Generic Extractors (fallback) ────────────────────────────────────

def detect_source(sender: str, subject: str, body: str) -> str:
    """Detect which portal the lead came from."""
    combined = f"{sender} {subject} {body}".lower()
    if "housing.com" in combined:
        return "housing"
    elif "99acres" in combined:
        return "99acres"
    elif "magicbricks" in combined or "magic bricks" in combined:
        return "magicbricks"
    return "email"


def extract_name(body: str, subject: str) -> str:
    """Extract name from email body."""
    for line in body.split('\n'):
        line = line.strip()
        match = re.match(r"(?:name|buyer|client|enquiry by|contact person|sender'?s?\s*name)\s*[:\-–]\s*(.+)", line, re.IGNORECASE)
        if match:
            name = match.group(1).strip().rstrip('.,')
            # Remove parenthetical like "(Individual)"
            name = re.sub(r"\s*\(.*?\)\s*", "", name)
            name = ' '.join(w for w in name.split() if re.match(r'^[A-Za-z]+$', w))
            if name:
                return name[:60]

    # Try "Mr./Mrs." pattern
    match = re.search(r"(?:Mr\.|Mrs\.|Ms\.)\s+([A-Za-z]+(?:\s+[A-Za-z]+){0,3})", body)
    if match:
        return match.group(1).strip()

    # Try subject line
    match = re.search(r"(?:enquiry|inquiry|lead)\s+(?:from|by)\s+([A-Za-z]+(?:\s+[A-Za-z]+){0,2})", subject, re.IGNORECASE)
    if match:
        return match.group(1).strip()

    # Try "XYZ would like to talk" pattern (Housing.com subject)
    match = re.search(r"^(.+?)\s+would\s+like\s+to\s+talk", subject, re.IGNORECASE)
    if match:
        return match.group(1).strip()

    return "Unknown"


def is_valid_indian_phone(phone: str) -> bool:
    """Check if a 10-digit number is a valid Indian mobile number (starts with 6/7/8/9)."""
    phone = re.sub(r"[\s\-]", "", phone)
    if len(phone) > 10:
        phone = phone[-10:]
    return len(phone) == 10 and phone[0] in "6789"


def validate_phone(raw_phone: str, has_non_indian_code: bool = False) -> str:
    """Validate and clean a phone number.
    If the number has a non-Indian country code (+1, +44, etc.), skip the 6/7/8/9 rule.
    For Indian numbers (+91 or no prefix), enforce 10 digits starting with 6/7/8/9.
    """
    phone = re.sub(r"[\s\-]", "", raw_phone)
    if has_non_indian_code:
        # Non-Indian: accept as-is if 7+ digits
        digits = re.sub(r"[^\d]", "", phone)
        return digits if len(digits) >= 7 else ""
    # Indian: must be 10 digits starting with 6/7/8/9
    if len(phone) > 10:
        phone = phone[-10:]
    return phone if is_valid_indian_phone(phone) else ""


def extract_phone(body: str) -> str:
    """Extract phone number from email body or HTML.
    Supports Indian (+91) and international numbers.
    """
    # First: try international numbers with non-Indian country codes
    intl_match = re.search(r'\+((?!91\b)\d{1,3})[\s\-]?(\d[\d\s\-]{6,14})', body)
    if intl_match:
        code = intl_match.group(1)
        number = re.sub(r'[\s\-]', '', intl_match.group(2))
        if len(number) >= 7:
            return f"+{code}{number}"

    # Then: Indian phone patterns
    patterns = [
        r"(?:phone|mobile|contact|cell|tel|mob)\s*[:\-\u2013]\s*\+?91[\s\-]?(\d{10})",
        r"(?:phone|mobile|contact|cell|tel|mob)\s*[:\-\u2013]\s*\+?(\d[\d\s\-]{8,14})",
        r"wa\.me/(\d{10,13})",
        r"api\.whatsapp\.com/send\?phone=(\d{10,13})",
        r'tel:\+?91[\s\-]?(\d{10})',
        r"\+91[\s\-]?(\d{10})",
        r"(?<!\d)(\d{10})(?!\d)",
        r"(?<!\d)(\d{5}[\s\-]\d{5})(?!\d)",
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, body, re.IGNORECASE):
            phone = re.sub(r"[\s\-]", "", match.group(1))
            if len(phone) >= 10:
                phone = phone[-10:]
                if is_valid_indian_phone(phone):
                    return phone
    return ""


def extract_email(body: str, sender: str) -> str:
    """Extract email address from body or sender."""
    match = re.search(r"[\w.+-]+@[\w-]+\.[\w.-]+", body)
    if match:
        found = match.group(0).lower()
        # Skip portal emails
        if not any(portal in found for portal in ["housing.com", "99acres", "magicbricks", "noreply", "no-reply"]):
            return found

    # Fallback to sender
    if sender:
        match = re.search(r"[\w.+-]+@[\w-]+\.[\w.-]+", sender)
        if match:
            return match.group(0).lower()
    return ""


def extract_budget(body: str) -> tuple:
    """Extract budget range from email body. Returns (min, max) in lakhs."""
    patterns = [
        r"(\d+(?:\.\d+)?)\s*(?:to|-|–)\s*(\d+(?:\.\d+)?)\s*(?:lac|lakh|lacs|lakhs)",
        r"(\d+(?:\.\d+)?)\s*(?:lac|lakh|lacs|lakhs)\s*(?:to|-|–)\s*(\d+(?:\.\d+)?)\s*(?:lac|lakh|lacs|lakhs|cr|crore|crores)",
        r"(\d+(?:\.\d+)?)\s*(?:cr|crore|crores)\s*(?:to|-|–)\s*(\d+(?:\.\d+)?)\s*(?:cr|crore|crores)",
        r"budget\s*[:\-–]\s*(?:Rs\.?\s*)?(\d+(?:\.\d+)?)\s*(?:to|-|–)?\s*(\d+(?:\.\d+)?)?\s*(?:lac|lakh|lacs|lakhs|cr|crore|crores)",
    ]
    for pattern in patterns:
        match = re.search(pattern, body, re.IGNORECASE)
        if match:
            groups = match.groups()
            vals = []
            for g in groups:
                if g:
                    try:
                        vals.append(float(g))
                    except ValueError:
                        pass
            if len(vals) >= 2:
                return (vals[0], vals[1])
            elif len(vals) == 1:
                return (vals[0], vals[0])
    return (None, None)


def extract_location(body: str, subject: str) -> str:
    """Extract location from email body or subject."""
    for line in body.split('\n'):
        line = line.strip()
        match = re.match(r"(?:location|area|locality|sector)\s*[:\-–]\s*(.+)", line, re.IGNORECASE)
        if match:
            loc = match.group(1).strip().rstrip('.,')
            if 3 < len(loc) < 100:
                return loc

    combined = f"{subject}\n{body}"
    patterns = [
        r"(?:property in|flat in|house in|apartment in|villa in)\s+([A-Za-z\s,]+?)(?:\.|,\s*(?:budget|phone|name)|\n|$)",
        r"(?:in)\s+([A-Z][a-z]+(?:\s*,\s*[A-Z][a-z]+)?)\s*(?:for|under|\.|$)",
    ]
    for pattern in patterns:
        match = re.search(pattern, combined, re.IGNORECASE)
        if match:
            loc = match.group(1).strip()
            if 3 < len(loc) < 100:
                return loc
    return ""


def extract_property_type(body: str, subject: str) -> str:
    """Extract property type from email content."""
    combined = f"{subject} {body}".lower()

    types = {
        "apartment": ["apartment", "flat", "multistorey"],
        "villa": ["villa", "bungalow", "independent house", "duplex", "row house"],
        "plot": ["plot", "land", "site"],
        "office": ["office", "commercial", "shop", "showroom"],
    }
    for ptype, keywords in types.items():
        if any(kw in combined for kw in keywords):
            return ptype
    return ""


# ─── Gmail IMAP Fetcher ──────────────────────────────────────────────

def fetch_gmail_leads(
    gmail_user: str,
    gmail_app_password: str,
    max_emails: Optional[int] = None,
    folder: str = "INBOX",
) -> list:
    """
    Fetch leads from Gmail using IMAP.
    Requires an App Password (not regular password).
    Searches for UNSEEN emails from real estate portals.
    Returns both plain text and HTML bodies for full extraction.
    """
    try:
        mail = imaplib.IMAP4_SSL("imap.gmail.com")
        mail.login(gmail_user, gmail_app_password)
        mail.select(folder)

        # Only fetch actual LEAD emails (not promotional/listing emails)
        # Each query targets emails with real contact data (name, phone)
        search_queries = [
            # Housing.com: "Lead - XYZ would like to talk to you"
            '(SINCE "03-May-2026" FROM "housing.com" SUBJECT "Lead")',
            # MagicBricks: "Buyer has contacted you on Magicbricks"
            '(SINCE "03-May-2026" FROM "magicbricks.com" SUBJECT "contacted")',
            # 99acres: "Advertisement Response" or "Property Advertisement Query"
            '(SINCE "03-May-2026" FROM "99acres.com" SUBJECT "Response")',
            '(SINCE "03-May-2026" FROM "99acres.com" SUBJECT "Query")',
        ]

        all_email_ids = set()
        for query in search_queries:
            status, data = mail.search(None, query)
            if status != "OK":
                continue
            for eid in data[0].split():
                all_email_ids.add(int(eid))
        
        # Sort chronologically (oldest to newest), then reverse for newest-first
        sorted_ids = sorted(list(all_email_ids), reverse=True)
        print(f"Total lead IDs found: {len(sorted_ids)}")
        
        if max_emails is not None:
            sorted_ids = sorted_ids[:max_emails]
            print(f"Limiting to latest {max_emails} emails")

        for eid_int in sorted_ids:
            print(f"Processing email ID: {eid_int}")
            eid = str(eid_int).encode()
            status, msg_data = mail.fetch(eid, "(RFC822)")
            if status != "OK":
                continue

            raw = msg_data[0][1]
            msg = email.message_from_bytes(raw)

            subject = ""
            raw_subject = msg.get("Subject", "")
            decoded = decode_header(raw_subject)
            for part, enc in decoded:
                if isinstance(part, bytes):
                    subject += part.decode(enc or "utf-8", errors="replace")
                else:
                    subject += part

            sender = msg.get("From", "")

            # Extract email date (when email was received)
            email_date = msg.get("Date", "")
            received_at = None
            if email_date:
                try:
                    from email.utils import parsedate_to_datetime
                    received_at = parsedate_to_datetime(email_date)
                except Exception:
                    pass

            body, html_body = _get_email_bodies(msg)
            lead = parse_lead_from_email(subject, body, sender, html_body)
            lead["raw_subject"] = subject
            lead["received_at"] = received_at  # actual email timestamp
            yield lead

        mail.logout()
    except Exception as e:
        print(f"Gmail fetch error: {e}")


def _get_email_bodies(msg) -> tuple:
    """Extract both plain text and HTML body from email message.
    Returns (text_body, html_body).
    """
    text_body = ""
    html_body = ""
    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            try:
                payload = part.get_payload(decode=True)
                if payload is None:
                    continue
                decoded = payload.decode("utf-8", errors="replace")
                if content_type == "text/plain" and not text_body:
                    text_body = decoded
                elif content_type == "text/html" and not html_body:
                    html_body = decoded
            except Exception:
                pass
    else:
        try:
            payload = msg.get_payload(decode=True).decode("utf-8", errors="replace")
            if msg.get_content_type() == "text/html":
                html_body = payload
            else:
                text_body = payload
        except Exception:
            pass

    # If we only have HTML, also extract plain text from it
    if html_body and not text_body:
        text_body = _html_to_text(html_body)

    return text_body, html_body


def _html_to_text(html: str) -> str:
    """Simple HTML to text converter."""
    # Remove script/style blocks
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", html, flags=re.DOTALL | re.IGNORECASE)
    # Replace common tags with newlines
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</(p|div|tr|li|h[1-6])>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<td[^>]*>", " ", text, flags=re.IGNORECASE)
    # Remove remaining tags
    text = re.sub(r"<[^>]+>", "", text)
    # Decode entities
    text = text.replace("&nbsp;", " ").replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">").replace("&#8377;", "₹").replace("&rsquo;", "'")
    # Collapse whitespace
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()
