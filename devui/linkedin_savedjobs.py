"""
LinkedIn Saved Jobs Scraper
Scrapes your saved jobs from LinkedIn using Playwright browser automation.
Inspired by: https://github.com/pamelafox/personal-linkedin-agent
"""
import asyncio
import logging
from pathlib import Path
from typing import List, Dict, Optional
from dataclasses import dataclass, asdict

from playwright.async_api import async_playwright, Page, BrowserContext

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("linkedin_scraper")

# Auth state file path - shared across LinkedIn tools
AUTH_STATE_PATH = Path(__file__).parent.parent / "playwright" / ".auth" / "state.json"

# Blocked domains - ads, trackers, scam sites
BLOCKED_DOMAINS = [
    "monetra.co.in",
    "doubleclick.net",
    "googlesyndication.com",
    "adservice.google.com",
    "pagead2.googlesyndication.com",
    "googleadservices.com",
    "advertising.com",
    "adnxs.com",
    "adsrvr.org",
    "demdex.net",
    "krxd.net",
    "bluekai.com",
    "everesttech.net",
    "2mdn.net",
    "serving-sys.com",
    "adform.net",
    "taboola.com",
    "outbrain.com",
    "zemanta.com",
    "revcontent.com",
    "mgid.com",
    "content-ad.net",
    "popcash.net",
    "propellerads.com",
    "pushwoosh.com",
    "onesignal.com",
    "pushengage.com",
    "pushcrew.com",
    "subscribers.com",
    "notix.io",
    "push.world",
]


def should_block_request(url: str) -> bool:
    """Check if a URL should be blocked."""
    url_lower = url.lower()
    for domain in BLOCKED_DOMAINS:
        if domain in url_lower:
            return True
    # Block common ad patterns
    if any(pattern in url_lower for pattern in ['/ads/', '/adserver/', '/popunder/', '/popup/']):
        return True
    return False


async def setup_ad_blocking(page: Page):
    """Configure the page to block ads, popups, and notification requests."""
    
    # Block notification permission requests
    await page.context.grant_permissions([], origin="https://www.linkedin.com")
    
    # Intercept and block requests to ad domains
    async def handle_route(route):
        if should_block_request(route.request.url):
            logger.debug(f"Blocked: {route.request.url[:80]}")
            await route.abort()
        else:
            await route.continue_()
    
    await page.route("**/*", handle_route)
    
    # Block popups by handling new page events
    page.context.on("page", lambda new_page: asyncio.create_task(new_page.close()))
    
    logger.info("Ad-blocking enabled")


@dataclass
class SavedJob:
    """Represents a saved LinkedIn job."""
    title: str
    company: str
    location: str
    description: str
    url: str
    posted_date: str = ""
    employment_type: str = ""
    
    def to_dict(self) -> dict:
        return asdict(self)


async def ensure_logged_in(page: Page, context: BrowserContext) -> bool:
    """
    Check if logged in, prompt for manual login if not.
    Saves session state for future use (like pamelafox's approach).
    """
    await page.goto("https://www.linkedin.com/feed")
    await page.wait_for_load_state("load")
    
    # Check if redirected to login or checkpoint
    if not page.url.startswith("https://www.linkedin.com/feed"):
        logger.info("User is not logged in. Please log in manually...")
        await page.goto("https://www.linkedin.com/login")
        try:
            # Wait up to 2 minutes for user to complete login
            await page.wait_for_url("https://www.linkedin.com/feed/**", timeout=120000)
            logger.info("Login detected. Saving storage state...")
            await context.storage_state(path=str(AUTH_STATE_PATH))
            return True
        except Exception as e:
            logger.error(f"Login timeout or error: {e}")
            return False
    return True


async def get_text_from_selectors(element, selectors: List[str], default: str = "") -> str:
    """
    Try multiple selectors to extract text (like pamelafox's fallback pattern).
    Returns the first successful match.
    """
    for selector in selectors:
        try:
            el = await element.query_selector(selector)
            if el:
                text = await el.inner_text()
                if text and text.strip():
                    return text.strip()
        except:
            continue
    return default


