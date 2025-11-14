import io
import logging
import random
import re
import threading
import time
import urllib.parse
import os
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from functools import wraps
import pandas as pd
import requests
import usaddress
from flask import Flask, jsonify, render_template, request, send_file
from selenium import webdriver
from selenium.common.exceptions import NoSuchElementException, TimeoutException, WebDriverException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from webdriver_manager.chrome import ChromeDriverManager
from webdriver_manager.core.os_manager import ChromeType

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
app = Flask(__name__)

SESSIONS = {}
SESSIONS_LOCK = threading.Lock()
MAX_CONCURRENT_SESSIONS = 20

def get_session(session_id):
    with SESSIONS_LOCK:
        if session_id not in SESSIONS:
            SESSIONS[session_id] = {
                "scraping_active": False, "stop_scraping_flag": False, "status_message": "Ready!",
                "link_collection_progress": 0.0, "detail_scraping_progress": 0.0,
                "link_count": 0, "scraped_count": 0, "total_to_scrape": 0,
                "results_df": pd.DataFrame(), "collected_links": [],
                "lock": threading.Lock()
            }
        return SESSIONS[session_id]
EMAIL_REGEX = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")
PHONE_REGEX = re.compile(r'(\+?\d[\d\s\-\(\)]{8,})')
USER_AGENTS = ["Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"]
DATA_DIR = "scraper_data"
if not os.path.exists(DATA_DIR): os.makedirs(DATA_DIR)

def update_status(session_id, message, link_progress=None, detail_progress=None, link_count=None, scraped_count=None, total_to_scrape=None):
    session = get_session(session_id)
    with session["lock"]:
        session["status_message"] = message
        if link_progress is not None: session["link_collection_progress"] = link_progress
        if detail_progress is not None: session["detail_scraping_progress"] = detail_progress
        if link_count is not None: session["link_count"] = link_count
        if scraped_count is not None: session["scraped_count"] = scraped_count
        if total_to_scrape is not None: session["total_to_scrape"] = total_to_scrape

def build_chrome(headless_mode=False, proxy=None):
    opts = Options()
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--disable-software-rasterizer")
    opts.add_argument("--disable-images")
    opts.add_argument("--disable-javascript")
    opts.add_argument("--disable-plugins")
    opts.add_argument("--disable-extensions")
    opts.add_argument("--page-load-strategy=eager")
    opts.add_argument("--aggressive-cache-discard")
    opts.add_argument(f"--user-agent={random.choice(USER_AGENTS)}")
    if headless_mode: opts.add_argument("--headless=new")
    if proxy: opts.add_argument(f"--proxy-server={proxy}")
    
    chrome_paths = [
        "/usr/bin/google-chrome-stable",
        "/usr/bin/google-chrome",
        "/usr/bin/chromium",
        "/usr/bin/chromium-browser"
    ]
    
    for path in chrome_paths:
        if os.path.exists(path):
            opts.binary_location = path
            break
    
    try:
        driver_path = ChromeDriverManager().install()
    except:
        try:
            driver_path = ChromeDriverManager(chrome_type=ChromeType.CHROMIUM).install()
        except:
            driver_path = "/usr/bin/chromedriver"
    
    return webdriver.Chrome(service=Service(driver_path), options=opts)

def find_emails(html):
    if not html: return []
    html = html.lower().replace('[at]','@').replace('(at)','@').replace('[dot]','.').replace('(dot)','.').replace(' at ','@').replace(' dot ','.')
    emails = EMAIL_REGEX.findall(html)
    
    invalid_extensions = ['.png', '.jpg', '.jpeg', '.gif', '.svg', '.webp', '.pdf', '.css', '.js', '.ico']
    invalid_domains = ['sentry.io', 'example.com', 'test.com', 'localhost', 'w3.org', 'schema.org', 'google.com', 'facebook.com', 'instagram.com', 'twitter.com', 'x.com', 'linkedin.com', 'youtube.com', 'maps.google.com']
    invalid_keywords = ['noreply', 'no-reply', 'donotreply', 'mailer-daemon', 'postmaster', 'webmaster', 'abuse', 'spam', 'privacy', 'support@example', 'info@example', 'contact@example']
    
    valid_emails = []
    for e in emails:
        e = e.strip().lower()
        if e.count('@') != 1: continue
        if any(ext in e for ext in invalid_extensions): continue
        
        local, domain = e.split('@')
        if len(local) < 2 or len(domain) < 4: continue
        if any(kw in local for kw in invalid_keywords): continue
        if any(d in domain for d in invalid_domains): continue
        if not '.' in domain: continue
        
        valid_emails.append(e)
    
    return sorted(set(valid_emails))
