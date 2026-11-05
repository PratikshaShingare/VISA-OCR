"""
One deliberate, real azapi.ai call — run by hand on YOUR machine.

    python azapi_selftest.py "front.pdf"              (front page only)
    python azapi_selftest.py "front.pdf" "back.pdf"  (front + back)

This SPENDS CREDITS (2.5 per call) and asks you to confirm first. The
automatic test-suite never does this: it uses faked responses only.

It reads AZAPI_API_KEY from backend/python/.env, sends the file(s) exactly the
way the website does, and prints what azapi returned. Passport details are
printed in YOUR terminal only — nothing is saved to disk or logged.
"""
import os
import sys

try:
    from dotenv import load_dotenv

    load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
except ImportError:
    pass

import ocr_azapi
import ocr_runner


def jpeg_of(path):
    pages = ocr_runner.load_pages(path)
    return ocr_azapi.to_jpeg_bytes(pages[0])


def main(argv):
    if not 1 <= len(argv) <= 2:
        print(__doc__)
        return 2
    if not ocr_azapi.is_enabled():
        print("AZAPI_API_KEY is not set in backend/python/.env (or AZAPI_ENABLED is off). Nothing was sent.")
        return 2
    print(f"Endpoint: {ocr_azapi._url()}")
    print(f"Files: {', '.join(os.path.basename(a) for a in argv)}")
    if input("This uses 2.5 credits. Type YES to continue: ").strip() != "YES":
        print("Cancelled. Nothing was sent.")
        return 1
    front = jpeg_of(argv[0])
    back = jpeg_of(argv[1]) if len(argv) == 2 else None
    try:
        output = ocr_azapi.call_api(front, back)
    except ocr_azapi.AzapiError as e:
        print(f"FAILED ({e.kind}): {e}")
        return 1
    normalized = ocr_azapi.normalize(output)
    print("\nazapi answered. Parsed fields:")
    for key, value in normalized.items():
        print(f"  {key}: {value}")
    print("\nCompare these with the passport itself. The website will show them as 'OCR Extracted - Please Verify'.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
