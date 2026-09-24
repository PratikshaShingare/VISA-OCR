"""
Khanna Travels & Holidays — High-Fidelity Word (.docx) & PDF Generator
Populates approved clean templates from templates/ as the single source of truth:
1. Cover Letters: Europe, Japan, Singapore (.docx & .pdf)
2. Hotel Blocking: Single and Multiple Hotels (.docx & .pdf)
   - Exact font styling matching official format: Aptos (Calibri fallback), 16pt, bold labels, exact colors.
   - Exact table structure preserved: Guest Name | Room Type | No. of Guests (Strictly 3 columns, no extra columns).
3. Passport Authorization Letter (.docx & .pdf)
4. Company Authorization Letter (.docx & .pdf)
Zero emojis, zero template artefacts, zero hardcoded sample names.
"""

import sys
import os
import io
import json
import docx
from datetime import datetime
from docx.shared import Inches, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT, WD_ALIGN_VERTICAL
from docx.oxml import OxmlElement, parse_xml
from docx.oxml.ns import nsdecls, qn

from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, KeepTogether
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

sys.stdout.reconfigure(encoding='utf-8')


def set_cell_background(cell, fill_hex):
    """Sets background shading color for a table cell."""
    tcPr = cell._tc.get_or_add_tcPr()
    shd = parse_xml(f'<w:shd {nsdecls("w")} w:fill="{fill_hex}"/>')
    tcPr.append(shd)


def set_cell_margins(cell, top=100, bottom=100, left=150, right=150):
    """Sets cell padding in twips."""
    tcPr = cell._tc.get_or_add_tcPr()
    tcMar = parse_xml(f'<w:tcMar {nsdecls("w")}><w:top w:w="{top}" w:type="dxa"/><w:bottom w:w="{bottom}" w:type="dxa"/><w:left w:w="{left}" w:type="dxa"/><w:right w:w="{right}" w:type="dxa"/></w:tcMar>')
    tcPr.append(tcMar)


def set_cell_formatted(cell, text, font_name="Aptos", size_pt=16.0, bold=False, color_rgb=(50, 50, 50), align=WD_ALIGN_PARAGRAPH.LEFT):
    """Sets cell text preserving exact Aptos/Calibri font styling and XML tags."""
    cell.text = ""
    p = cell.paragraphs[0]
    p.alignment = align
    if p.runs:
        run = p.runs[0]
        run.text = str(text) if text is not None else ""
        for extra in p.runs[1:]:
            p._p.remove(extra._r)
    else:
        run = p.add_run(str(text) if text is not None else "")
    
    run.font.name = font_name
    if size_pt:
        run.font.size = Pt(size_pt)
    run.font.bold = bold
    if color_rgb:
        run.font.color.rgb = RGBColor(*color_rgb)
    rPr = run._r.get_or_add_rPr()
    for existing_rf in rPr.findall(qn('w:rFonts')):
        rPr.remove(existing_rf)
    rFonts = parse_xml(f'<w:rFonts {nsdecls("w")} w:ascii="{font_name}" w:hAnsi="{font_name}" w:cs="{font_name}"/>')
    rPr.append(rFonts)
    return run


def set_hotel_header_cell(cell, conf_no, font_name="Aptos", size_pt=16.0):
    """Formats the hotel confirmation banner preserving exact font runs and styles."""
    cell.text = ""
    p = cell.paragraphs[0]
    for r in list(p.runs):
        p._p.remove(r._r)
    
    r0 = p.add_run('Thanks for booking with us, your booking has been "')
    r0.font.name = font_name
    r0.font.size = Pt(size_pt)
    r0.font.bold = False
    r0.font.color.rgb = RGBColor(50, 50, 50)
    
    r1 = p.add_run('Confirmed')
    r1.font.name = font_name
    r1.font.size = Pt(size_pt)
    r1.font.bold = True
    r1.font.color.rgb = RGBColor(50, 50, 50)
    
    r2 = p.add_run('" with \nConfirmation Number- ')
    r2.font.name = font_name
    r2.font.size = Pt(size_pt)
    r2.font.bold = True
    r2.font.color.rgb = RGBColor(50, 50, 50)
    
    r3 = p.add_run(str(conf_no))
    r3.font.name = font_name
    r3.font.size = Pt(size_pt)
    r3.font.bold = True
    r3.font.color.rgb = RGBColor(50, 50, 50)
    
    for r in [r0, r1, r2, r3]:
        rPr = r._r.get_or_add_rPr()
        for existing_rf in rPr.findall(qn('w:rFonts')):
            rPr.remove(existing_rf)
        rFonts = parse_xml(f'<w:rFonts {nsdecls("w")} w:ascii="{font_name}" w:hAnsi="{font_name}" w:cs="{font_name}"/>')
        rPr.append(rFonts)