async def get_job_card_info(card, page: Page) -> Optional[SavedJob]:
    """Extract job information from a card element with multiple selector fallbacks."""
    
    # First, try to get job title from aria-label on buttons (most reliable for saved jobs)
    title = ""
    try:
        buttons = await card.query_selector_all("button[aria-label]")
        for btn in buttons:
            aria_label = await btn.get_attribute("aria-label")
            if aria_label and ("ações em" in aria_label or "actions in" in aria_label):
                # Extract job title: "Clique para tomar mais ações em JOB TITLE"
                title = aria_label.split(" em ", 1)[-1].strip()
                # Remove trailing nbsp and whitespace
                title = title.replace("\xa0", " ").strip()
                break
    except:
        pass
    
    # Fallback to other title selectors
    if not title:
        title_selectors = [
            "span.entity-result__title-text a span[aria-hidden='true']",
            "span.entity-result__title-text span span",
            "a[href*='/jobs/view/'] span",
            "a.job-card-list__title",
            "a[href*='/jobs/view/']",
            ".job-card-container__link span",
            "strong",
            "h3 a",
        ]
        title = await get_text_from_selectors(card, title_selectors)
    
    if not title:
        return None
    
    # Company selectors (saved jobs page uses div with text-emphasis classes)
    company_selectors = [
        "div.t-14.t-black.t-normal",  # Most common on saved jobs page
        "div.t-14.t-black",  # Alternative
        ".entity-result__primary-subtitle",
        "span.entity-result__primary-subtitle",
        "span.job-card-container__primary-description",
        ".artdeco-entity-lockup__subtitle span",
    ]
    company = await get_text_from_selectors(card, company_selectors, "Unknown Company")
    
    # Location selectors (saved jobs page uses div with t-normal class)
    location_selectors = [
        "div.t-14.t-normal:not(.t-black)",  # Location div (not the company one)
        ".entity-result__secondary-subtitle",
        "span.entity-result__secondary-subtitle",
        "li.job-card-container__metadata-item",
        ".artdeco-entity-lockup__caption span",
    ]
    location = await get_text_from_selectors(card, location_selectors)
    
    # Get job URL (saved jobs page uses entity-result links)
    job_url = ""
    link_selectors = [
        "a.app-aware-link[href*='/jobs/']",
        "span.entity-result__title-text a",
        "a[href*='/jobs/view/']",
        "a[href*='/jobs/collections/']",
        "a.job-card-list__title",
        ".job-card-container__link",
    ]
    for selector in link_selectors:
        try:
            link_el = await card.query_selector(selector)
            if link_el:
                href = await link_el.get_attribute("href")
                if href:
                    job_url = href if href.startswith("http") else f"https://www.linkedin.com{href}"
                    break
        except:
            continue
    
    # Get any insight/metadata text from the card (posting date, applicants, etc.)
    insights = ""
    try:
        insight_el = await card.query_selector(".entity-result__insights")
        if insight_el:
            insights = (await insight_el.inner_text()).strip()
    except:
        pass
    
    # Note: Skipping card click to avoid navigation issues
    # Description can be fetched later by visiting the job URL directly
    description = insights  # Use insights as description placeholder
    
    # Try to get employment type and posted date from insight text
    employment_type = ""
    posted_date = ""
    if insights:
        insights_lower = insights.lower()
        if any(t in insights_lower for t in ["full-time", "part-time", "contract", "internship", "temporary"]):
            for t in ["full-time", "part-time", "contract", "internship", "temporary"]:
                if t in insights_lower:
                    employment_type = t.title()
                    break
        if any(t in insights_lower for t in ["ago", "posted", "day", "week", "month", "há"]):
            posted_date = insights
    
    return SavedJob(
        title=title,
        company=company,
        location=location,
        description=description[:5000] if description else "",
        url=job_url,
        posted_date=posted_date,
        employment_type=employment_type,
    )


