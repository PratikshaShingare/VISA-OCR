"""Fill Forms (visa_forms.py) and Check Forms (form_check.py).

All data here is invented — never a real client's passport (project rule 11)."""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

pypdf = pytest.importorskip("pypdf")

import form_check  # noqa: E402
import visa_forms  # noqa: E402

PASSPORT = {
    "label": "SHARMA ANITA RAJ",
    "surname": "SHARMA",
    "givenNames": "ANITA RAJ",
    "dob": "1980-05-14",
    "sex": "F",
    "nationality": "INDIAN",
    "countryCode": "IND",
    "placeOfBirth": "PUNE, MAHARASHTRA",
    "passportNumber": "Z1234567",
    "passportType": "P",
    "issueDate": "2020-01-10",
    "expiryDate": "2035-01-09",
    "issuePlace": "MUMBAI",
    "issuingAuthority": "",
}

VALUES = dict(
    surname="Sharma", givenNames="Anita Raj", dob="1980-05-14", birthCity="Pune", birthState="Maharashtra", birthCountry="India",
    sex="F", maritalStatus="married", nationality="Indian", passportType="ordinary", passportNumber="Z1234567",
    issuePlace="Mumbai", issueDate="2020-01-10", issuingAuthority="Government of India", expiryDate="2035-01-09",
    purpose="Tourism", lengthOfStay="11 days", arrivalDate="2030-12-20", portOfEntry="Tokyo", airline="All Nippon Airways",
    hotelName="Sample Hotel Tokyo", hotelTel="+81 3-0000-0000", hotelAddress="1-2-3 Sample Street, Koto City, Tokyo",
    homeAddress="12 Sample Society, Example Road, Pune 411001", mobile="9800000000", occupation="Engineer",
    guarantorName="Sample Hotel Tokyo", guarantorTel="+81 3-0000-0000", guarantorAddress="1-2-3 Sample Street, Koto City, Tokyo",
    q1Crime="no", q2Prison="no", q3Deported="no", q4Drugs="no", q5Prostitution="no", q6Trafficking="no",
)


def _fill(tmp_path, **changes):
    values = dict(VALUES, **changes)
    content, missing, _overflow = visa_forms.fill_form("japan-visa", values)
    path = tmp_path / "form.pdf"
    path.write_bytes(content)
    return str(path), missing


def _by_key(extract):
    return {f["key"]: f["value"] for f in extract["fields"]}


# --------------------------------------------------------------------------- forms


def test_list_forms_hides_pdf_field_names():
    forms = visa_forms.list_forms()
    japan = next(f for f in forms if f["id"] == "japan-visa")
    assert japan["available"] is True
    for section in japan["sections"]:
        for field in section["fields"]:
            assert "pdf" not in field
            for opt in field.get("options", []):
                assert "state" not in opt


def test_fill_writes_values_in_capitals_and_ticks_radios(tmp_path):
    path, missing = _fill(tmp_path)
    assert missing == []
    reader = pypdf.PdfReader(path)
    assert "/XFA" not in reader.trailer["/Root"]["/AcroForm"]
    got = _by_key(form_check.extract_document(path, allow_ocr=False))
    assert got["surname"] == "SHARMA"
    assert got["givenNames"] == "ANITA RAJ"
    assert got["dob"] == "14/05/1980"
    assert got["arrivalDate"] == "20-12-2030"  # the form's sample writes arrival with dashes
    assert got["sex"] == "Female"
    assert got["maritalStatus"] == "Married"
    assert got["passportType"] == "Ordinary"
    assert got["q3Deported"] == "No"
    assert got["placeOfBirth"].split() == ["PUNE", "MAHARASHTRA", "INDIA"]
    assert got["applicationDate"] == ""


def test_fill_reports_required_fields_left_empty(tmp_path):
    _path, missing = _fill(tmp_path, q4Drugs="", surname="")
    assert "Surname (as shown in passport)" in missing
    assert any("drug" in m for m in missing)