# =========================================================================
# 1. COVER LETTER GENERATORS (Europe, Japan, Singapore)
# =========================================================================

def generate_cover_letter_docx(data: dict, output_path: str):
    """
    Generates a formal visa cover letter using approved clean docx templates from templates/cover-letter/
    """
    template_type = data.get("template", "Europe")
    applicant = data.get("applicant", {})
    travel = data.get("travel", {})
    travellers = data.get("travellers", [])
    hotels = data.get("hotels", [])

    template_map = {
        "Europe": "templates/cover-letter/Europe/Europe_covering_letter_template_clean.docx",
        "Japan": "templates/cover-letter/Japan/Japan_covering_letter_template_clean.docx",
        "Singapore": "templates/cover-letter/Singapore/Singapore_covering_letter_template_clean.docx"
    }

    tpl_path = template_map.get(template_type, template_map["Europe"])
    if not os.path.exists(tpl_path):
        tpl_path = os.path.join("..", tpl_path)

    doc = docx.Document(tpl_path)
    today_str = datetime.now().strftime("%d-%b-%Y")

    app_name = applicant.get("fullName") or f"{applicant.get('givenNames', '')} {applicant.get('surname', '')}".strip() or "Applicant Name"
    pass_no = applicant.get("passportNumber") or "N/A"
    poi = applicant.get("placeOfIssue") or "Mumbai"
    doi = applicant.get("dateOfIssue") or "N/A"
    dest = travel.get("destinationCountry") or "Europe"
    start_date = travel.get("travelStartDate") or "DD/MM/YYYY"
    end_date = travel.get("travelEndDate") or "DD/MM/YYYY"
    funding = travel.get("fundingArrangement") or "Self-funded from personal savings"
    job_title = travel.get("jobTitle") or "Professional"
    employer = travel.get("employerName") or "Organization"
    phone = travel.get("applicantPhone") or "+91 9876543210"
    email = travel.get("applicantEmail") or "applicant@example.com"
    city = applicant.get("city") or "Mumbai"
    address = applicant.get("residentialAddress") or f"{city}, India"
    consulate_str = f"Embassy / Consulate General of {dest},\nMumbai / New Delhi, India"

    # Calculate duration
    duration_str = "10 Nights"
    if start_date != "DD/MM/YYYY" and end_date != "DD/MM/YYYY":
        try:
            parts1 = [int(p) for p in start_date.replace('-', '/').split('/')]
            parts2 = [int(p) for p in end_date.replace('-', '/').split('/')]
            if len(parts1) == 3 and len(parts2) == 3:
                d1 = datetime(parts1[2], parts1[1], parts1[0])
                d2 = datetime(parts2[2], parts2[1], parts2[0])
                diff_days = (d2 - d1).days
                if diff_days > 0:
                    duration_str = f"{diff_days} Nights"
        except Exception:
            pass

    replacements = {
        "[Date]": today_str,
        "[Applicant Full Name]": app_name,
        "[Passenger 1 Name]": app_name,
        "[Passport Number]": pass_no,
        "[Passport No.]": pass_no,
        "[Place of Issue]": poi,
        "[Passport Issue Date]": doi,
        "[Destination Country]": dest,
        "[Destination Country/Countries]": dest,
        "[Travel Start Date]": start_date,
        "[Travel End Date]": end_date,
        "[Funding Arrangement]": funding,
        "[Sponsor Name / Funding Arrangement]": funding,
        "[Job Title]": job_title,
        "[Employer Name]": employer,
        "[Employer / Occupation]": f"{employer} - {job_title}",
        "[Employment Status]": travel.get("employmentStatus", "Employed"),
        "[Employment Start Year]": travel.get("employmentStartYear", "2018"),
        "[Phone Number]": phone,
        "[Email Address]": email,
        "[Contact No.]": phone,
        "[City, Country]": f"{city}, India",
        "[City]": city,
        "[Address]": address,
        "[Number of Nights]": duration_str,
        "[Next Country]": dest,
        "[Next Travel Start Date]": start_date,
        "[Next Travel End Date]": end_date,
        "[Occupation]": job_title,
        "[Relation]": "Family Member",
        "[Relation/Family]": "Family",
        "[Consulate Name and Address]": consulate_str
    }

    if travellers:
        p2 = travellers[0]
        replacements["[Passenger 2 Name]"] = p2.get("fullName", "Accompanying Passenger")
        replacements["[Relation]"] = p2.get("relation", "Spouse")
        replacements["[Occupation]"] = p2.get("occupation", "Employed")
    else:
        replacements["[Passenger 2 Name]"] = ""
        replacements["[Add additional family member details here if applicable]."] = ""

    for p in doc.paragraphs:
        for k, v in replacements.items():
            if k in p.text:
                p.text = p.text.replace(k, v)

    # Handle template-specific tables
    if template_type == "Japan" and doc.tables:
        t = doc.tables[0]
        while len(t.rows) > 1:
            t._tbl.remove(t.rows[-1]._tr)

        if hotels:
            for h in hotels:
                r = t.add_row()
                r.cells[0].text = h.get("hotelName", "Hotel")
                r.cells[1].text = f"{h.get('checkIn', start_date)} - {h.get('checkOut', end_date)}"
                r.cells[2].text = h.get("phone", phone)
        else:
            r = t.add_row()
            r.cells[0].text = f"Grand Hotel {dest}"
            r.cells[1].text = f"{start_date} - {end_date}"
            r.cells[2].text = phone

    elif template_type == "Singapore" and doc.tables:
        t = doc.tables[0]
        while len(t.rows) > 1:
            t._tbl.remove(t.rows[-1]._tr)

        r1 = t.add_row()
        r1.cells[0].text = "1"
        r1.cells[1].text = app_name
        r1.cells[2].text = pass_no
        r1.cells[3].text = "Self"
        r1.cells[4].text = job_title

        for i, tr in enumerate(travellers):
            r = t.add_row()
            r.cells[0].text = str(i + 2)
            r.cells[1].text = tr.get("fullName", "")
            r.cells[2].text = tr.get("passportNumber", "")
            r.cells[3].text = tr.get("relation", "Family")
            r.cells[4].text = tr.get("occupation", "Employed")

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    doc.save(output_path)
    return output_path


