"""Test the parser with real email formats from MagicBricks, 99acres, Housing.com"""
from parser import parse_lead_from_email

# Test MagicBricks email
mb = parse_lead_from_email(
    subject='Response on your Property Listing',
    body='Dear Ravindra Bhujbal,\nA user is interested in your Property, ID 80509613: 1 BHK, Multistorey Apartment in Siddharth Nagar Bavdhan, Pune.\n\nDetails of Contact Made:\nSender\'s Name: ajit (Individual)\nMobile: 9604092514\nEmail: ajito18@hotmail.com\nMessage: I am interested in your property. Please get in touch with me\n\nClick here to view all responses',
    sender='alerts@magicbricks.com'
)
print('=== MagicBricks ===')
for k, v in mb.items():
    if k != 'notes':
        print(f'  {k}: {v}')
print(f'  notes: {mb["notes"][:100]}...')

# Test 99acres email
na = parse_lead_from_email(
    subject='Property Advertisement Query',
    body='Dear RAVINDRA NARAYAN BHUJBAL\nYou have received a query on Rs15,000 , Flat/Apartment in Yahavi Vanaha Bavdhan Patil Nagar (K88204044) on 99acres.com\n\nDetails of the Query\nDaksh Sharma\n+91-9958323859 (Verified)',
    sender='no-reply@99acres.com'
)
print('\n=== 99acres ===')
for k, v in na.items():
    if k != 'notes':
        print(f'  {k}: {v}')
print(f'  notes: {na["notes"][:100]}...')

# Test Housing.com email (with HTML for phone extraction)
hc = parse_lead_from_email(
    subject='Upasana Satpathy would like to talk to you',
    body='Hi Armstrong,\nWe have received a contact request from our user:\nName: Upasana Satpathy\nwho would like to talk to you regarding your 1 BHK Apartment:\n1 BHK Apartment\nShapoorji Palonji Vanaha Bavdhan\n1 BHK Apartment\nRs 18.0k',
    sender='no-reply@housing.com',
    html_body='<a href="https://wa.me/919876543210">Chat On WhatsApp</a><a href="tel:+919876543210">Call Now</a><a href="mailto:upasana@gmail.com">Send Email</a>'
)
print('\n=== Housing.com ===')
for k, v in hc.items():
    if k != 'notes':
        print(f'  {k}: {v}')
print(f'  notes: {hc["notes"][:100]}...')
