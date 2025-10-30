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
import re
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
TRAINER_PATH_SUFFIX = "/gymleaders-elitefour"
DEFAULT_DELAY = 1.5
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

# Known game slugs on PokemonDB
# Format: (display_name, slug, custom_path_suffix)
# If custom_path_suffix is None, uses TRAINER_PATH_SUFFIX
KNOWN_GAMES = [
    ("Red/Blue", "red-blue", None),
    ("Yellow", "yellow", None),
    ("Gold/Silver", "gold-silver", None),
    ("Crystal", "crystal", None),
    ("Ruby/Sapphire", "ruby-sapphire", None),
    ("Emerald", "emerald", None),
    ("FireRed/LeafGreen", "firered-leafgreen", None),
    ("Diamond/Pearl", "diamond-pearl", None),
    ("Platinum", "platinum", None),
    ("HeartGold/SoulSilver", "heartgold-soulsilver", None),
    ("Black/White", "black-white", None),
    ("Black 2/White 2", "black-white-2", None),
    ("X/Y", "x-y", None),
    ("Omega Ruby/Alpha Sapphire", "omega-ruby-alpha-sapphire", None),
    ("Sun/Moon", "sun-moon", "/kahunas-elitefour"),
    ("Ultra Sun/Ultra Moon", "ultra-sun-ultra-moon", "/kahunas-elitefour"),
    ("Let's Go Pikachu/Eevee", "lets-go-pikachu-eevee", None),
    ("Sword/Shield", "sword-shield", "/gymleaders"),
    ("Brilliant Diamond/Shining Pearl", "brilliant-diamond-shining-pearl", None),
    ("Scarlet/Violet", "scarlet-violet", None),
]


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
    
    # If no thead, check first row for headers
    if not headers:
        first_row = table.find("tr")
        if first_row:
            potential_headers = first_row.find_all("th")
            if potential_headers:
                headers = [clean_text(th.get_text(" ", strip=True)) for th in potential_headers]
    
    tbody = table.find("tbody") or table
    rows = []
    for row in tbody.find_all("tr", recursive=False):
        # Skip header rows
        if row.find_parent("thead"):
            continue
        if all(cell.name == "th" for cell in row.find_all(["td", "th"])):
            continue
            
        entries = row.find_all(["td", "th"], recursive=False)
        if not entries:
            continue
            
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


def parse_trainer_card(card: Tag) -> dict:
    """Parse a trainer infocard to extract name and Pokemon team.
    
    Returns a dict with 'title' (team variation name) and 'pokemon_list'.
    """
    
    # Find trainer name in span.ent-name within the trainer-head
    trainer_head = card.find("span", class_="trainer-head")
    title = None
    
    if trainer_head:
        # Get the full text of the trainer head (includes name + variation)
        full_text = clean_text(trainer_head.get_text(" ", strip=True))
        
        # The ent-name span contains just the trainer name
        name_elem = trainer_head.find("span", class_="ent-name")
        trainer_name = clean_text(name_elem.get_text(" ", strip=True)) if name_elem else "Unknown"
        
        # Check if there's variation text after the name
        # e.g., full_text might be "Blue(Bulbasaur as starter)Mixed types"
        # and trainer_name is just "Blue"
        if name_elem and len(full_text) > len(trainer_name):
            # Get the part after the name
            remainder = full_text[len(trainer_name):].strip()
            # Check if it starts with a parenthesis (variation)
            if remainder.startswith("(") and ")" in remainder:
                # Extract the variation
                match = re.match(r'^\((.+?)\)', remainder)
                if match:
                    title = match.group(1)
        
        # Get subtitle (badge name and type specialty)
        subtitle_parts = []
        small_tag = trainer_head.find("small")
        if small_tag:
            for text in small_tag.stripped_strings:
                if "type Pokémon" not in text and "Badge" in text:
                    subtitle_parts.append(text)
        subtitle = " - ".join(subtitle_parts) if subtitle_parts else None
    else:
        trainer_name = "Unknown"
        subtitle = None
    
    # Extract Pokemon data - look for div.trainer-pkmn elements
    pokemon_divs = card.find_all("div", class_="trainer-pkmn")
    
    pokemon_list = []
    for pkmn_div in pokemon_divs:
        pkmn_data = {}
        
        # Get the data span
        data_span = pkmn_div.find("span", class_="infocard-lg-data")
        if not data_span:
            continue
        
        # Get Pokemon name from the ent-name link
        name_link = data_span.find("a", class_="ent-name")
        if name_link:
            pkmn_data["Pokemon"] = clean_text(name_link.get_text(" ", strip=True))
        
        # Get Pokedex number
        number_elem = data_span.find("small")
        if number_elem:
            number_text = clean_text(number_elem.get_text(" ", strip=True))
            if number_text.startswith("#"):
                pkmn_data["Number"] = number_text
        
        # Get level - find the small tag containing "Level"
        for small in data_span.find_all("small"):
            text = clean_text(small.get_text(" ", strip=True))
            if text.startswith("Level"):
                level_match = re.search(r'Level\s+(\d+)', text, re.IGNORECASE)
                if level_match:
                    pkmn_data["Level"] = level_match.group(1)
                break
        
        # Get types
        type_links = data_span.find_all("a", class_=lambda c: c and "itype" in c)
        if type_links:
            types = [clean_text(t.get_text(" ", strip=True)) for t in type_links]
            pkmn_data["Type"] = " / ".join(types)
        
        if pkmn_data:
            pokemon_list.append(pkmn_data)
    
    return {
        "name": trainer_name,
        "subtitle": subtitle,
        "title": title,
        "pokemon_list": pokemon_list,
    }


