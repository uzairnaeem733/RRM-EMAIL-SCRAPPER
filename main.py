from fastapi import FastAPI, File, Form, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
import pandas as pd
import io
import requests
from bs4 import BeautifulSoup
from urllib.parse import urlparse, urljoin
import re
from concurrent.futures import ThreadPoolExecutor, as_completed

app = FastAPI()

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
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
}

def clean_text_data(text):
    emails = set()
    phones = set()
    found_emails = re.findall(EMAIL_REGEX, text)
    found_phones = re.findall(PHONE_REGEX, text)

    for e in found_emails:
        e_lower = e.lower()
        if not any(ext in e_lower for ext in ['.png', '.jpg', '.webp', '.svg', 'example.com', 'sentry', 'w3.org', 'bootstrap', 'schema.org', 'wordpress', 'jquery', 'domain.com']):
            emails.add(e_lower)

    for p_num in found_phones:
        if isinstance(p_num, tuple):
            p_num = p_num[0]
        p_clean = p_num.strip()
        if len(p_clean) >= 7 and not p_clean.startswith('000') and not p_clean.startswith('111'):
            phones.add(p_clean)

    return emails, phones

def get_domain_root(domain):
    try:
        parsed = urlparse(domain if domain.startswith('http') else 'https://' + domain)
        netloc = parsed.netloc or parsed.path
        parts = netloc.split('.')
        if len(parts) >= 2:
            return parts[-2]
    except Exception:
        pass
    return ""

def extract_company_name_from_domain(domain):
    try:
        parsed = urlparse(domain if domain.startswith('http') else 'https://' + domain)
        netloc = parsed.netloc or parsed.path
        netloc = netloc.replace("www.", "")
        name_part = netloc.split('.')[0]
        return name_part.capitalize()
    except Exception:
        return "NotFound"

def extract_services(soup):
    services = []
    for tag in soup.find_all(['h2', 'h3', 'h4', 'li']):
        text = tag.get_text(strip=True)
        if len(text) > 4 and len(text) < 55 and not any(w in text.lower() for w in ['copyright', 'all rights', 'privacy', 'terms', 'login', 'sign up', 'menu', 'cookie']):
            if text not in services:
                services.append(text)
        if len(services) >= 3:
            break
    return "; ".join(services[:3]) if services else "NotFound"

def scrape_website_logic(domain, input_company_name="", apollo_email="NotFound"):
    if not domain or str(domain).strip() in ["nan", "None", ""]:
        return {
            "Web_CompanyName": input_company_name if input_company_name and input_company_name != "nan" else "NotFound",
            "companyDomain": "",
            "web": "NotFound",
            "Apollo_Email": apollo_email,
            "Other_Scraped_Emails": "NotFound",
            "Scraped_Phones": "NotFound",
            "Main_Services": "NotFound"
        }

    url = str(domain).strip()
    if not url.startswith("http"):
        url = "https://" + url

    domain_root = get_domain_root(url)
    comp_name = str(input_company_name).strip() if input_company_name and str(input_company_name).strip() not in ["nan", "None", ""] else extract_company_name_from_domain(url)

    all_emails = set()
    all_phones = set()
    extracted_services_list = []
    pages_to_visit = [url]
    visited_pages = set()

    try:
        res = requests.get(url, headers=HEADERS, timeout=10)
        if res.status_code == 200:
            soup = BeautifulSoup(res.text, 'html.parser')
            s_text = extract_services(soup)
            if s_text and s_text != "NotFound":
                extracted_services_list.append(s_text)
            e, p = clean_text_data(res.text)
            all_emails.update(e)
            all_phones.update(p)

            for a_tag in soup.find_all('a', href=True):
                link_text = a_tag.get_text().lower()
                href = a_tag['href'].lower()
                if any(w in link_text or w in href for w in ['contact', 'about', 'service', 'team', 'support', 'reach', 'get-in-touch']):
                    full_link = urljoin(url, a_tag['href'])
                    if full_link not in pages_to_visit and len(pages_to_visit) < 5:
                        pages_to_visit.append(full_link)
    except Exception:
        pass

    for sub_url in pages_to_visit[1:]:
        if sub_url in visited_pages:
            continue
        visited_pages.add(sub_url)
        try:
            sub_res = requests.get(sub_url, headers=HEADERS, timeout=5)
            if sub_res.status_code == 200:
                sub_soup = BeautifulSoup(sub_res.text, 'html.parser')
                s_text = extract_services(sub_soup)
                if s_text and s_text != "NotFound":
                    extracted_services_list.append(s_text)
                e, p = clean_text_data(sub_res.text)
                all_emails.update(e)
                all_phones.update(p)
        except Exception:
            pass

    all_emails_list = list(all_emails)
    primary_email = ""
    for em in all_emails_list:
        if domain_root and domain_root in em:
            primary_email = em
            break
        elif any(k in em for k in ['info@', 'support@', 'contact@', 'hello@', 'sales@']):
            primary_email = em
            break

    if not primary_email and all_emails_list:
        primary_email = all_emails_list[0]

    other_emails_list = [em for em in all_emails_list if em != primary_email]
    phones_list = list(all_phones)

    unique_services = []
    for s_block in extracted_services_list:
        for s in s_block.split(';'):
            s_clean = s.strip()
            if s_clean and s_clean not in unique_services:
                unique_services.append(s_clean)

    return {
        "Web_CompanyName": comp_name if comp_name else "NotFound",
        "companyDomain": domain,
        "web": primary_email if primary_email else "NotFound",
        "Apollo_Email": apollo_email,
        "Other_Scraped_Emails": ", ".join(other_emails_list) if other_emails_list else "NotFound",
        "Scraped_Phones": ", ".join(phones_list) if phones_list else "NotFound",
        "Main_Services": "; ".join(unique_services[:3]) if unique_services else "NotFound"
    }

@app.post("/scrape-single")
def scrape_single(url: str = Form(...)):
    result = scrape_website_logic(url)
    return result

@app.post("/scrape-bulk")
async def scrape_bulk(file: UploadFile = File(...), limit: int = Form(50)):
    contents = await file.read()
    if file.filename.endswith('.csv'):
        df = pd.read_csv(io.BytesIO(contents))
    else:
        df = pd.read_excel(io.BytesIO(contents))

    if limit > 0:
        df = df.head(limit)

    rows_list = df.to_dict(orient="records")
    results = []

    def process_row(row):
        domain = ""
        for col in row.keys():
            if 'domain' in col.lower() or 'website' in col.lower():
                domain = row[col]
                break
        if not domain and len(row) > 0:
            domain = list(row.values())[0]

        input_comp = ""
        for col in row.keys():
            if 'company' in col.lower() or 'name' in col.lower():
                input_comp = str(row[col])
                break

        apollo_email = "NotFound"
        for col in row.keys():
            if 'email' in col.lower() and 'web' not in col.lower():
                val = str(row[col]).strip()
                if val and val.lower() != "nan":
                    apollo_email = val
                    break

        return scrape_website_logic(domain, input_company_name=input_comp, apollo_email=apollo_email)

    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(process_row, row) for row in rows_list]
        @app.get("/", response_class=HTMLResponse)
def read_root():
    try:
        with open("index.html", "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return "<h2>RRM Web Scraper Backend is Live! (index.html not found in root)</h2>"
        for future in as_completed(futures):
            results.append(future.result())

    return {"results": results}