def test_unknown_form_is_a_clean_error():
    with pytest.raises(visa_forms.FormError):
        visa_forms.fill_form("nowhere-visa", {})


def test_format_date_accepts_iso_and_ddmmyyyy():
    assert visa_forms.format_date("2026-10-20", "DD-MM-YYYY") == "20-10-2026"
    assert visa_forms.format_date("20-10-2026", "DD/MM/YYYY") == "20/10/2026"
    assert visa_forms.format_date("-", "DD/MM/YYYY") == "-"


# --------------------------------------------------------------------------- check


def _check(path, passports=(PASSPORT,), supporting=()):
    extract = form_check.extract_document(path, allow_ocr=False)
    extract["fileName"] = "form.pdf"
    return form_check.check_form(extract, list(passports), list(supporting))


def _status(result, field):
    return [f["status"] for f in result["findings"] if f["field"] == field]


def test_correct_form_has_nothing_to_correct(tmp_path):
    path, _ = _fill(tmp_path)
    result = _check(path)
    assert result["summary"]["correct"] == 0, result["findings"]
    assert result["summary"]["missing"] == 0, result["findings"]
    for key in ("surname", "givenNames", "dob", "sex", "nationality", "passportNumber", "issueDate", "expiryDate", "passportType", "placeOfBirth", "issuePlace"):
        assert _status(result, key) == ["ok"], key


def test_mistakes_are_found_with_the_right_advice(tmp_path):
    path, _ = _fill(tmp_path, surname="SHRAMA", passportNumber="Z1234576", dob="05/14/1980", sex="M", issueDate="2021-01-10")
    result = _check(path)
    msgs = {f["field"]: f for f in result["findings"]}
    assert msgs["surname"]["status"] == "correct"
    assert msgs["passportNumber"]["status"] == "correct"
    assert "different order" in msgs["passportNumber"]["message"]
    assert msgs["sex"]["status"] == "correct"
    assert msgs["issueDate"]["status"] == "correct" and "year" in msgs["issueDate"]["message"]
    assert msgs["dob"]["expected"] == "14/05/1980"
    assert msgs["dob"]["status"] == "correct" and "month first" in msgs["dob"]["message"]


def test_swapped_day_and_month_is_named(tmp_path):
    path, _ = _fill(tmp_path, issueDate="")
    extract = form_check.extract_document(path, allow_ocr=False)
    for f in extract["fields"]:
        if f["key"] == "issueDate":
            f["value"] = "01/10/2020"  # 1 Oct instead of 10 Jan
    result = form_check.check_form(extract, [PASSPORT], [])
    item = next(f for f in result["findings"] if f["field"] == "issueDate")
    assert item["status"] == "correct" and "swapped" in item["message"]


def test_unanswered_questions_are_listed(tmp_path):
    path, _ = _fill(tmp_path, q1Crime="")
    result = _check(path)
    assert any(f["status"] == "missing" and "convicted of a crime" in f["label"] for f in result["findings"])


def test_short_passport_validity_is_flagged(tmp_path):
    path, _ = _fill(tmp_path, arrivalDate="2034-10-01")
    result = _check(path)
    assert any(f["label"] == "Passport validity" and f["status"] == "check" for f in result["findings"])


def test_the_right_passport_is_chosen_from_several(tmp_path):
    path, _ = _fill(tmp_path)
    other = dict(PASSPORT, label="MEHTA RAVI", surname="MEHTA", givenNames="RAVI", passportNumber="Y7654321")
    result = _check(path, passports=[other, PASSPORT])
    assert result["passportUsed"] == "SHARMA ANITA RAJ"
    assert result["summary"]["correct"] == 0


