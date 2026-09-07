"""
linkedin_urls.py — Builds search URLs for manual outreach research.

Generates links only. Nothing here fetches, scrapes, or automates LinkedIn —
Juhi clicks these herself. LinkedIn's currentCompany facet needs numeric
company IDs we don't have, so these use quoted keyword search: less precise,
but one click and zero automation.
"""

from urllib.parse import quote_plus

PEOPLE_SEARCH = "https://www.linkedin.com/search/results/people/?keywords="

PRODUCT_LEADER_TITLES = (
    '"Head of Product" OR "Director of Product" OR "VP Product" '
    'OR "Group Product Manager" OR "Principal Product Manager"'
)


def people_search_url(company: str, title_filter: str = PRODUCT_LEADER_TITLES) -> str:
    """People at a company matching a title pattern."""
    return PEOPLE_SEARCH + quote_plus(f'"{company}" ({title_filter})')


def school_search_url(company: str, school: str) -> str:
    """Alumni of a school currently at a company — the warmest cold route."""
    return PEOPLE_SEARCH + quote_plus(f'"{company}" "{school}"')


def company_people_url(slug: str) -> str:
    """A company's own LinkedIn people directory, if the slug is known."""
    return f"https://www.linkedin.com/company/{slug}/people/"


def news_search_url(company: str, days: int = 30) -> str:
    """
    Recent news about a company. Opened by hand during the send block —
    no automated fetch, so nothing can go stale or wrong in a draft.
    """
    query = f'"{company}" (funding OR launch OR product OR acquisition) when:{days}d'
    return "https://news.google.com/search?q=" + quote_plus(query)


def research_links(company: str, schools=("Indian School of Business", "Delhi Technological University")) -> dict:
    """Every research link for one company, ready to write into a Targets row."""
    links = {
        "linkedin_people_url": people_search_url(company),
        "news_search_url": news_search_url(company),
    }
    keys = ["linkedin_isb_url", "linkedin_dtu_url"]
    for key, school in zip(keys, schools):
        links[key] = school_search_url(company, school)
    return links