async def scrape_saved_jobs(max_jobs: int = 20, headless: bool = False) -> List[SavedJob]:
    """
    Scrape saved jobs from LinkedIn using Playwright browser automation.
    
    Uses patterns from pamelafox/personal-linkedin-agent:
    - Session persistence via storage_state
    - Multiple selector fallbacks
    - Scrolling for more content
    """
    jobs: List[SavedJob] = []
    
    # Ensure auth directory exists
    AUTH_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not AUTH_STATE_PATH.exists():
        AUTH_STATE_PATH.write_text("{}")
    
    async with async_playwright() as p:
        # Launch visible browser (like pamelafox's approach)
        # WSLg now supports GUI apps
        try:
            logger.info("Launching browser...")
            browser = await p.chromium.launch(headless=headless)
            logger.info("Successfully launched browser")
        except Exception as e:
            logger.error(f"Failed to launch browser: {e}")
            logger.info("Try running: playwright install chromium")
            return jobs
        
        context = await browser.new_context(storage_state=str(AUTH_STATE_PATH))
        page = await context.new_page()
        
        try:
            # Check login status
            if not await ensure_logged_in(page, context):
                logger.error("Could not log in to LinkedIn")
                return jobs
            
            # Save session state after successful login check
            await context.storage_state(path=str(AUTH_STATE_PATH))
            
            logger.info("Navigating to saved jobs...")
            await page.goto("https://www.linkedin.com/my-items/saved-jobs/")
            await page.wait_for_load_state("load")
            await asyncio.sleep(2)
            
            # Wait for the main content region
            try:
                await page.wait_for_selector("div[role='main']", timeout=10000)
            except:
                logger.warning("Main content region not found, continuing anyway...")
            
            # DEBUG: Save screenshot and HTML to see what's on the page
            debug_dir = Path(__file__).parent / "debug"
            debug_dir.mkdir(exist_ok=True)
            await page.screenshot(path=str(debug_dir / "saved_jobs_page.png"))
            html_content = await page.content()
            (debug_dir / "saved_jobs_page.html").write_text(html_content)
            logger.info(f"Debug files saved to {debug_dir}")
            
            # Track processed jobs to avoid duplicates (like pamelafox's approach)
            processed_urls: set = set()
            consecutive_no_new_scrolls = 0
            max_no_new_scrolls = 5
            
            while len(jobs) < max_jobs:
                # Try multiple selectors for job cards (based on actual LinkedIn HTML)
                # LinkedIn uses obfuscated classes, so we use role/structure-based selectors
                job_card_selectors = [
                    "ul[role='list'] > li:has(.entity-result__insights)",  # Saved jobs page
                    "ul[role='list'] > li:has(button[aria-label*='ações'])",  # Portuguese aria-label
                    "ul[role='list'] > li:has(button[aria-label*='actions'])",  # English aria-label
                    ".workflow-results-container ul[role='list'] > li",  # Container-based
                    "ul.list-style-none > li",  # Generic list items
                    "div.reusable-search__result-container",  # Old selector
                ]
                
                job_cards = []
                for selector in job_card_selectors:
                    job_cards = await page.query_selector_all(selector)
                    if job_cards:
                        logger.debug(f"Found {len(job_cards)} cards with selector: {selector}")
                        break
                
                if not job_cards:
                    logger.warning("No job cards found on page")
                    # Log some HTML to help debug
                    try:
                        html_snippet = (await page.content())[:2000]
                        logger.debug(f"Page HTML snippet: {html_snippet}")
                    except:
                        pass
                    break
                
                logger.info(f"Found {len(job_cards)} job cards on page")
                
                new_job_found = False
                for card in job_cards:
                    if len(jobs) >= max_jobs:
                        break
                    
                    try:
                        job = await get_job_card_info(card, page)
                        if not job:
                            continue
                        
                        # Skip duplicates
                        if job.url and job.url in processed_urls:
                            continue
                        
                        if job.url:
                            processed_urls.add(job.url)
                        
                        jobs.append(job)
                        new_job_found = True
                        logger.info(f"Scraped ({len(jobs)}/{max_jobs}): {job.title} @ {job.company}")
                        
                        # Small delay between jobs
                        await asyncio.sleep(0.5)
                        
                    except Exception as e:
                        logger.warning(f"Error processing job card: {e}")
                        continue
                
                if len(jobs) >= max_jobs:
                    break
                
                # Scroll for more jobs (like pamelafox's scrolling pattern)
                if not new_job_found:
                    consecutive_no_new_scrolls += 1
                    logger.info(f"No new jobs found (attempt {consecutive_no_new_scrolls}/{max_no_new_scrolls}). Scrolling...")
                    
                    if consecutive_no_new_scrolls >= max_no_new_scrolls:
                        logger.info("Reached max scroll attempts. Stopping.")
                        break
                else:
                    consecutive_no_new_scrolls = 0
                
                # Scroll down to load more
                await page.evaluate("window.scrollBy(0, window.innerHeight * 0.9)")
                await asyncio.sleep(2)
            
            logger.info(f"\n=== Scraping Complete ===")
            logger.info(f"Total jobs scraped: {len(jobs)}")
            
        finally:
            await browser.close()
    
    return jobs


def scrape_jobs_sync(max_jobs: int = 20, headless: bool = False) -> List[Dict]:
    """Synchronous wrapper for use in Streamlit and other sync contexts."""
    jobs = asyncio.run(scrape_saved_jobs(max_jobs=max_jobs, headless=headless))
    return [job.to_dict() for job in jobs]