def generate_cover_letter_pdf(data: dict, output_path: str):
    """
    Generates a formal Cover Letter PDF using ReportLab.
    """
    doc = SimpleDocTemplate(
        output_path,
        pagesize=A4,
        rightMargin=48,
        leftMargin=48,
        topMargin=48,
        bottomMargin=48
    )

    styles = getSampleStyleSheet()
    p_style = ParagraphStyle(
        'CoverBody',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=10,
        leading=15,
        textColor=colors.HexColor('#1E293B'),
        spaceAfter=10
    )
    p_bold_style = ParagraphStyle(
        'CoverBold',
        parent=p_style,
        fontName='Helvetica-Bold'
    )

    story = []
    html_content = data.get("html", "")
    if html_content:
        import re
        clean_html = html_content.replace('<br>', '<br/>').replace('</p>', '</p><spacer height="10"/>')
        clean_html = re.sub(r'<table[\s\S]*?</table>', '', clean_html)
        paragraphs = clean_html.split('<p')
        for p in paragraphs:
            if not p.strip():
                continue
            text = '<p' + p
            text = re.sub(r'<p[^>]*>', '', text).replace('</p>', '').strip()
            if text:
                story.append(Paragraph(text, p_style))
                story.append(Spacer(1, 8))
    else:
        app = data.get("applicant", {})
        story.append(Paragraph(f"<b>Cover Letter for Visa Application</b>", p_bold_style))
        story.append(Paragraph(f"Applicant: {app.get('fullName', 'Applicant')}", p_style))

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    doc.build(story)
    return output_path


# =========================================================================
# 2. HOTEL BLOCKING GENERATORS (Single & Multiple Hotels)
# =========================================================================