def find_phone_numbers(html): return list(set([m.strip() for m in PHONE_REGEX.findall(re.sub(r'<[^>]+>', ' ', html)) if len(re.sub(r'[^\d]','',m))>=10]))

def collect_gmaps_links(session_id, config):
    session = get_session(session_id)
    driver = build_chrome(config.get("headless_mode", True), config.get("proxy"))
    queries = [f"{config.get('general_search_term','')} {cat} {zipc}".strip() for cat in config.get('categories',[]) for zipc in config.get('zipcodes',[])]
    for i, query in enumerate(queries):
        if session["stop_scraping_flag"]: break
        driver.get(f"https://www.google.com/maps/search/{urllib.parse.quote(query)}")
        try:
            feed = WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.XPATH, '//div[@role="feed"]')))
            for _ in range(config.get("max_scrolls", 10)):
                driver.execute_script("arguments[0].scrollBy(0, 3000);", feed)
                time.sleep(0.3)
                cards = driver.find_elements(By.CSS_SELECTOR, 'a.hfpxzc')
                for c in cards[-30:]:
                    href = c.get_attribute("href")
                    if href and "/maps/place/" in href:
                        with session["lock"]:
                            if (href, query, "") not in session["collected_links"]:
                                session["collected_links"].append((href, query, ""))
                with session["lock"]: link_count = len(session["collected_links"])
                update_status(session_id, f"Query {i+1}/{len(queries)}: Found {link_count} links", link_count=link_count, link_progress=(i+1)/len(queries))
        except: pass
    driver.quit()

def extract_social_links(html):
    socials = {"Facebook": "", "Instagram": "", "Twitter": "", "LinkedIn": ""}
    patterns = {"Facebook": r'https?://(?:www\.)?facebook\.com/[^\s"\'\'<>]+', "Instagram": r'https?://(?:www\.)?instagram\.com/[^\s"\'\'<>]+', "Twitter": r'https?://(?:www\.)?(?:twitter|x)\.com/[^\s"\'\'<>]+', "LinkedIn": r'https?://(?:[a-z]{2,3}\.)?linkedin\.com/[^\s"\'\'<>]+'}
    for k, p in patterns.items():
        m = re.findall(p, html, re.IGNORECASE)
        if m: socials[k] = m[0].split('?')[0].rstrip('/')
    return socials

def scrape_website_selenium(url, headless_mode, proxy=None):
    driver = None
    try:
        driver = build_chrome(headless_mode, proxy)
        driver.set_page_load_timeout(10)
        driver.get(url)
        time.sleep(1)
        
        emails = set()
        
        # Scroll entire page
        for _ in range(5):
            driver.execute_script("window.scrollBy(0, 1000);")
            time.sleep(0.4)
            emails.update(find_emails(driver.page_source))
        
        socials = extract_social_links(driver.page_source)
        
        # Check ALL internal links for emails
        try:
            all_links = driver.find_elements(By.TAG_NAME, 'a')
            contact_keywords = ['contact', 'about', 'team', 'reach', 'connect', 'email', 'support', 'info']
            
            for link in all_links[:30]:
                try:
                    href = link.get_attribute('href')
                    text = link.text.lower()
                    
                    if href and url in href and any(kw in href.lower() or kw in text for kw in contact_keywords):
                        driver.get(href)
                        time.sleep(0.8)
                        
                        # Scroll this page too
                        for _ in range(3):
                            driver.execute_script("window.scrollBy(0, 1000);")
                            time.sleep(0.3)
                        
                        emails.update(find_emails(driver.page_source))
                        
                        if len(emails) >= 3:
                            break
                            
                        driver.back()
                        time.sleep(0.5)
                except: continue
        except: pass
        
        return list(emails), socials
    except:
        return [], {"Facebook": "", "Instagram": "", "Twitter": "", "LinkedIn": ""}
    finally:
        if driver: driver.quit()