async def fetch_job_description(job_url: str, headless: bool = False) -> str:
    """
    Fetch the full job description by visiting the job detail page.
    Called when user clicks on a specific job to get more details.
    Uses visible browser by default since LinkedIn blocks headless.
    """
    if not job_url:
        return ""
    
    # Ensure auth directory exists
    AUTH_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not AUTH_STATE_PATH.exists():
        AUTH_STATE_PATH.write_text("{}")
    
    async with async_playwright() as p:
        try:
            # Use visible browser - LinkedIn often blocks headless
            browser = await p.chromium.launch(headless=headless)
            context = await browser.new_context(storage_state=str(AUTH_STATE_PATH))
            page = await context.new_page()
            
            logger.info(f"Fetching job details from: {job_url}")
            # Set longer timeout for slow connections
            page.set_default_timeout(60000)
            
            await page.goto(job_url, wait_until="domcontentloaded")
            await asyncio.sleep(4)  # Wait for dynamic content to render
            
            # Wait for the expandable text box which contains job description
            try:
                await page.wait_for_selector("span[data-testid='expandable-text-box'], #job-details", timeout=15000)
            except:
                logger.warning("Job description container not found, trying anyway...")
            
            # Click "Show more" / "...more" / "...mais" button to expand full description
            # LinkedIn truncates long descriptions and requires clicking to see full text
            expand_button_selectors = [
                "button[data-testid='expandable-text-button']",  # Main expand button
                "button:has-text('more')",
                "button:has-text('mais')",
                "button:has-text('Show more')",
                "button:has-text('Ver mais')",
                ".jobs-description button[aria-label*='more']",
            ]
            
            for btn_selector in expand_button_selectors:
                try:
                    expand_btn = await page.query_selector(btn_selector)
                    if expand_btn:
                        await expand_btn.click()
                        logger.info(f"Clicked expand button: {btn_selector}")
                        await asyncio.sleep(1)  # Wait for content to expand
                        break
                except Exception as e:
                    logger.debug(f"Could not click expand button {btn_selector}: {e}")
                    continue
            
            # DEBUG: Save HTML for analysis (after expanding)
            debug_dir = Path(__file__).parent / "debug"
            debug_dir.mkdir(exist_ok=True)
            await page.screenshot(path=str(debug_dir / "job_detail.png"))
            html_content = await page.content()
            (debug_dir / "job_detail.html").write_text(html_content)
            logger.info(f"Debug files saved to {debug_dir}")
            
            # Try multiple description selectors based on actual LinkedIn HTML
            description = ""
            desc_selectors = [
                # Primary: The expandable text box used for job description (found in HTML)
                "span[data-testid='expandable-text-box']",
                # Secondary: Try to find section after "About the job" / "Sobre a vaga" heading
                "h2:has-text('Sobre a vaga') ~ p span[data-testid='expandable-text-box']",
                "h2:has-text('About the job') ~ p span[data-testid='expandable-text-box']",
                # Older selectors that might still work
                "#job-details",
                "div.jobs-description__content",
                "article.jobs-description",
                ".jobs-box__html-content",
            ]
            
            for selector in desc_selectors:
                try:
                    desc_el = await page.query_selector(selector)
                    if desc_el:
                        text = (await desc_el.inner_text()).strip()
                        if text and len(text) > 100:  # Ensure it's actual content
                            description = text
                            logger.info(f"Found description with selector: {selector} ({len(text)} chars)")
                            break
                except:
                    continue
            
            # If still no description, try getting text from the "Sobre a vaga" section specifically
            if not description:
                try:
                    # Find all expandable text boxes and get the longest one (usually the description)
                    all_text_boxes = await page.query_selector_all("span[data-testid='expandable-text-box']")
                    longest_text = ""
                    for box in all_text_boxes:
                        text = (await box.inner_text()).strip()
                        if len(text) > len(longest_text):
                            longest_text = text
                    if len(longest_text) > 200:
                        description = longest_text
                        logger.info(f"Used longest expandable text box ({len(longest_text)} chars)")
                except:
                    pass
            
            # Last resort: Try main content area
            if not description:
                try:
                    main_content = await page.query_selector("main, div[role='main']")
                    if main_content:
                        text = (await main_content.inner_text()).strip()
                        if len(text) > 500:
                            description = text
                            logger.info(f"Used main content fallback ({len(text)} chars)")
                except:
                    pass
            
            # Also try to get additional job details (company, type, etc.)
            details = []
            try:
                # Job insights (employment type, level, etc.)
                insight_els = await page.query_selector_all("li.job-details-jobs-unified-top-card__job-insight")
                for el in insight_els:
                    text = (await el.inner_text()).strip()
                    if text and len(text) > 2:
                        details.append(text)
            except:
                pass
            
            if details:
                description = " | ".join(details[:5]) + "\n\n" + description
            
            await browser.close()
            return description[:8000]  # Limit length
            
        except Exception as e:
            logger.error(f"Error fetching job description: {e}")
            return ""


def fetch_job_description_sync(job_url: str, headless: bool = False) -> str:
    """Synchronous wrapper for fetching job description."""
    return asyncio.run(fetch_job_description(job_url, headless=headless))


if __name__ == "__main__":
    # Test the scraper
    import argparse
    
    parser = argparse.ArgumentParser(description="Scrape LinkedIn saved jobs")
    parser.add_argument("--max-jobs", type=int, default=10, help="Max jobs to scrape")
    parser.add_argument("--headless", action="store_true", help="Run in headless mode")
    args = parser.parse_args()
    
    jobs = scrape_jobs_sync(max_jobs=args.max_jobs, headless=args.headless)
    print(f"\nScraped {len(jobs)} jobs:")
    for job in jobs:
        print(f"  - {job['title']} @ {job['company']}")