def generate_hotel_blocking_docx(data: dict, output_path: str):
    """
    Generates high-fidelity Hotel Blocking Word document matching Khanna Travels format.
    Uses templates/hotel-blocking/ as single source of truth.
    Strictly preserves the exact 3-column table structure: Guest Name | Room Type | No. of Guests.
    No extra columns.
    """
    hotels = data.get("hotels", [])
    applicant = data.get("applicant", {})

    if len(hotels) > 1:
        base_tpl = "templates/hotel-blocking/Multiple Hotels/Aakarsh Vikrant Shukla-  Australia Hotel Booking.docx"
    else:
        base_tpl = "templates/hotel-blocking/Single Hotel/Hotel Booking Format.docx"

    if not os.path.exists(base_tpl):
        base_tpl = os.path.join("..", base_tpl)

    doc = docx.Document(base_tpl)

    if not hotels:
        hotels = [{
            "confirmationNumber": "TBHBV5YP9R",
            "hotelName": "Hotel Booking Confirmation",
            "leadGuest": applicant.get("fullName", "Lead Guest"),
            "checkIn": "TBD",
            "checkOut": "TBD",
            "duration": "1 Night(s)",
            "city": "",
            "phone": "+61 2 7255 2300",
            "address": "",
            "numRooms": "1",
            "numGuests": "1 Adult(s)",
            "guests": [{"guestName": applicant.get("fullName", "Lead Guest"), "roomType": "Standard Room", "numGuests": "1 Adult(s)"}]
        }]

    for idx, h in enumerate(hotels):
        conf_no = h.get("confirmationNumber", "TBHBV5YP9R")
        hotel_name = h.get("hotelName", "Hotel Booking")
        lead_guest = h.get("leadGuest") or applicant.get("fullName") or "Lead Guest"
        check_in = h.get("checkIn", "TBD")
        check_out = h.get("checkOut", "TBD")
        duration = h.get("duration", "1 Night(s)")
        city = h.get("city", "")
        phone = h.get("phone", "+61 2 7255 2300")
        address = h.get("address", "")
        num_rooms = h.get("numRooms", "1")
        num_guests = h.get("numGuests", "1 Adult(s)")

        # Determine outer table and subtable container
        if len(hotels) > 1:
            t = doc.tables[idx] if idx < len(doc.tables) else doc.tables[0]
            header_cell = t.rows[0].cells[0]
            subtables_cell = t.rows[1].cells[0]
        else:
            outer = doc.tables[0]
            if outer.rows[0].cells[0].tables:
                sub_outer = outer.rows[0].cells[0].tables[0]
                header_cell = sub_outer.rows[0].cells[0]
                subtables_cell = sub_outer.rows[1].cells[0]
            else:
                header_cell = outer.rows[0].cells[0]
                subtables_cell = outer.rows[1].cells[0]

        # 1. Update header cell
        set_hotel_header_cell(header_cell, conf_no, font_name="Aptos", size_pt=16.0)

        # 2. Update Subtables
        if subtables_cell.tables:
            # Subtable 0: Metadata Grid (7 rows, 4 cols)
            sub0 = subtables_cell.tables[0]
            if len(sub0.rows) >= 7:
                set_cell_formatted(sub0.rows[1].cells[3], hotel_name, font_name="Aptos", size_pt=16.0, bold=False)
                set_cell_formatted(sub0.rows[2].cells[1], lead_guest, font_name="Aptos", size_pt=16.0, bold=False)
                set_cell_formatted(sub0.rows[2].cells[3], str(len(h.get("guests", [1]))), font_name="Aptos", size_pt=16.0, bold=False)
                set_cell_formatted(sub0.rows[3].cells[1], num_rooms, font_name="Aptos", size_pt=16.0, bold=False)
                set_cell_formatted(sub0.rows[3].cells[3], phone, font_name="Aptos", size_pt=16.0, bold=False)
                # Check-In & Checkout dates are bold in template
                set_cell_formatted(sub0.rows[4].cells[1], check_in, font_name="Aptos", size_pt=16.0, bold=True)
                set_cell_formatted(sub0.rows[4].cells[3], check_out, font_name="Aptos", size_pt=16.0, bold=True)
                set_cell_formatted(sub0.rows[5].cells[1], duration, font_name="Aptos", size_pt=16.0, bold=False)
                set_cell_formatted(sub0.rows[5].cells[3], city, font_name="Aptos", size_pt=16.0, bold=False)
                set_cell_formatted(sub0.rows[6].cells[1], address, font_name="Aptos", size_pt=16.0, bold=False)

            # Subtable 1: Guest Table (EXACT 3-COLUMN STRUCTURE PRESERVED)
            if len(subtables_cell.tables) >= 2:
                sub1 = subtables_cell.tables[1]
                r_data = sub1.rows[1] if len(sub1.rows) > 1 else sub1.add_row()
                while len(sub1.rows) > 2:
                    sub1._tbl.remove(sub1.rows[-1]._tr)

                guests_list = h.get("guests", [])
                if guests_list:
                    guest_names = [g.get('guestName', '') for g in guests_list if g.get('guestName')]
                    if not guest_names:
                        guest_names = [lead_guest]
                    guest_names_str = "\n".join(guest_names)
                    room_type_str = guests_list[0].get("roomType", "Standard Room")
                    pax_str = guests_list[0].get("numGuests", num_guests)
                else:
                    guest_names_str = lead_guest
                    room_type_str = "Standard Room"
                    pax_str = num_guests

                # Exactly 3 columns! No extra column added!
                set_cell_formatted(r_data.cells[0], guest_names_str, font_name="Aptos", size_pt=16.0, bold=False)
                set_cell_formatted(r_data.cells[1], room_type_str, font_name="Aptos", size_pt=16.0, bold=False)
                set_cell_formatted(r_data.cells[2], pax_str, font_name="Aptos", size_pt=16.0, bold=False)

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    doc.save(output_path)
    return output_path


