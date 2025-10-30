"""Scraper for PokemonDB gym leaders, Elite Four, champions, and rivals.

This script walks the PokemonDB game index, finds the trainer overview page for
each game, and then extracts the trainer rosters. The resulting JSON is grouped
by game title, with trainer data grouped by their section (e.g. Gym Leaders,
Elite Four).

Because PokemonDB actively rate-limits traffic, the scraper intentionally pauses
between requests. Use a personal user agent string (override with --user-agent)
when running it outside of development to respect the site's terms of use.
"""
from __future__ import annotations

import argparse
import json
import time
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from bs4.element import NavigableString, Tag

BASE_URL = "https://pokemondb.net"
GAME_INDEX_PATH = "/game"
TRAINER_PATH_SUFFIX = "/gymleaders-elitefour"
DEFAULT_DELAY = 1.0
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0 Safari/537.36"
)


@dataclass
class TeamEntry:
    """A single team listing for a trainer."""

    title: Optional[str]
    columns: List[str]
    rows: List[dict]


@dataclass
class Trainer:
    """Structured representation of a trainer on a trainer overview page."""

    name: str
    subtitle: Optional[str]
    description: Optional[str]
    teams: List[TeamEntry]


def clean_text(text: str) -> str:
    """Collapse whitespace and strip extraneous footnote markers."""

    collapsed = " ".join(text.split())
    return collapsed.replace("[note 1]", "").strip()


def cell_text(cell: Tag) -> str:
    """Extract readable text from a table cell."""

    if cell.find("ul"):
        items = [clean_text(li.get_text(" ", strip=True)) for li in cell.find_all("li")]
        return "; ".join(item for item in items if item)
    if cell.find("br"):
        parts = [clean_text(part) for part in cell.get_text("\n", strip=True).split("\n")]
        return "; ".join(part for part in parts if part)
    return clean_text(cell.get_text(" ", strip=True))


def parse_table(table: Tag) -> TeamEntry:
    """Convert a PokemonDB roster table to a structured representation."""

    headers: List[str] = []
    thead = table.find("thead")
    if thead:
        headers = [clean_text(th.get_text(" ", strip=True)) for th in thead.find_all("th")]
    tbody = table.find("tbody") or table
    rows = []
    for row in tbody.find_all("tr", recursive=False):
        entries = row.find_all(["td", "th"], recursive=False)
        row_data = {}
        for idx, entry in enumerate(entries):
            key = headers[idx] if idx < len(headers) else f"Column {idx + 1}"
            row_data[key] = cell_text(entry)
        if row_data:
            rows.append(row_data)
    return TeamEntry(title=None, columns=headers, rows=rows)


def parse_trainer_container(container: Tag) -> Trainer:
    """Parse a single trainer card from the trainer overview page."""

    title_tag = container.find(["h3", "h4", "h5"])
    if not title_tag:
        raise ValueError("Trainer container missing title heading")

    subtitle_tag = title_tag.find("small")
    subtitle = clean_text(subtitle_tag.get_text(" ", strip=True)) if subtitle_tag else None
    if subtitle_tag:
        subtitle_tag.extract()
    name = clean_text(title_tag.get_text(" ", strip=True))

    description_parts = []
    for paragraph in container.find_all("p", recursive=False):
        text = clean_text(paragraph.get_text(" ", strip=True))
        if text:
            description_parts.append(text)
    description = "\n".join(description_parts) if description_parts else None

    teams: List[TeamEntry] = []
    current_title: Optional[str] = None
    for child in container.children:
        if isinstance(child, NavigableString):
            continue
        if child.name in {"h4", "h5"}:
            current_title = clean_text(child.get_text(" ", strip=True))
            continue
        if child.name == "table":
            team = parse_table(child)
            team.title = current_title
            teams.append(team)
            current_title = None
    return Trainer(name=name, subtitle=subtitle, description=description, teams=teams)


def _has_heading(tag: Tag) -> bool:
    return bool(tag.find(["h3", "h4", "h5"]))


def _class_contains_grid_col(value: object) -> bool:
    if not value:
        return False
    if isinstance(value, str):
        return "grid-col" in value
    if isinstance(value, (list, tuple, set)):
        return any("grid-col" in item for item in value if isinstance(item, str))
    return False


def _looks_like_trainer_card(tag: Tag) -> bool:
    if not isinstance(tag, Tag):
        return False
    if tag.name in {"table", "tbody", "thead", "tr"}:
        return False
    if not tag.find("table"):
        return False
    if not _has_heading(tag):
        return False
    return True