def test_supporting_documents_confirm_address_and_phone(tmp_path):
    path, _ = _fill(tmp_path)
    support = {"fileName": "booking.pdf", "text": "Booking at Sample Hotel Tokyo, 1-2-3 Sample Street, Koto City, Tokyo. Tel +81 3 0000 0000", "fields": []}
    result = _check(path, supporting=[support])
    hotel = [f for f in result["findings"] if f["field"] == "hotelName"]
    assert hotel and hotel[0]["status"] == "ok" and hotel[0]["source"] == "booking.pdf"
    tel = [f for f in result["findings"] if f["field"] == "hotelTel"]
    assert tel and tel[0]["status"] == "ok"
    home = [f for f in result["findings"] if f["field"] == "homeAddress"]
    assert home and home[0]["status"] == "info"


def test_supporting_document_with_a_different_passport_number_is_flagged(tmp_path):
    path, _ = _fill(tmp_path)
    support = {"fileName": "ticket.pdf", "text": "Passenger SHARMA ANITA RAJ passport Z1234561", "fields": []}
    result = _check(path, supporting=[support])
    assert any(f["status"] == "check" and "ticket.pdf" in f["label"] for f in result["findings"])


def test_text_only_form_is_searched_for_passport_details():
    form = {"fileName": "scan.jpg", "fields": [], "text": "Surname SHARMA Given names ANITA RAJ Passport Z1234667 Date of birth 14/05/1980 Issued 10/01/2020 Expiry 09-01-2035", "method": "ocr"}
    result = form_check.check_form(form, [PASSPORT], [])
    by = {f["field"]: f for f in result["findings"]}
    assert by["passportNumber"]["status"] == "correct" and by["passportNumber"]["formValue"] == "Z1234667"
    assert by["surname"]["status"] == "ok"
    assert by["dob"]["status"] == "ok"
    assert by["expiryDate"]["status"] == "ok"


def test_unknown_fillable_form_uses_field_labels(tmp_path):
    # A generic fillable PDF (not one we have a definition for): labels decide.
    from pypdf import PdfWriter
    from pypdf.generic import ArrayObject, DictionaryObject, FloatObject, NameObject, NumberObject, TextStringObject

    writer = PdfWriter()
    page = writer.add_blank_page(400, 400)
    fields = ArrayObject()
    for i, (name, label, value) in enumerate([("f1", "Family name", "SHARMA"), ("f2", "Passport number", "Z1234567"), ("f3", "Date of birth", "15/05/1980")]):
        w = DictionaryObject({
            NameObject("/Type"): NameObject("/Annot"), NameObject("/Subtype"): NameObject("/Widget"),
            NameObject("/FT"): NameObject("/Tx"), NameObject("/T"): TextStringObject(name),
            NameObject("/TU"): TextStringObject(label), NameObject("/V"): TextStringObject(value),
            NameObject("/Rect"): ArrayObject([FloatObject(10), FloatObject(10 + i * 30), FloatObject(200), FloatObject(30 + i * 30)]),
        })
        ref = writer._add_object(w)
        page[NameObject("/Annots")] = page.get("/Annots", ArrayObject()) if "/Annots" in page else ArrayObject()
        page["/Annots"].append(ref)
        fields.append(ref)
    writer._root_object[NameObject("/AcroForm")] = DictionaryObject({NameObject("/Fields"): fields})
    path = tmp_path / "generic.pdf"
    with open(path, "wb") as fh:
        writer.write(fh)
    extract = form_check.extract_document(str(path), allow_ocr=False)
    assert extract["formId"] is None and extract["method"] == "form-fields"
    result = form_check.check_form(extract, [PASSPORT], [])
    by = {f["field"]: f for f in result["findings"]}
    assert by["surname"]["status"] == "ok"
    assert by["passportNumber"]["status"] == "ok"
    assert by["dob"]["status"] == "correct" and "day" in by["dob"]["message"]