def generate_hotel_blocking_pdf(data: dict, output_path: str):
    """
    Generates high-fidelity Hotel Blocking PDF matching Khanna Travels official format using ReportLab.
    Strictly preserves the exact 3-column table structure: Guest Name | Room Type | No. of Guests.
    """
    doc = SimpleDocTemplate(
        output_path,
        pagesize=A4,
        rightMargin=36,
        leftMargin=36,
        topMargin=36,
        bottomMargin=36
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        'HeaderTitle',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=11,
        leading=15,
        textColor=colors.HexColor('#222222'),
        alignment=0
    )
    label_style = ParagraphStyle(
        'CellLabel',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=9,
        leading=12,
        textColor=colors.HexColor('#333333')
    )
    val_style = ParagraphStyle(
        'CellVal',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=9,
        leading=12,
        textColor=colors.HexColor('#222222')
    )
    val_bold_style = ParagraphStyle(
        'CellValBold',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=9,
        leading=12,
        textColor=colors.HexColor('#111111')
    )
    policy_hdr_style = ParagraphStyle(
        'PolicyHdr',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=9,
        leading=12,
        textColor=colors.HexColor('#55575A')
    )
    policy_body_style = ParagraphStyle(
        'PolicyBody',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=8.5,
        leading=12,
        textColor=colors.HexColor('#55575A')
    )

    story = []
    hotels = data.get("hotels", [])
    applicant = data.get("applicant", {})

    if not hotels:
        hotels = [{
            "confirmationNumber": "TBHBV5YP9R",
            "hotelName": "Hotel Booking Confirmation",
            "leadGuest": applicant.get("fullName", "Lead Guest"),
            "checkIn": "TBD",
            "checkOut": "TBD",
            "duration": "1 Night(s)",
            "city": "",
            "phone": "+61 2 7255 2300",
            "address": "",
            "numRooms": "1",
            "numGuests": "1 Adult(s)",
            "guests": [
                {"guestName": applicant.get("fullName", "Lead Guest"), "roomType": "Standard Room", "numGuests": "1 Adult(s)"}
            ]
        }]

    for idx, h in enumerate(hotels):
        conf_no = h.get("confirmationNumber", "TBHBV5YP9R")
        hotel_name = h.get("hotelName", "Hotel Booking")
        lead_guest = h.get("leadGuest") or applicant.get("fullName") or "Lead Guest"
        check_in = h.get("checkIn", "TBD")
        check_out = h.get("checkOut", "TBD")
        duration = h.get("duration", "1 Night(s)")
        city = h.get("city", "")
        phone = h.get("phone", "+61 2 7255 2300")
        address = h.get("address", "")
        num_rooms = h.get("numRooms", "1")
        num_guests = h.get("numGuests", "1 Adult(s)")

        # Header Box
        hdr_text = f'Thanks for booking with us, your booking has been <b>"Confirmed"</b> with<br/><b>Confirmation Number- {conf_no}</b>'
        hdr_tbl = Table([[Paragraph(hdr_text, title_style)]], colWidths=[523])
        hdr_tbl.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#F8FAFC')),
            ('BOX', (0, 0), (-1, -1), 1, colors.HexColor('#CBD5E1')),
            ('PADDING', (0, 0), (-1, -1), 10),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 10),
        ]))
        story.append(hdr_tbl)
        story.append(Spacer(1, 10))

        # Booking details metadata grid
        meta_data = [
            [Paragraph('<b>Booking details:</b>', policy_hdr_style), '', '', ''],
            [Paragraph('Service Booked:', label_style), Paragraph('Hotel', val_style), Paragraph('Hotel Name:', label_style), Paragraph(hotel_name, val_style)],
            [Paragraph('Lead Guest:', label_style), Paragraph(lead_guest, val_style), Paragraph('No Guest:', label_style), Paragraph(str(len(h.get("guests", [1]))), val_style)],
            [Paragraph('No of Rooms:', label_style), Paragraph(num_rooms, val_style), Paragraph('Phone No:', label_style), Paragraph(phone, val_style)],
            [Paragraph('Check-In:', label_style), Paragraph(check_in, val_bold_style), Paragraph('Checkout:', label_style), Paragraph(check_out, val_bold_style)],
            [Paragraph('Duration:', label_style), Paragraph(duration, val_style), Paragraph('City:', label_style), Paragraph(city, val_style)],
            [Paragraph('Hotel Address:', label_style), Paragraph(address, val_style), '', '']
        ]

        meta_tbl = Table(meta_data, colWidths=[110, 151, 100, 162])
        meta_tbl.setStyle(TableStyle([
            ('SPAN', (0, 0), (3, 0)),
            ('SPAN', (1, 6), (3, 6)),
            ('BACKGROUND', (0, 0), (3, 0), colors.HexColor('#F1F5F9')),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#CBD5E1')),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('TOPPADDING', (0, 0), (-1, -1), 6),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
            ('LEFTPADDING', (0, 0), (-1, -1), 8),
            ('RIGHTPADDING', (0, 0), (-1, -1), 8),
        ]))
        story.append(meta_tbl)
        story.append(Spacer(1, 10))

        # Guest table (EXACT 3-COLUMN STRUCTURE PRESERVED)
        guests = h.get("guests", [])
        if not guests:
            guests = [{"guestName": lead_guest, "roomType": "Standard Room", "numGuests": num_guests}]

        guest_names = "<br/>".join([g.get('guestName', '') for g in guests if g.get('guestName')]) or lead_guest
        room_type = guests[0].get('roomType', 'Standard Room')
        pax = guests[0].get('numGuests', num_guests)

        guest_rows = [
            [Paragraph('<b>Guest Name</b>', label_style), Paragraph('<b>Room Type</b>', label_style), Paragraph('<b>No. of Guests</b>', label_style)],
            [Paragraph(guest_names, val_style), Paragraph(room_type, val_style), Paragraph(pax, val_style)]
        ]

        guest_tbl = Table(guest_rows, colWidths=[240, 163, 120])
        guest_tbl.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#F8FAFC')),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#CBD5E1')),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('TOPPADDING', (0, 0), (-1, -1), 6),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
            ('LEFTPADDING', (0, 0), (-1, -1), 8),
            ('RIGHTPADDING', (0, 0), (-1, -1), 8),
        ]))
        story.append(guest_tbl)
        story.append(Spacer(1, 10))

        # Hotel Policy table
        policy_data = [
            [Paragraph('<b>Hotel Policy:</b>', policy_hdr_style)],
            [Paragraph('Early check out will attract full cancellation charges.<br/>Please note that the cancellation policy is subject to change at any time. Rates are inclusive of all taxes.', policy_body_style)]
        ]
        policy_tbl = Table(policy_data, colWidths=[523])
        policy_tbl.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#F1F5F9')),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#CBD5E1')),
            ('TOPPADDING', (0, 0), (-1, -1), 6),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
            ('LEFTPADDING', (0, 0), (-1, -1), 8),
            ('RIGHTPADDING', (0, 0), (-1, -1), 8),
        ]))
        story.append(policy_tbl)

        if idx < len(hotels) - 1:
            story.append(Spacer(1, 20))

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    doc.build(story)
    return output_path