def scrape_website_data(url, headless_mode, proxy=None):
    all_emails = set()
    socials = {"Facebook": "", "Instagram": "", "Twitter": "", "LinkedIn": ""}
    
    try:
        session = requests.Session()
        r = session.get(url, headers={"User-Agent": random.choice(USER_AGENTS)}, timeout=5)
        if r.status_code == 200:
            all_emails.update(find_emails(r.text))
            socials = extract_social_links(r.text)
            
            # Check ALL possible contact pages
            contact_pages = [
                '/contact', '/contact-us', '/contactus', '/contact_us',
                '/about', '/about-us', '/aboutus', '/about_us',
                '/team', '/our-team', '/staff',
                '/reach-us', '/get-in-touch', '/connect',
                '/support', '/help', '/info',
                '/email', '/reach', '/touch'
            ]
            
            for page in contact_pages:
                try:
                    contact_url = urllib.parse.urljoin(url, page)
                    cr = session.get(contact_url, headers={"User-Agent": random.choice(USER_AGENTS)}, timeout=3)
                    if cr.status_code == 200:
                        all_emails.update(find_emails(cr.text))
                except: continue
    except: pass
    
    # ALWAYS use Selenium for deep scraping
    selenium_emails, selenium_socials = scrape_website_selenium(url, headless_mode, proxy)
    all_emails.update(selenium_emails)
    for k, v in selenium_socials.items():
        if v and not socials.get(k): socials[k] = v
    
    return list(all_emails), socials

def extract_facebook_phone(driver):
    phones = set()
    selectors = [
        "//a[contains(@href, 'tel:')]",
        "//div[contains(text(), 'Phone')]/following-sibling::*",
        "//span[contains(text(), 'Phone')]/following-sibling::*",
        "//div[@role='button'][contains(., '+')]",
        "//span[contains(., '+1')]",
        "//span[contains(., '(')][contains(., ')')]",
    ]
    
    for sel in selectors:
        try:
            elems = driver.find_elements(By.XPATH, sel)
            for elem in elems:
                text = elem.text or elem.get_attribute('href') or ''
                if 'tel:' in text: text = text.replace('tel:', '')
                found = PHONE_REGEX.findall(text)
                phones.update(found)
        except: pass
    
    return list(phones)

def scrape_facebook_page(fb_url, headless_mode, proxy=None):
    if not fb_url: return [], []
    driver = None
    try:
        opts = Options()
        opts.add_argument("--no-sandbox")
        opts.add_argument("--disable-dev-shm-usage")
        opts.add_argument("--disable-gpu")
        opts.add_argument(f"--user-agent={random.choice(USER_AGENTS)}")
        if headless_mode: opts.add_argument("--headless=new")
        
        chrome_paths = ["/usr/bin/google-chrome-stable", "/usr/bin/google-chrome", "/usr/bin/chromium", "/usr/bin/chromium-browser"]
        for path in chrome_paths:
            if os.path.exists(path):
                opts.binary_location = path
                break
        
        try:
            driver_path = ChromeDriverManager().install()
        except:
            try:
                driver_path = ChromeDriverManager(chrome_type=ChromeType.CHROMIUM).install()
            except:
                driver_path = "/usr/bin/chromedriver"
        driver = webdriver.Chrome(service=Service(driver_path), options=opts)
        driver.set_page_load_timeout(15)
        
        all_emails = set()
        all_phones = set()
        
        pages = [
            fb_url.rstrip('/') + '/about',
            fb_url.rstrip('/') + '/about_contact_and_basic_info',
            fb_url.rstrip('/') + '/about_details',
            fb_url.rstrip('/') + '/about_profile',
            fb_url.rstrip('/'),
            fb_url.rstrip('/') + '/posts',
            fb_url.rstrip('/') + '/reviews'
        ]
        
        for page_url in pages:
            try:
                driver.get(page_url)
                time.sleep(2)
                
                # Aggressive scrolling
                for i in range(10):
                    driver.execute_script("window.scrollBy(0, 800);")
                    time.sleep(0.4)
                    
                    # Extract on every scroll
                    html = driver.page_source
                    all_emails.update(find_emails(html))
                    all_phones.update(extract_facebook_phone(driver))
                    all_phones.update(find_phone_numbers(html))
                
                # Click ALL expandable elements
                try:
                    clickable = driver.find_elements(By.XPATH, "//div[@role='button'] | //span[contains(text(), 'See')] | //span[contains(text(), 'Show')] | //span[contains(text(), 'More')]")
                    for elem in clickable[:20]:
                        try:
                            driver.execute_script("arguments[0].click();", elem)
                            time.sleep(0.5)
                            html = driver.page_source
                            all_emails.update(find_emails(html))
                            all_phones.update(extract_facebook_phone(driver))
                        except: pass
                except: pass
                
                # Final extraction
                html = driver.page_source
                all_emails.update(find_emails(html))
                all_phones.update(extract_facebook_phone(driver))
                all_phones.update(find_phone_numbers(html))
                
            except: continue
        
        return list(all_emails), list(all_phones)
    except:
        return [], []
    finally:
        if driver: driver.quit()

