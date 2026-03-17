from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List
import asyncio

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Request Model ---

class Source(BaseModel):
    id: str
    name: str
    url: str
    count: int = 0
    detected: bool = False
    status: str = "unverified"

class ScrapeRequest(BaseModel):
    sources: List[Source]

# --- Health Check ---

@app.get("/")
def health_check():
    return { "status": "ok", "service": "ProductPulse Scraper" }

# --- Main Scrape Endpoint ---

@app.post("/scrape")
async def scrape_reviews(body: ScrapeRequest):
    all_reviews = []

    for source in body.sources:
        if source.status != "verified":
            continue
        try:
            if source.name == "Play Store":
                app_id = extract_play_store_id(source.url)
                if app_id:
                    reviews = await asyncio.to_thread(scrape_play_store, app_id)
                    all_reviews.extend([{**r, "source": "play_store"} for r in reviews])

            elif source.name == "App Store":
                app_id = extract_app_store_id(source.url)
                if app_id:
                    reviews = await asyncio.to_thread(scrape_app_store, app_id)
                    all_reviews.extend([{**r, "source": "app_store"} for r in reviews])

            elif source.name == "Trustpilot":
                domain = extract_trustpilot_domain(source.url)
                if domain:
                    reviews = await asyncio.to_thread(scrape_trustpilot, domain)
                    all_reviews.extend([{**r, "source": "trustpilot"} for r in reviews])

        except Exception as e:
            print(f"[Scrape] Failed for {source.name}: {e}")

    metrics = compute_metrics(all_reviews)
    return { "reviews": all_reviews, "metrics": metrics, "total": len(all_reviews) }

# --- ID Extractors ---

def extract_play_store_id(url: str):
    import re
    match = re.search(r'id=([a-zA-Z0-9._]+)', url)
    return match.group(1) if match else None

def extract_app_store_id(url: str):
    import re
    match = re.search(r'/id(\d+)', url)
    return match.group(1) if match else None

def extract_trustpilot_domain(url: str):
    import re
    match = re.search(r'trustpilot\.com/review/([^/?]+)', url)
    return match.group(1) if match else None

# --- Scrapers ---

def scrape_play_store(app_id: str):
    try:
        from google_play_scraper import reviews, Sort
        result, _ = reviews(
            app_id,
            lang='en',
            country='us',
            sort=Sort.NEWEST,
            count=1000
        )
        return [
            {
                "author": r.get("userName", "Anonymous"),
                "rating": r.get("score", 0),
                "review_text": r.get("content", ""),
                "review_date": r.get("at").strftime("%Y-%m-%d") if r.get("at") else ""
            }
            for r in result
        ]
    except Exception as e:
        print(f"[Play Store] Failed: {e}")
        return []

def scrape_app_store(app_id: str):
    try:
        from app_store_scraper import AppStore
        # We need the app name — fetch it from the lookup API first
        import requests
        lookup = requests.get(f"https://itunes.apple.com/lookup?id={app_id}").json()
        results = lookup.get("results", [])
        if not results:
            return []
        app_name = results[0].get("trackName", "app")
        country = results[0].get("country", "us").lower() or "us"

        scraper = AppStore(country="us", app_name=app_name, app_id=app_id)
        scraper.review(how_many=1000)

        return [
            {
                "author": r.get("userName", "Anonymous"),
                "rating": r.get("rating", 0),
                "review_text": r.get("review", ""),
                "review_date": r.get("date").strftime("%Y-%m-%d") if r.get("date") else ""
            }
            for r in scraper.reviews
        ]
    except Exception as e:
        print(f"[App Store] Failed: {e}")
        return []

def scrape_trustpilot(domain: str):
    try:
        import requests
        from bs4 import BeautifulSoup

        reviews = []
        for page in range(1, 6):  # fetch up to 5 pages = ~100 reviews
            url = f"https://www.trustpilot.com/review/{domain}?page={page}"
            res = requests.get(url, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            }, timeout=10)
            if not res.ok:
                break

            soup = BeautifulSoup(res.text, "html.parser")
            review_cards = soup.select("[data-service-review-card-paper]")

            if not review_cards:
                break

            for card in review_cards:
                try:
                    rating_el = card.select_one("[data-service-review-rating]")
                    rating = int(rating_el["data-service-review-rating"]) if rating_el else 0
                    text_el = card.select_one("[data-service-review-text-typography]")
                    text = text_el.get_text(strip=True) if text_el else ""
                    date_el = card.select_one("time")
                    date = date_el["datetime"][:10] if date_el else ""
                    author_el = card.select_one("[data-consumer-name-typography]")
                    author = author_el.get_text(strip=True) if author_el else "Anonymous"
                    reviews.append({
                        "author": author,
                        "rating": rating,
                        "review_text": text,
                        "review_date": date
                    })
                except Exception:
                    continue

        return reviews
    except Exception as e:
        print(f"[Trustpilot] Failed: {e}")
        return []

# --- Metric Computation ---

def compute_metrics(reviews: list):
    if not reviews:
        return None

    total = len(reviews)

    avg_rating = sum(r.get("rating", 0) for r in reviews) / total
    overall_satisfaction = {
        "value": round((avg_rating / 5) * 100),
        "confidence": min(95, 40 + total // 10),
        "dataPoints": total
    }

    success_keywords = ["easy", "worked", "successful", "simple", "smooth", "great", "love", "perfect"]
    fail_keywords = ["couldn't", "confusing", "gave up", "broken", "failed", "doesn't work", "useless", "terrible"]

    success_count = sum(
        1 for r in reviews
        if any(k in (r.get("review_text") or "").lower() for k in success_keywords)
    )

    task_completion_value = round((success_count / total) * 100)
    task_completion = {
        "value": task_completion_value,
        "confidence": min(90, 35 + total // 10),
        "dataPoints": total
    }

    abandonment = {
        "value": 100 - task_completion_value,
        "confidence": task_completion["confidence"],
        "dataPoints": total
    }

    promoters = sum(1 for r in reviews if r.get("rating") == 5)
    detractors = sum(1 for r in reviews if r.get("rating", 0) <= 3)
    nps_value = round(((promoters - detractors) / total) * 100)

    nps = {
        "value": max(-100, min(100, nps_value)),
        "confidence": min(95, 40 + total // 10),
        "dataPoints": total
    }

    return {
        "overallSatisfaction": overall_satisfaction,
        "taskCompletion": task_completion,
        "abandonmentRate": abandonment,
        "nps": nps
    }