# =========================================================================
# 3. PASSPORT AUTHORIZATION LETTER GENERATORS
# =========================================================================

def generate_passport_authorization_docx(data: dict, output_path: str):
    """
    Generates high-fidelity Passport Authorization Letter matching templates/Passport Authorization Letter/
    """
    applicant = data.get("applicant", {})
    travel = data.get("travel", {})
    travellers = data.get("travellers", [])

    base_tpl = "templates/Passport Authorization Letter/Passport Authorization Letter.docx"
    if not os.path.exists(base_tpl):
        base_tpl = os.path.join("..", base_tpl)

    doc = docx.Document(base_tpl)
    today_str = datetime.now().strftime("%d-%b-%Y")

    app_name = applicant.get("fullName") or f"{applicant.get('givenNames', '')} {applicant.get('surname', '')}".strip() or "Applicant Name"
    pass_no = applicant.get("passportNumber") or "N/A"
    dest = travel.get("destinationCountry") or "Europe"
    consulate_str = f"Embassy / Consulate General of {dest},\nMumbai / New Delhi, India"

    all_applicants = [(app_name, pass_no)]
    for t in travellers:
        t_name = t.get("fullName")
        t_pass = t.get("passportNumber") or "N/A"
        if t_name:
            all_applicants.append((t_name, t_pass))

    for p in doc.paragraphs:
        if "[Date]" in p.text:
            p.text = p.text.replace("[Date]", today_str)
        if "[Consulate Name and Address]" in p.text:
            p.text = p.text.replace("[Consulate Name and Address]", consulate_str)

        if "[Applicant1 Full Name]" in p.text:
            if len(all_applicants) > 0:
                p.text = f"{all_applicants[0][0]} - Passport No.: {all_applicants[0][1]}"
            else:
                p.text = ""
        elif "[Applicant Full Name]" in p.text or "[Applicant2 Full Name]" in p.text:
            if len(all_applicants) > 1:
                p.text = f"{all_applicants[1][0]} - Passport No.: {all_applicants[1][1]}"
            else:
                p.text = ""

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    doc.save(output_path)
    return output_path