def get_best_email(emails):
    if not emails: return ""
    priority_domains = ['gmail.com', 'yahoo.com', 'hotmail.com', 'outlook.com']
    business_emails = [e for e in emails if not any(d in e for d in priority_domains)]
    return business_emails[0] if business_emails else emails[0]

def get_domain_matched_email(emails, website_url):
    if not emails or not website_url: return ""
    try:
        domain = urllib.parse.urlparse(website_url).netloc.replace('www.', '').split(':')[0]
        for email in emails:
            if domain in email:
                return email
    except: pass
    return get_best_email(emails)

def scrape_business_entry(gmaps_url, search_query_used, zipcode, timeout, headless_mode, proxy=None):
    driver = build_chrome(headless_mode, proxy)
    try:
        driver.get(gmaps_url)
        WebDriverWait(driver, timeout).until(EC.presence_of_element_located((By.CSS_SELECTOR, 'h1.DUwDvf, h1.lfPIob')))
        time.sleep(1)
        
        html = driver.page_source
        closure_status = "Open"
        if re.search(r'\bPermanently closed\b', html, re.IGNORECASE):
            closure_status = "Permanently Closed"
        elif re.search(r'\bTemporar(?:il)?y closed\b', html, re.IGNORECASE):
            closure_status = "Temporarily Closed"
        
        place_id = re.search(r'(ChIJ[a-zA-Z0-9_-]+)', gmaps_url).group(0) if re.search(r'(ChIJ[a-zA-Z0-9_-]+)', gmaps_url) else ""
        name = driver.find_element(By.CSS_SELECTOR, 'h1.DUwDvf, h1.lfPIob').text.strip()
        address = driver.find_element(By.CSS_SELECTOR, 'button[data-item-id="address"]').text.strip() if driver.find_elements(By.CSS_SELECTOR, 'button[data-item-id="address"]') else ""
        phone = driver.find_element(By.CSS_SELECTOR, 'button[data-item-id^="phone"]').text.strip() if driver.find_elements(By.CSS_SELECTOR, 'button[data-item-id^="phone"]') else ""
        website = driver.find_element(By.CSS_SELECTOR, 'a[data-item-id="authority"]').get_attribute("href") if driver.find_elements(By.CSS_SELECTOR, 'a[data-item-id="authority"]') else ""
        category = driver.find_element(By.CSS_SELECTOR, 'button[jsaction*="category"]').text.strip() if driver.find_elements(By.CSS_SELECTOR, 'button[jsaction*="category"]') else ""
        price = driver.find_element(By.CSS_SELECTOR, '[aria-label^="Price:"]').get_attribute('aria-label').replace('Price:', '').strip() if driver.find_elements(By.CSS_SELECTOR, '[aria-label^="Price:"]') else ""
        
        rating, reviews = "", ""
        if driver.find_elements(By.CSS_SELECTOR, 'div.F7nice'):
            txt = driver.find_element(By.CSS_SELECTOR, 'div.F7nice').text.strip()
            if m := re.search(r'(\d[.,]\d+)', txt): rating = m.group(1)
            if m := re.search(r'\((\d{1,3}(?:[.,]\d{3})*)\)', txt): reviews = re.sub(r'[.,]', '', m.group(1))
        
        city, state = "", ""
        if address:
            try:
                tagged, _ = usaddress.tag(address)
                city = tagged.get('PlaceName', '')
                state = tagged.get('StateName', '')
            except:
                parts = address.split(', ')
                if len(parts) >= 3: city = parts[-3]; state = parts[-2].split(' ')[0] if len(parts[-2].split(' ')) > 1 else ''
        
        # Scroll Google Maps page to load all content
        for _ in range(3):
            driver.execute_script("window.scrollBy(0, 500);")
            time.sleep(0.3)
        
        html = driver.page_source
        maps_emails = find_emails(html)
        
        # Click on website link in Maps to get more emails
        try:
            website_btn = driver.find_elements(By.XPATH, "//a[contains(@href, 'http') and not(contains(@href, 'google'))]")
            for btn in website_btn[:5]:
                try:
                    href = btn.get_attribute('href')
                    if href and 'facebook' not in href and 'instagram' not in href:
                        maps_emails.update(find_emails(href))
                except: pass
        except: pass
        
        maps_email = get_best_email(maps_emails)
        logging.info(f"[{name}] Google Maps emails: {maps_emails}")
        
        website_emails, socials = [], {"Facebook": "", "Instagram": "", "Twitter": "", "LinkedIn": ""}
        if website:
            website_emails, socials = scrape_website_data(website, headless_mode, proxy)
        
        all_website_emails = ", ".join(website_emails)
        website_email = get_domain_matched_email(website_emails, website)
        
        fb_emails, fb_phones = [], []
        if socials["Facebook"]:
            fb_emails, fb_phones = scrape_facebook_page(socials["Facebook"], headless_mode, proxy)
        fb_email = get_best_email(fb_emails)
        
        insta_email = ""
        
        if fb_email:
            final_email = fb_email
        elif website_email:
            final_email = website_email
        elif maps_email:
            final_email = maps_email
        else:
            final_email = ""
        
        all_phones = set([phone] + fb_phones) if phone else set(fb_phones)
        
        hours = ""
        try:
            hours_elem = driver.find_elements(By.CSS_SELECTOR, 'table.eK4R0e')
            if hours_elem: hours = hours_elem[0].text.replace('\n', '; ')
        except: pass
        
        return {
            "Search Query": search_query_used, "Category": category, "Zipcode": zipcode,
            "City": city, "State": state, "Name": name, "Address": address, 
            "Phone": phone, "Facebook Phone": ", ".join(fb_phones), "All Phones": ", ".join(sorted(all_phones)),
            "Website": website, "Facebook": socials["Facebook"], "Instagram": socials["Instagram"],
            "Twitter": socials["Twitter"], "LinkedIn": socials["LinkedIn"],
            "Google Maps Email": maps_email, "All Website Emails": all_website_emails, "Website Email": website_email, 
            "Facebook Email": fb_email, "Instagram Email": insta_email, 
            "Final Email": final_email,
            "Source": "Facebook" if fb_email and final_email == fb_email else "Website" if website_email and final_email == website_email else "Maps" if maps_email and final_email == maps_email else "Instagram" if final_email else "",
            "Maps URL": gmaps_url,
            "Place ID": place_id, "Closure Status": closure_status, "Status": "SCRAPED", "Rating": rating, "Reviews Count": reviews,
            "Price Range": price, "Cuisine Types": category, "Opening Hours": hours
        }
    except Exception as e:
        return {"Maps URL": gmaps_url, "Status": f"ERROR: {str(e)[:50]}"}
    finally:
        driver.quit()

