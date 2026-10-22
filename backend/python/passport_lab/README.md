# Passport Lab

A local Streamlit page for comparing passport-extraction engines side by side.
It is a test bench — it does **not** change the website.

## Run it
Double-click `Start Passport Lab.bat` in the project folder (first run installs Streamlit), or:

```
cd backend\python
pip install -r requirements.txt -r requirements-lab.txt
streamlit run passport_lab\app.py
```
It opens at http://localhost:8501.

## Engines
| Engine | Where it runs | Needs |
|---|---|---|
| Current website pipeline | this computer | Tesseract |
| Free local MRZ reader (v2) | this computer | Tesseract |
| Google Vision | cloud | `GOOGLE_VISION_API_KEY` in `backend/python/.env` + consent tick |
| AI vision model (OpenRouter) | cloud | `OPENROUTER_API_KEY` in `backend/python/.env` + consent tick |

## How to pick the winner
1. Upload 10–20 of your own real passports (photos AND scans).
2. For each one, type the true values under "Score against the real passport" and add to the scoreboard.
3. The engine with the highest % — especially on name, passport number, dates — is the one to move into the website.

## Notes
* Nothing is saved or logged; the upload is deleted when the engines finish.
* MRZ fields are check-digit protected; printed-only fields (place of birth/issue, date of issue) are never guaranteed.
* Use consented/test passports; never commit real passport images.