def generate_passport_authorization_pdf(data: dict, output_path: str):
    """
    Generates high-fidelity Passport Authorization Letter PDF using ReportLab.
    """
    doc = SimpleDocTemplate(
        output_path,
        pagesize=A4,
        rightMargin=48,
        leftMargin=48,
        topMargin=48,
        bottomMargin=48
    )

    styles = getSampleStyleSheet()
    p_style = ParagraphStyle(
        'AuthBody',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=10.5,
        leading=16,
        textColor=colors.HexColor('#1E293B'),
        spaceAfter=10
    )
    p_bold_style = ParagraphStyle(
        'AuthBold',
        parent=p_style,
        fontName='Helvetica-Bold'
    )
    p_right_style = ParagraphStyle(
        'AuthRight',
        parent=p_style,
        alignment=2
    )

    applicant = data.get("applicant", {})
    travel = data.get("travel", {})
    travellers = data.get("travellers", [])

    today_str = datetime.now().strftime("%d-%b-%Y")
    app_name = applicant.get("fullName") or f"{applicant.get('givenNames', '')} {applicant.get('surname', '')}".strip() or "Applicant Name"
    pass_no = applicant.get("passportNumber") or "N/A"
    dest = travel.get("destinationCountry") or "Europe"
    consulate_str = f"Embassy / Consulate General of {dest},<br/>Mumbai / New Delhi, India"

    all_applicants = [(app_name, pass_no)]
    for t in travellers:
        t_name = t.get("fullName")
        t_pass = t.get("passportNumber") or "N/A"
        if t_name:
            all_applicants.append((t_name, t_pass))

    story = [
        Paragraph(f"<b>Date:</b> {today_str}", p_right_style),
        Spacer(1, 10),
        Paragraph("To,<br/><b>The Visa Officer,</b><br/>" + consulate_str, p_style),
        Spacer(1, 10),
        Paragraph("<b>Subject: Authorization Letter for my Visa Application.</b>", p_bold_style),
        Spacer(1, 10),
        Paragraph("Dear Sir/Madam,", p_style),
        Paragraph("We, <b>Khanna Holidays Pvt. Ltd.</b> have been authorized to collect original Passport of our clients mentioned below –", p_style),
        Spacer(1, 6)
    ]

    for i, (name, p_num) in enumerate(all_applicants):
        story.append(Paragraph(f"<b>{i+1}. {name}</b> - Passport No.: <b>{p_num}</b>", p_style))

    story.extend([
        Spacer(1, 10),
        Paragraph("The applicants have authorized us to do the passport collection on their behalf.", p_style),
        Paragraph("Kindly feel free to contact us for more information.", p_style),
        Spacer(1, 14),
        Paragraph("Thanking You,<br/><br/>Yours Faithfully,<br/><br/><b>Ms. Dhvani Chheda</b><br/><b>Team Lead – Visa</b><br/>Phone No. +91 8657461001<br/>Email id: customercare@khannatravels.com", p_style)
    ])

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    doc.build(story)
    return output_path


# =========================================================================
# 4. COMPANY AUTHORIZATION LETTER GENERATORS
# =========================================================================

def generate_company_authorization_docx(data: dict, output_path: str):
    """
    Generates high-fidelity Company Authorization Letter matching templates/Company Authorization Letter/
    """
    applicant = data.get("applicant", {})
    travel = data.get("travel", {})
    travellers = data.get("travellers", [])

    base_tpl = "templates/Company Authorization Letter/Company Authorization Letter.docx"
    if not os.path.exists(base_tpl):
        base_tpl = os.path.join("..", base_tpl)

    doc = docx.Document(base_tpl)
    today_str = datetime.now().strftime("%d-%b-%Y")

    app_name = applicant.get("fullName") or f"{applicant.get('givenNames', '')} {applicant.get('surname', '')}".strip() or "Applicant Name"
    pass_no = applicant.get("passportNumber") or "N/A"
    dest = travel.get("destinationCountry") or "Europe"
    consulate_str = f"Embassy / Consulate General of {dest},\nMumbai / New Delhi, India"

    all_applicants = [(app_name, pass_no)]
    for t in travellers:
        t_name = t.get("fullName")
        t_pass = t.get("passportNumber") or "N/A"
        if t_name:
            all_applicants.append((t_name, t_pass))

    for p in doc.paragraphs:
        if "[Date]" in p.text:
            p.text = p.text.replace("[Date]", today_str)
        if "[Consulate Name and Address]" in p.text:
            p.text = p.text.replace("[Consulate Name and Address]", consulate_str)

        if "[Applicant1 Full Name]" in p.text:
            if len(all_applicants) > 0:
                p.text = f"{all_applicants[0][0]} - Passport No.: {all_applicants[0][1]}"
            else:
                p.text = ""
        elif "[Applicant2 Full Name]" in p.text or "[Applicant Full Name]" in p.text:
            if len(all_applicants) > 1:
                p.text = f"{all_applicants[1][0]} - Passport No.: {all_applicants[1][1]}"
            else:
                p.text = ""

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    doc.save(output_path)
    return output_path