def scrape_details(session_id, config):
    session = get_session(session_id)
    links = session["collected_links"]
    update_status(session_id, f"Scraping {len(links)} businesses...", total_to_scrape=len(links))
    results = []
    with ThreadPoolExecutor(max_workers=config.get("max_workers", 10)) as pool:
        futures = {pool.submit(scrape_business_entry, url, query, zipc, config.get("scrape_timeout", 15), config.get("headless_mode", True), config.get("proxy")): (url, query, zipc) for url, query, zipc in links}
        for i, fut in enumerate(as_completed(futures)):
            if session["stop_scraping_flag"]: break
            try: res = fut.result()
            except: res = None
            if res: results.append(res)
            update_status(session_id, f"Scraped {len(results)}/{len(links)}", detail_progress=(i+1)/len(links), scraped_count=len(results))
    with session["lock"]: session["results_df"] = pd.DataFrame(results)

def scraping_worker(session_id, config):
    session = get_session(session_id)
    try:
        with session["lock"]: 
            session["scraping_active"] = True
            session["stop_scraping_flag"] = False
            session["results_df"] = pd.DataFrame()
            session["collected_links"] = []
            session["link_count"] = 0
            session["scraped_count"] = 0
            session["total_to_scrape"] = 0
        update_status(session_id, "Collecting links...")
        collect_gmaps_links(session_id, config)
        if not session["stop_scraping_flag"] and session["collected_links"]:
            update_status(session_id, "Scraping details...")
            scrape_details(session_id, config)
            update_status(session_id, "Complete! Ready for next job.")
        else:
            update_status(session_id, "Ready for next job.")
    except Exception as e: 
        update_status(session_id, f"Error: {e}. Ready for next job.")
    finally:
        with session["lock"]: 
            session["scraping_active"] = False
            session["stop_scraping_flag"] = False

