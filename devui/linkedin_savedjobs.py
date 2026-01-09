"""
LinkedIn Saved Jobs Scraper
Scrapes your saved jobs from LinkedIn using Playwright
"""
import asyncio
import logging
from pathlib import Path
from typing import List, Dict
from dataclasses import dataclass, asdict

from playwright.async_api import async_playwright, Page

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("linkedin_scraper")

# Auth state file path
AUTH_STATE_PATH = Path(__file__).parent.parent / "playwright" / ".auth" / "state.json"


@dataclass
class SavedJob:
    """Represents a saved LinkedIn job."""
    title: str
    company: str
    location: str
    description: str
    url: str
    
    def to_dict(self) -> dict:
        return asdict(self)


async def ensure_logged_in(page: Page) -> bool:
    """Check if logged in, prompt for login if not."""
    await page.goto("https://www.linkedin.com/feed")
    await page.wait_for_load_state("load")
    
    if "login" in page.url or "checkpoint" in page.url:
        logger.info("Not logged in. Please log in manually...")
        await page.goto("https://www.linkedin.com/login")
        try:
            await page.wait_for_url("**/feed/**", timeout=120000)
            logger.info("Login successful!")
            return True
        except:
            logger.error("Login timeout")
            return False
    return True


async def scrape_saved_jobs(max_jobs: int = 20, headless: bool = True) -> List[SavedJob]:
    """Scrape saved jobs from LinkedIn."""
    jobs: List[SavedJob] = []
    
    AUTH_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not AUTH_STATE_PATH.exists():
        AUTH_STATE_PATH.write_text("{}")
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=headless,
            args=['--no-sandbox', '--disable-gpu', '--disable-dev-shm-usage']
        )
        context = await browser.new_context(storage_state=str(AUTH_STATE_PATH))
        page = await context.new_page()
        
        try:
            if not await ensure_logged_in(page):
                return jobs
            
            await context.storage_state(path=str(AUTH_STATE_PATH))
            
            logger.info("Navigating to saved jobs...")
            await page.goto("https://www.linkedin.com/my-items/saved-jobs/")
            await page.wait_for_load_state("load")
            await asyncio.sleep(2)
            
            # Find job cards
            job_cards = await page.query_selector_all("div.reusable-search__result-container")
            if not job_cards:
                job_cards = await page.query_selector_all("ul.scaffold-layout__list-container > li")
            
            logger.info(f"Found {len(job_cards)} job cards")
            
            processed = 0
            for card in job_cards:
                if processed >= max_jobs:
                    break
                
                try:
                    title_el = await card.query_selector("a.job-card-list__title, a[href*='/jobs/view/']")
                    company_el = await card.query_selector("span.job-card-container__primary-description")
                    location_el = await card.query_selector("li.job-card-container__metadata-item")
                    
                    if not title_el:
                        continue
                    
                    title = (await title_el.inner_text()).strip()
                    company = (await company_el.inner_text()).strip() if company_el else "Unknown"
                    location = (await location_el.inner_text()).strip() if location_el else ""
                    
                    link_el = await card.query_selector("a[href*='/jobs/view/']")
                    job_url = ""
                    if link_el:
                        job_url = await link_el.get_attribute("href") or ""
                        if job_url and not job_url.startswith("http"):
                            job_url = f"https://www.linkedin.com{job_url}"
                    
                    await card.click()
                    await asyncio.sleep(1.5)
                    
                    desc_el = await page.query_selector("div.jobs-description__content, article.jobs-description")
                    description = (await desc_el.inner_text()).strip() if desc_el else ""
                    
                    if title:
                        jobs.append(SavedJob(
                            title=title, company=company, location=location,
                            description=description[:5000], url=job_url
                        ))
                        processed += 1
                        logger.info(f"Scraped: {title} @ {company}")
                
                except Exception as e:
                    logger.warning(f"Error: {e}")
                    continue
            
        finally:
            await browser.close()
    
    return jobs


def scrape_jobs_sync(max_jobs: int = 20) -> List[Dict]:
    """Synchronous wrapper."""
    jobs = asyncio.run(scrape_saved_jobs(max_jobs=max_jobs))
    return [job.to_dict() for job in jobs]