def parse_game_page(html: str) -> List[dict]:
    """Parse a PokemonDB game trainer page into sectioned trainer data."""

    soup = BeautifulSoup(html, "html.parser")
    sections = []
    
    # The structure is: H2 (section like "Gym #1, Pewter City")
    # followed by one or more div.infocard-list-trainer-pkmn containing trainer data
    # Multiple divs = different forms/variations of the same trainer
    
    for h2 in soup.find_all("h2"):
        section_name = clean_text(h2.get_text(" ", strip=True))
        
        # Find ALL infocard divs that follow this heading (until next h2)
        trainer_cards = []
        current = h2.find_next_sibling()
        
        while current and not (isinstance(current, Tag) and current.name == "h2"):
            if isinstance(current, Tag):
                if current.name == "div" and "infocard-list-trainer-pkmn" in current.get("class", []):
                    trainer_cards.append(current)
                # Also check for h3 which might indicate team variations
                elif current.find("div", class_="infocard-list-trainer-pkmn"):
                    # Sometimes the cards are nested
                    trainer_cards.extend(current.find_all("div", class_="infocard-list-trainer-pkmn"))
            current = current.find_next_sibling()
        
        if trainer_cards:
            # Group cards by trainer name
            trainer_dict = {}
            
            for card in trainer_cards:
                try:
                    card_data = parse_trainer_card(card)
                    if not card_data["pokemon_list"]:
                        continue
                    
                    trainer_name = card_data["name"]
                    
                    # Initialize trainer if not seen
                    if trainer_name not in trainer_dict:
                        trainer_dict[trainer_name] = {
                            "name": trainer_name,
                            "subtitle": card_data["subtitle"],
                            "description": None,
                            "teams": [],
                        }
                    
                    # Add this team variation
                    trainer_dict[trainer_name]["teams"].append({
                        "title": card_data["title"],
                        "columns": list(card_data["pokemon_list"][0].keys()) if card_data["pokemon_list"] else [],
                        "rows": card_data["pokemon_list"],
                    })
                    
                except Exception as e:
                    print(f"  Warning: Failed to parse trainer card in section '{section_name}': {e}")
                    continue
            
            if trainer_dict:
                sections.append({
                    "section": section_name,
                    "trainers": list(trainer_dict.values()),
                })
    
    return sections


def get_game_links(game_filter: Optional[Iterable[str]] = None) -> List[tuple[str, str]]:
    """Return a list of (game_name, trainer_page_url) pairs from known games."""
    
    game_links: List[tuple[str, str]] = []
    for game_name, slug, custom_suffix in KNOWN_GAMES:
        # Use custom suffix if provided, otherwise use default
        suffix = custom_suffix if custom_suffix is not None else TRAINER_PATH_SUFFIX
        url = urljoin(BASE_URL, f"/{slug}{suffix}")
        game_links.append((game_name, url))
    
    if game_filter:
        desired = {name.lower() for name in game_filter}
        game_links = [
            (name, url) for name, url in game_links 
            if name.lower() in desired or any(d in name.lower() for d in desired)
        ]
    
    return game_links


def scrape_trainer_data(
    session: requests.Session,
    delay: float,
    game_filter: Optional[Iterable[str]] = None,
) -> OrderedDict[str, dict]:
    """Scrape trainer data for every PokemonDB game page."""

    game_links = get_game_links(game_filter)
    
    if not game_links:
        print("No matching games found.")
        return OrderedDict()

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