def _find_trainer_cards(node: Tag) -> List[Tag]:
    cards: List[Tag] = []
    if not isinstance(node, Tag):
        return cards
    if node.name == "div":
        classes = set(node.get("class", []))
        if "grid-row" in classes or "grid" in classes or "row" in classes:
            cards.extend(
                child
                for child in node.find_all(
                    "div",
                    class_=_class_contains_grid_col,
                    recursive=False,
                )
                if _looks_like_trainer_card(child)
            )
            if cards:
                return cards
    for candidate in node.find_all(_looks_like_trainer_card):
        parent = candidate.find_parent(
            lambda ancestor: isinstance(ancestor, Tag)
            and ancestor is not candidate
            and _looks_like_trainer_card(ancestor)
        )
        if parent is not None:
            continue
        cards.append(candidate)
    return cards


def extract_section_trainers(section_heading: Tag) -> List[Trainer]:
    """Extract all trainer entries under a section heading."""

    trainers: List[Trainer] = []
    seen_cards: set[int] = set()

    sibling = section_heading.find_next_sibling()
    while sibling and not (isinstance(sibling, Tag) and sibling.name == "h2"):
        if isinstance(sibling, Tag):
            for card in _find_trainer_cards(sibling):
                identity = id(card)
                if identity in seen_cards:
                    continue
                seen_cards.add(identity)
                try:
                    trainer = parse_trainer_container(card)
                except ValueError:
                    continue
                if trainer.teams:
                    trainers.append(trainer)
        sibling = sibling.find_next_sibling()
    return trainers


def parse_game_page(html: str) -> List[dict]:
    """Parse a PokemonDB game trainer page into sectioned trainer data."""

    soup = BeautifulSoup(html, "html.parser")
    sections = []
    for heading in soup.find_all("h2"):
        section_name = clean_text(heading.get_text(" ", strip=True))
        trainers = extract_section_trainers(heading)
        if trainers:
            sections.append(
                {
                    "section": section_name,
                    "trainers": [
                        {
                            "name": trainer.name,
                            "subtitle": trainer.subtitle,
                            "description": trainer.description,
                            "teams": [
                                {
                                    "title": team.title,
                                    "columns": team.columns,
                                    "rows": team.rows,
                                }
                                for team in trainer.teams
                            ],
                        }
                        for trainer in trainers
                    ],
                }
            )
    return sections


def extract_game_links(index_html: str) -> List[tuple[str, str]]:
    """Return a list of (game_name, trainer_page_url) pairs from the index page."""

    soup = BeautifulSoup(index_html, "html.parser")
    seen = set()
    game_links: List[tuple[str, str]] = []
    for anchor in soup.find_all("a", href=True):
        href = anchor["href"].strip()
        if not href.endswith(TRAINER_PATH_SUFFIX):
            continue
        url = urljoin(BASE_URL, href)
        if url in seen:
            continue
        seen.add(url)
        game_name = clean_text(anchor.get_text(" ", strip=True)) or href.strip("/").split("/")[0]
        game_links.append((game_name, url))
    return game_links


def scrape_trainer_data(
    session: requests.Session,
    delay: float,
    game_filter: Optional[Iterable[str]] = None,
) -> OrderedDict[str, dict]:
    """Scrape trainer data for every PokemonDB game page."""

    index_url = urljoin(BASE_URL, GAME_INDEX_PATH)
    try:
        response = session.get(index_url, timeout=30)
        response.raise_for_status()
    except requests.RequestException as exc:
        raise RuntimeError(f"Unable to load PokemonDB game index: {exc}") from exc
    game_links = extract_game_links(response.text)

    if game_filter:
        desired = {name.lower() for name in game_filter}
        game_links = [item for item in game_links if item[0].lower() in desired]

    results: OrderedDict[str, dict] = OrderedDict()
    for game_name, url in game_links:
        print(f"Fetching trainer data for {game_name}...", flush=True)
        try:
            page_response = session.get(url, timeout=30)
            page_response.raise_for_status()
        except requests.RequestException as exc:
            print(f"  Failed to download {url}: {exc}")
            continue
        sections = parse_game_page(page_response.text)
        results[game_name] = {"source": url, "sections": sections}
        if delay:
            time.sleep(delay)
    return results


def build_session(user_agent: str) -> requests.Session:
    session = requests.Session()
    session.headers.update({"User-Agent": user_agent, "Referer": BASE_URL})
    return session


def main() -> None:
    parser = argparse.ArgumentParser(description="Scrape trainer rosters from PokemonDB")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).with_name("pokemondb_trainers.json"),
        help="Where to write the resulting JSON data.",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=DEFAULT_DELAY,
        help="Delay (in seconds) between requests to avoid hammering the server.",
    )
    parser.add_argument(
        "--user-agent",
        default=DEFAULT_USER_AGENT,
        help="Custom user agent string to send with requests.",
    )
    parser.add_argument(
        "--game",
        action="append",
        help="Limit scraping to specific game names from the index page.",
    )
    args = parser.parse_args()

    session = build_session(args.user_agent)
    data = scrape_trainer_data(session=session, delay=args.delay, game_filter=args.game)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)

    print(f"Saved trainer data for {len(data)} games to {args.output}")


if __name__ == "__main__":
    main()