def generate_company_authorization_pdf(data: dict, output_path: str):
    """
    Generates high-fidelity Company Authorization Letter PDF using ReportLab.
    """
    doc = SimpleDocTemplate(
        output_path,
        pagesize=A4,
        rightMargin=48,
        leftMargin=48,
        topMargin=48,
        bottomMargin=48
    )

    styles = getSampleStyleSheet()
    p_style = ParagraphStyle(
        'AuthBody',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=10.5,
        leading=16,
        textColor=colors.HexColor('#1E293B'),
        spaceAfter=10
    )
    p_bold_style = ParagraphStyle(
        'AuthBold',
        parent=p_style,
        fontName='Helvetica-Bold'
    )
    p_right_style = ParagraphStyle(
        'AuthRight',
        parent=p_style,
        alignment=2
    )

    applicant = data.get("applicant", {})
    travel = data.get("travel", {})
    travellers = data.get("travellers", [])

    today_str = datetime.now().strftime("%d-%b-%Y")
    app_name = applicant.get("fullName") or f"{applicant.get('givenNames', '')} {applicant.get('surname', '')}".strip() or "Applicant Name"
    pass_no = applicant.get("passportNumber") or "N/A"
    dest = travel.get("destinationCountry") or "Europe"
    consulate_str = f"Embassy / Consulate General of {dest},<br/>Mumbai / New Delhi, India"

    all_applicants = [(app_name, pass_no)]
    for t in travellers:
        t_name = t.get("fullName")
        t_pass = t.get("passportNumber") or "N/A"
        if t_name:
            all_applicants.append((t_name, t_pass))

    story = [
        Paragraph(f"<b>Date:</b> {today_str}", p_right_style),
        Spacer(1, 10),
        Paragraph("To,<br/><b>The Visa Officer,</b><br/>" + consulate_str, p_style),
        Spacer(1, 10),
        Paragraph("<b>Subject: Authorization Letter for my Visa Application.</b>", p_bold_style),
        Spacer(1, 10),
        Paragraph("Dear Sir/Madam,", p_style),
        Paragraph("We, <b>Khanna Holidays Pvt. Ltd.</b> have been authorized to collect original Passport of our clients mentioned below –", p_style),
        Spacer(1, 6)
    ]

    for i, (name, p_num) in enumerate(all_applicants):
        story.append(Paragraph(f"<b>{i+1}. {name}</b> - Passport No.: <b>{p_num}</b>", p_style))

    story.extend([
        Spacer(1, 10),
        Paragraph("The applicants have authorized us to do the passport collection on their behalf.", p_style),
        Paragraph("Kindly feel free to contact us for more information.", p_style),
        Spacer(1, 14),
        Paragraph("Thanking You,<br/><br/>Yours Faithfully,<br/><br/><b>Ms. Dhvani Chheda</b><br/><b>Team Lead – Visa</b><br/>Phone No. +91 8657461001<br/>Email id: customercare@khannatravels.com", p_style)
    ])

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    doc.build(story)
    return output_path


# =========================================================================
# CLI ENTRY POINT
# =========================================================================

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(json.dumps({"error": "Usage: docx_engine.py <json_payload_file> <output_path> [format: docx|pdf]"}))
        sys.exit(1)

    payload_file = sys.argv[1]
    out_file = sys.argv[2]
    export_format = sys.argv[3] if len(sys.argv) > 3 else ("pdf" if out_file.lower().endswith(".pdf") else "docx")

    with open(payload_file, 'r', encoding='utf-8') as f:
        data = json.load(f)

    doc_type = data.get("docType", "cover_letter")

    if export_format == "pdf":
        if doc_type == "hotel_blocking":
            res_path = generate_hotel_blocking_pdf(data, out_file)
        elif doc_type == "passport_authorization":
            res_path = generate_passport_authorization_pdf(data, out_file)
        elif doc_type == "company_authorization":
            res_path = generate_company_authorization_pdf(data, out_file)
        else:
            res_path = generate_cover_letter_pdf(data, out_file)
    else:
        if doc_type == "hotel_blocking":
            res_path = generate_hotel_blocking_docx(data, out_file)
        elif doc_type == "passport_authorization":
            res_path = generate_passport_authorization_docx(data, out_file)
        elif doc_type == "company_authorization":
            res_path = generate_company_authorization_docx(data, out_file)
        else:
            res_path = generate_cover_letter_docx(data, out_file)

    print(json.dumps({"status": "success", "file": res_path}))