def test_api_endpoints(tmp_path):
    from fastapi.testclient import TestClient

    import app as app_module

    client = TestClient(app_module.app)
    forms = client.get("/api/forms").json()["forms"]
    assert any(f["id"] == "japan-visa" for f in forms)

    res = client.post("/api/forms/fill", json={"formId": "japan-visa", "values": VALUES, "applicantName": "Anita Sharma"})
    assert res.status_code == 200 and res.content[:4] == b"%PDF"
    assert "Japan_Visa_Application_Form_Anita_Sharma.pdf" in res.headers["content-disposition"]

    res = client.post("/api/form-check/extract", files={"file": ("form.pdf", res.content, "application/pdf")})
    assert res.status_code == 200
    extract = res.json()
    assert extract["formId"] == "japan-visa" and extract["fileName"] == "form.pdf"

    res = client.post("/api/form-check/compare", json={"form": extract, "passports": [PASSPORT], "supporting": []})
    assert res.status_code == 200
    assert res.json()["summary"]["correct"] == 0

    assert client.post("/api/forms/fill", json={"formId": "nope", "values": {}}).status_code == 400
    assert client.post("/api/form-check/extract", files={"file": ("x.txt", b"hi", "text/plain")}).status_code == 400


# --------------------------------------------------------------------------- long text


def test_long_address_wraps_onto_the_next_line_inside_the_box(tmp_path):
    address = "Flat 1203, Sample Heights Co-operative Housing Society, Plot No. 45, Sector 17, Near Example Station, Navi Mumbai 400703"
    path, _missing = _fill(tmp_path, homeAddress=address)
    reader = pypdf.PdfReader(path)
    widget = next(a.get_object() for a in reader.pages[0]["/Annots"] if a.get_object().get("/T") == "T0[1]")
    lines = str(widget["/V"]).split("\n")
    assert len(lines) == 2
    assert " ".join(lines) == address.upper()
    metrics = visa_forms.font_metrics(reader.trailer["/Root"]["/AcroForm"], "/MyriadPro-Regular")
    size = visa_forms._da_parts(str(widget["/DA"]))[1]
    box = [float(x) for x in widget["/Rect"]]
    assert all(metrics.width(line, size) <= box[2] - box[0] - 4 for line in lines)
    # Read back by Check Forms as one value.
    got = _by_key(form_check.extract_document(path, allow_ocr=False))
    assert got["homeAddress"] == address.upper()


def test_one_long_word_is_broken_and_shrunk_to_fit():
    metrics = visa_forms.FontMetrics({}, 600, 1.2)
    lines, size, fits = visa_forms.fit_text("A" * 130, 420, 24, True, metrics)
    assert fits and len(lines) >= 2 and size < 11
    assert all(metrics.width(line, size) <= 416 for line in lines)


def test_single_line_field_gets_smaller_letters_and_reports_what_cannot_fit(tmp_path):
    _path, _missing = _fill(tmp_path, airline="ALL NIPPON AIRWAYS")
    content, _m, overflow = visa_forms.fill_form("japan-visa", dict(VALUES, airline="X" * 120, employerAddress="Y" * 600))
    assert "Name of ship or airline" in overflow
    assert "Employer — Address" in overflow
    content, _m, overflow = visa_forms.fill_form("japan-visa", VALUES)
    assert overflow == []


# --------------------------------------------------------------------------- Singapore Form 14A

SG_VALUES = dict(
    fullName="Sharma Anita Raj Kumar Prasad Verma", dob="1980-05-14", sex="F", maritalStatus="married",
    birthCountryPlace="India Pune", birthState="Maharashtra", race="Indian", nationality="Indian", documentType="international",
    passportNumber="Z1234567", issueDate="10-01-2020", expiryDate="09-01-2035", issueCountryPlace="India Mumbai",
    originCountry="India", originState="Maharashtra", originAddress="12 Sample Society, Pune 411001",
    email="anita@example.com", contactNumber="9800000000", occupation="Self employed", education="postGraduate",
    annualIncome="25000", religion="Hindu", arrivalDate="04-12-2030", visaType="multiple", purpose="social",
    purposeDetails="Tourism", stayLength="less30", stayPlace="hotel", sgPostalCode="219924", sgStreet="3 Sample Rd",
    sgContactNo="+65 6000 0000", sgBuildingName="Sample Garden Inn", residedAbroad="no",
    localContactName="Sample Garden Inn Singapore Serangoon", localContactRelationship="Hotel", localContactNo="+65 6000 0000",
    qRefused="no", qConvicted="no", qProhibited="no", qOtherIdentity="no",
)