@app.route("/")
def index(): return render_template("index.html")

@app.route("/start-scraping", methods=["POST"])
def start_scraping():
    session_id = request.headers.get('X-Session-ID', 'default')
    
    with SESSIONS_LOCK:
        active_count = sum(1 for s in SESSIONS.values() if s["scraping_active"])
        if active_count >= MAX_CONCURRENT_SESSIONS:
            return jsonify({"status": "error", "message": f"Maximum {MAX_CONCURRENT_SESSIONS} concurrent sessions reached. Please wait."}), 200
    
    session = get_session(session_id)
    with session["lock"]:
        if session["scraping_active"]: 
            return jsonify({"status": "error", "message": "Your session is already scraping. Please wait."}), 200
    
    threading.Thread(target=scraping_worker, args=(session_id, request.json or {}), daemon=True).start()
    return jsonify({"status": "success", "message": "Started"})

@app.route("/status")
def status():
    session_id = request.headers.get('X-Session-ID', 'default')
    session = get_session(session_id)
    with session["lock"]: return jsonify({k: v for k, v in session.items() if k not in ["results_df", "lock"]})

@app.route("/stop-scraping", methods=["POST"])
def stop_scraping():
    session_id = request.headers.get('X-Session-ID', 'default')
    session = get_session(session_id)
    with session["lock"]: 
        session["stop_scraping_flag"] = True
        session["scraping_active"] = False
    return jsonify({"status": "success", "message": "Stopped"})

@app.route("/get-results")
def get_results():
    session_id = request.headers.get('X-Session-ID', 'default')
    session = get_session(session_id)
    with session["lock"]: return jsonify(session["results_df"].to_dict(orient="records") if not session["results_df"].empty else [])

@app.route("/download-csv")
def download_csv():
    session_id = request.headers.get('X-Session-ID') or request.args.get('session', 'default')
    session = get_session(session_id)
    with session["lock"]:
        if not session["results_df"].empty:
            buf = io.BytesIO()
            session["results_df"].to_csv(buf, index=False, encoding="utf-8-sig")
            buf.seek(0)
            return send_file(buf, as_attachment=True, download_name=f"scraped_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv", mimetype="text/csv")
    return "No data", 404

@app.route("/download-excel")
def download_excel():
    session_id = request.headers.get('X-Session-ID') or request.args.get('session', 'default')
    session = get_session(session_id)
    with session["lock"]:
        if not session["results_df"].empty:
            buf = io.BytesIO()
            with pd.ExcelWriter(buf, engine="xlsxwriter") as writer: session["results_df"].to_excel(writer, index=False, sheet_name="Data")
            buf.seek(0)
            return send_file(buf, as_attachment=True, download_name=f"scraped_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx", mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    return "No data", 404

@app.route("/save-progress", methods=["POST"])
def save_progress_route(): return jsonify({"status": "success", "message": "Saved"})

@app.route("/load-progress", methods=["POST"])
def load_progress_route(): return jsonify({"status": "success", "message": "Loaded"})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
