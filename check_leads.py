"""Follow the inner hsng.co redirect URLs directly."""
import io, sys, os, re
from urllib.request import urlopen, Request
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

# The awstrack URLs contain embedded hsng.co URLs. Extract them.
awstrack_urls = [
    "https://8czw49zf.r.ap-southeast-1.awstrack.me/L0/https:%2F%2Fhsng.co%2FHOUSNG%2FqGT79vo/1/010e019debe73e8c-6177d085-4ad9-4c7f-af47-846f4412ab05-000000",
    "https://8czw49zf.r.ap-southeast-1.awstrack.me/L0/https:%2F%2Fhsng.co%2FHOUSNG%2F4QbgcSA/1/010e019debe73e8c-6177d085-4ad9-4c7f-af47-846f4412ab05-000000",
    "https://8czw49zf.r.ap-southeast-1.awstrack.me/L0/https:%2F%2Fhsng.co%2FHOUSNG%2F5OPYrQG/1/010e019debe73e8c-6177d085-4ad9-4c7f-af47-846f4412ab05-000000",
]

# Extract the actual hsng.co URLs from the tracking wrappers
for aw_url in awstrack_urls:
    # The URL pattern: /L0/https:%2F%2Fhsng.co%2FHOUSNG%2Fxxx/1/...
    match = re.search(r'/L0/(https?[^/]+)/1/', aw_url)
    if match:
        from urllib.parse import unquote
        inner_url = unquote(match.group(1))
        print(f"\nInner URL: {inner_url}")
        
        try:
            req = Request(inner_url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'})
            resp = urlopen(req, timeout=15)
            final_url = resp.geturl()
            body = resp.read(5000).decode('utf-8', errors='replace')
            print(f"  Final URL: {final_url}")
            
            # Check for wa.me or tel in final URL
            wa = re.search(r'wa\.me/(\d+)', final_url)
            tel = re.search(r'tel:\+?(\d+)', final_url)
            if wa:
                print(f"  >>> PHONE (wa.me): +{wa.group(1)} -> {wa.group(1)[-10:]}")
            elif tel:
                print(f"  >>> PHONE (tel): {tel.group(1)} -> {tel.group(1)[-10:]}")
            else:
                # Check body
                wa_body = re.search(r'wa\.me/(\d+)', body)
                tel_body = re.search(r'tel:\+?(\d+)', body) 
                if wa_body:
                    print(f"  >>> PHONE in body (wa.me): +{wa_body.group(1)} -> {wa_body.group(1)[-10:]}")
                elif tel_body:
                    print(f"  >>> PHONE in body (tel): {tel_body.group(1)}")
                else:
                    print(f"  No phone found. Body: {body[:500]}")
        except Exception as e:
            print(f"  Error: {e}")
            # Try to extract from Location header for 3xx redirects
            from urllib.request import build_opener, HTTPRedirectHandler
            class NoRedirect(HTTPRedirectHandler):
                def redirect_request(self, req, fp, code, msg, headers, newurl):
                    print(f"    Redirect {code} -> {newurl[:120]}")
                    wa2 = re.search(r'wa\.me/(\d+)', newurl)
                    tel2 = re.search(r'tel:\+?(\d+)', newurl)
                    if wa2:
                        print(f"    >>> PHONE: +{wa2.group(1)}")
                    elif tel2:
                        print(f"    >>> PHONE: {tel2.group(1)}")
                    return super().redirect_request(req, fp, code, msg, headers, newurl)
            
            opener = build_opener(NoRedirect)
            try:
                req2 = Request(inner_url, headers={'User-Agent': 'Mozilla/5.0'})
                resp2 = opener.open(req2, timeout=15)
                print(f"    Final: {resp2.geturl()}")
            except Exception as e2:
                print(f"    Redirect follow error: {e2}")