SG_PASSPORT = dict(PASSPORT, givenNames="ANITA RAJ KUMAR PRASAD", surname="SHARMA VERMA", placeOfBirth="PUNE, MAHARASHTRA")


def _fill_sg(tmp_path, **changes):
    content, missing, overflow = visa_forms.fill_form("singapore-visa", dict(SG_VALUES, **changes))
    path = tmp_path / "sg.pdf"
    path.write_bytes(content)
    return str(path), missing, overflow


def test_singapore_form_fields_exist_on_the_blank_pdf():
    d = visa_forms.get_definition("singapore-visa")
    names = set(visa_forms._widgets_by_name(pypdf.PdfReader(visa_forms.template_path(d)).pages))
    for field in visa_forms.iter_fields(d):
        for name in visa_forms.pdf_names(field):
            assert name in names, (field["key"], name)


def test_singapore_letter_boxes_dates_and_two_row_name(tmp_path):
    path, missing, overflow = _fill_sg(tmp_path)
    assert missing == [] and overflow == []
    fields = {k: str(v.get("/V") or "") for k, v in pypdf.PdfReader(path).get_fields().items()}
    assert fields["fullName_1"] == "SHARMA ANITA RAJ KUMAR"  # broken between words, 25 boxes
    assert fields["fullName_2"] == "PRASAD VERMA"
    assert (fields["dob_day"], fields["dob_month"], fields["dob_year"]) == ("14", "05", "1980")
    assert (fields["arrivalDate_day"], fields["arrivalDate_month"], fields["arrivalDate_year"]) == ("04", "12", "2030")
    assert fields["sex"] == "/Female" and fields["qRefused"] == "/No" and fields["stayPlace"] == "/Hotel"
    assert fields["passportNumber"] == "Z1234567"


def test_singapore_too_long_for_the_boxes_is_reported(tmp_path):
    _path, _missing, overflow = _fill_sg(tmp_path, fullName="A" * 30 + " " + "B" * 30, religion="X" * 40)
    assert "Name (full name as shown in passport)" in overflow
    assert "Religion" in overflow


def test_singapore_read_back_and_checked(tmp_path):
    path, _m, _o = _fill_sg(tmp_path)
    extract = form_check.extract_document(path, allow_ocr=False)
    assert extract["formId"] == "singapore-visa"
    got = _by_key(extract)
    assert got["fullName"] == "SHARMA ANITA RAJ KUMAR PRASAD VERMA"
    assert got["dob"] == "14/05/1980" and got["sex"] == "Female"
    result = form_check.check_form(extract, [dict(SG_PASSPORT, surname="SHARMA", givenNames="ANITA RAJ KUMAR PRASAD VERMA")], [])
    by = {f["field"]: f["status"] for f in result["findings"]}
    assert by["fullName"] == "ok" and by["dob"] == "ok" and by["passportNumber"] == "ok"
    assert by["placeOfBirth"] == "ok" and by["issuePlace"] == "ok" and by["nationality"] == "ok"
    assert result["summary"]["correct"] == 0, result["findings"]
    wrong = form_check.check_form(extract, [dict(PASSPORT, surname="SHARMA", givenNames="ANITA RAJ KUMAR PRASAD VERNA")], [])
    assert {f["field"]: f["status"] for f in wrong["findings"]}["fullName"] == "correct"


def test_split_rows():
    assert visa_forms.split_rows("AB CD EF", [5, 5]) == (["AB CD", "EF"], "")
    assert visa_forms.split_rows("ABCDEFGH", [5, 5]) == (["ABCDE", "FGH"], "")
    assert visa_forms.split_rows("AAAA BBBB CCCC", [4, 4]) == (["AAAA", "BBBB"], "CCCC")
