from concurrent.futures import ThreadPoolExecutor, as_completed
import os
import re
from bs4 import BeautifulSoup
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import pydantic
import requests
from urllib.parse import urljoin, urlparse

app = FastAPI(title="RRM Web Scraper API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

EMAIL_REGEX = r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+"
PHONE_REGEX = r"(\+?\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML,"
        " like Gecko) Chrome/122.0.0.0 Safari/537.36"
    )
}

def clean_text_data(text):
    emails = set()
    phones = set()
    found_emails = re.findall(EMAIL_REGEX, text)
    found_phones = re.findall(PHONE_REGEX, text)

    for e in found_emails:
        e_lower = e.lower()
        if not any(ext in e_lower for ext in [".png", ".jpg", ".webp", ".svg", "example.com", "sentry", "w3.org"]):
            emails.add(e_lower)

    for p_num in found_phones:
        if isinstance(p_num, tuple):
            p_num = p_num[0]
        p_clean = p_num.strip()
        if len(p_clean) >= 7 and not p_clean.startswith("000"):
            phones.add(p_clean)

    return emails, phones

def get_domain_root(domain):
    try:
        parsed = urlparse(domain if domain.startswith("http") else "https://" + domain)
        netloc = parsed.netloc or parsed.path
        parts = netloc.split(".")
        if len(parts) >= 2:
            return parts[-2]
    except Exception:
        pass
    return ""

def extract_services(soup):
    services = []
    for tag in soup.find_all(["h2", "h3", "h4", "li"]):
        text = tag.get_text(strip=True)
        if len(text) > 4 and len(text) < 55 and not any(w in text.lower() for w in ["copyright", "privacy", "terms", "login"]):
            if text not in services:
                services.append(text)
        if len(services) >= 3:
            break
    return "; ".join(services[:3]) if services else "NotFound"

def scrape_website_logic(domain):
    if not domain or str(domain).strip() in ["nan", "None", ""]:
        return {"Web_CompanyName": "NotFound", "companyDomain": "", "web": "NotFound", "Main_Services": "NotFound"}

    url = str(domain).strip()
    if not url.startswith("http"):
        url = "https://" + url

    domain_root = get_domain_root(url)
    all_emails = set()
    extracted_services_list = []

    try:
        res = requests.get(url, headers=HEADERS, timeout=10)
        if res.status_code == 200:
            soup = BeautifulSoup(res.text, "html.parser")
            extracted_services_list.append(extract_services(soup))
            e, _ = clean_text_data(res.text)
            all_emails.update(e)
    except Exception:
        pass

    all_emails_list = list(all_emails)
    primary_email = ""
    for em in all_emails_list:
        if domain_root and domain_root in em:
            primary_email = em
            break
    if not primary_email and all_emails_list:
        primary_email = all_emails_list[0]

    return {
        "Web_CompanyName": urlparse(url).netloc.replace("www.", "").capitalize(),
        "companyDomain": domain,
        "web": primary_email if primary_email else "NotFound",
        "Main_Services": extracted_services_list[0] if extracted_services_list else "NotFound"
    }

class SingleUrlRequest(pydantic.BaseModel):
    url: str

@app.post("/api/scrape-single")
def scrape_single(data: SingleUrlRequest):
    try:
        result = scrape_website_logic(data.url)
        return {"status": "success", "data": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))