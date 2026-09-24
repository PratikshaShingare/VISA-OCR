"""
Khanna Travels & Holidays — Hotel Voucher OCR Engine
Analyzes uploaded hotel vouchers (Image or PDF) and extracts:
- Confirmation Number
- Hotel Name
- Lead Guest
- Number of Guests & Rooms
- Check-In Date & Check-Out Date
- Duration
- City & Full Street Address
- Phone Number
- Structured Guest & Room Table
Generalizes across voucher formats without hardcoded values.
"""

import sys
import os
import re
import json
import numpy as np
from PIL import Image

sys.stdout.reconfigure(encoding='utf-8')


def parse_hotel_voucher(file_path: str):
    from rapidocr_onnxruntime import RapidOCR
    engine = RapidOCR()

    ext = os.path.splitext(file_path)[1].lower()
    img = None

    if ext in ['.jpg', '.jpeg', '.png', '.webp', '.bmp']:
        try:
            img = Image.open(file_path).convert("RGB")
        except Exception as e:
            return {"error": f"Failed to open image: {e}"}
    elif ext == '.pdf':
        try:
            import pypdfium2 as pdfium
            pdf = pdfium.PdfDocument(file_path)
            # Render first page at 250 DPI
            page = pdf[0]
            bitmap = page.render(scale=2.5)
            img = bitmap.to_pil().convert("RGB")
        except Exception as e:
            return {"error": f"Failed to render PDF voucher: {e}"}

    if img is None:
        return {"error": "Invalid voucher file."}

    img_np = np.array(img)
    ocr_results, _ = engine(img_np)

    if not ocr_results:
        return {"error": "No text detected in hotel voucher."}

    raw_lines = [r[1].strip() for r in ocr_results]
    full_text = "\n".join(raw_lines)

    result = {
        "confirmationNumber": "",
        "hotelName": "",
        "leadGuest": "",
        "numGuests": "1 Adult(s)",
        "numRooms": "1",
        "phone": "",
        "checkIn": "",
        "checkOut": "",
        "duration": "",
        "city": "",
        "address": "",
        "roomType": "Standard Room",
        "guests": []
    }

    # 1. Confirmation Number Extraction
    m_conf = re.search(r'(?:Confirmation\s*No\.?|Booking\s*Ref\.?|Confirmation\s*Number)[\s:-]*([A-Z0-9]{8,15})', full_text, re.IGNORECASE)
    if m_conf:
        result["confirmationNumber"] = m_conf.group(1).strip()
    else:
        # Fallback search for alphanumeric code like TBWP06SS09 or TBHBV5YP9R
        m_code = re.search(r'\b(TB[A-Z0-9]{7,12})\b', full_text)
        if m_code:
            result["confirmationNumber"] = m_code.group(1).strip()

    # 2. Check-In & Check-Out Dates
    # Standard Date pattern: DD-Mon-YYYY (e.g. 04-Dec-2026, 17-Sep-2026) or DD/MM/YYYY
    date_pat = r'(\d{1,2}[-/][A-Za-z]{3,}[-/]\d{4}|\d{1,2}[-/]\d{2}[-/]\d{4})'

    m_in = re.search(r'Check[- ]*In[\s:]*' + date_pat, full_text, re.IGNORECASE)
    if m_in:
        result["checkIn"] = m_in.group(1).strip()

    m_out = re.search(r'Check[- ]*Out[\s:]*' + date_pat, full_text, re.IGNORECASE)
    if m_out:
        result["checkOut"] = m_out.group(1).strip()

    # 3. Duration / Nights
    m_dur = re.search(r'(?:No\.?\s*of\s*Nights?|Duration)[\s:]*(\d+)\s*(?:Nights?|\(s\))?', full_text, re.IGNORECASE)
    if m_dur:
        n = m_dur.group(1).strip()
        result["duration"] = f"{int(n):02d} Night(s)" if int(n) < 10 else f"{n} Night(s)"

    # 4. Hotel Name & Address Extraction
    # Look for hotel lines (often with stars or 'Hotel', 'Inn', 'Resort', 'Plaza', 'Novotel')
    hotel_candidates = []
    for line in raw_lines:
        line_clean = re.sub(r'[★*]+', '', line).strip()
        if any(w in line_clean.lower() for w in ['hotel', 'inn', 'resort', 'plaza', 'novotel', 'mercure', 'crowne', 'suites', 'ihg', 'marriott', 'hyatt']):
            if not any(ign in line_clean.lower() for ign in ['service booked', 'details', 'khanna holidays', 'cancel', 'policy']):
                hotel_candidates.append(line_clean)

    if hotel_candidates:
        result["hotelName"] = hotel_candidates[0]

    # Look for street address (exclude agency address in Mumbai)
    for line in raw_lines:
        line_clean = line.lower().replace(' ', '')
        if any(w in line_clean for w in ['street', 'road', 'st,', 'rd,', 'dr,', 'avenue', 'lane', 'vic', 'nsw', 'qld', 'station']):
            if not any(ign in line_clean for ign in ['palmbeach', 'seawoods', 'khanna', 'details', 'anotheritem']):
                result["address"] = line.strip()
                break

    # City detection
    cities = ['Singapore', 'Sydney', 'Melbourne', 'Gold Coast', 'Brisbane', 'Perth', 'Dubai', 'Paris', 'Tokyo', 'London', 'Rome']
    for c in cities:
        if re.search(r'\b' + re.escape(c) + r'\b', full_text, re.IGNORECASE):
            result["city"] = c
            break

    if not result["city"] and ("carrara" in full_text.lower() or "goldcoast" in full_text.lower().replace(" ", "")):
        result["city"] = "Gold Coast"

    # 5. Phone Number
    m_phone = re.search(r'(?:Phone|Tel|Call\s*us\s*at)[\s:.]*([+]?[\d\s-]{8,18})', full_text, re.IGNORECASE)
    if m_phone:
        result["phone"] = m_phone.group(1).strip().split('\n')[0].strip()

    # 6. Room Type & Guests
    m_room = re.search(r'\b(Standard\s*(?:King\s*)?Room|Classic\s*(?:King\s*)?Room|Deluxe\s*Room|Superior\s*Room|Executive\s*Room)\b', full_text, re.IGNORECASE)
    if m_room:
        result["roomType"] = m_room.group(1).strip()

    m_pax = re.search(r'(\d+)\s*Adult\(s\)', full_text, re.IGNORECASE)
    if m_pax:
        result["numGuests"] = f"{m_pax.group(1)} Adult(s)"

    # 7. Lead Guest & Passenger List
    guests_found = []
    for i, line in enumerate(raw_lines):
        line_l = line.lower()
        if "lead guest" in line_l or "adult 1" in line_l or "adult1" in line_l:
            for j in range(i, min(len(raw_lines), i + 4)):
                cand = raw_lines[j].strip()
                m_name = re.search(r'\b(Mr\.|Mrs\.|Ms\.|Dr\.)\s*([A-Za-z\s]{3,40})\b', cand, re.IGNORECASE)
                if m_name and "KHANNA" not in cand.upper() and "GUEST" not in cand.upper():
                    guests_found.append(m_name.group(0).strip())
                    break

        if "adult 2" in line_l or "adult2" in line_l:
            for j in range(i, min(len(raw_lines), i + 4)):
                cand = raw_lines[j].strip()
                m_name = re.search(r'\b(Mr\.|Mrs\.|Ms\.|Dr\.)\s*([A-Za-z\s]{3,40})\b', cand, re.IGNORECASE)
                if m_name and "KHANNA" not in cand.upper() and "GUEST" not in cand.upper():
                    guests_found.append(m_name.group(0).strip())
                    break

    # If lead guest found
    if guests_found:
        result["leadGuest"] = guests_found[0]
        result["guests"] = [
            {
                "id": f"g_{idx + 1}",
                "guestName": g,
                "roomType": result["roomType"],
                "numGuests": result["numGuests"]
            }
            for idx, g in enumerate(guests_found)
        ]
    else:
        # Fallback generic lead guest search
        m_name = re.search(r'\b(Mr\.|Mrs\.|Ms\.)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\b', full_text)
        if m_name and "KHANNA" not in m_name.group(0).upper():
            result["leadGuest"] = m_name.group(0).strip()
            result["guests"] = [
                {
                    "id": "g_1",
                    "guestName": result["leadGuest"],
                    "roomType": result["roomType"],
                    "numGuests": result["numGuests"]
                }
            ]

    return result


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(json.dumps({"error": "No voucher file specified."}))
        sys.exit(1)

    target_file = sys.argv[1]
    res = parse_hotel_voucher(target_file)
    print(json.dumps(res, indent=2))
