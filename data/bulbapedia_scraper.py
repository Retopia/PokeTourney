"""Scraper for Bulbapedia trainer battle data.

This script builds on the PokemonDB trainer list and fetches the
corresponding Bulbapedia pages to extract detailed battle rosters. The
output groups tables by their heading path (e.g. ``Pokémon -> Red and
Blue``) so downstream tools can identify the strongest configuration for
a trainer across games and rematches.
"""
from __future__ import annotations

import argparse
import json
import logging
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple
from urllib.parse import quote, urljoin

import requests
from bs4 import BeautifulSoup
from bs4.element import NavigableString, Tag

API_URL = "https://bulbapedia.bulbagarden.net/w/api.php"
BASE_URL = "https://bulbapedia.bulbagarden.net"
DEFAULT_DELAY = 1.2
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

# Headings on Bulbapedia use h2-h6; we only care up to h5 for nested sections
HEADING_TAGS = {"h2", "h3", "h4", "h5"}

REFERENCE_RE = re.compile(r"\[(?:note\s*\d+|\d+)\]")
WHITESPACE_RE = re.compile(r"\s+")

# Keywords we expect in team tables. If none are present, the table is
# likely unrelated (e.g. biographies or trivia tables).
TABLE_KEYWORDS = (
    "pokémon",
    "pokemon",
    "level",
    "moves",
    "move",
    "ability",
    "abilities",
    "item",
    "items",
)

DISALLOWED_TITLE_KEYWORDS = (
    "(anime)",
    "(manga)",
    "(adventures)",
    "(tcg)",
    "(song)",
    "(chapter)",
    "(episode)",
)

PREFERRED_TITLE_KEYWORDS = (
    "(game)",
    "(trainer)",
    "(core series)",
    "gym leader",
    "trial captain",
    "elite four",
    "champion",
)


@dataclass
class TeamTable:
    """Representation of a roster table on Bulbapedia."""

    title: Optional[str]
    columns: List[str]
    rows: List[Dict[str, str]]

    def to_dict(self) -> Dict[str, object]:
        return {
            "title": self.title,
            "columns": self.columns,
            "rows": self.rows,
        }


class BulbapediaError(RuntimeError):
    """Exception raised when a Bulbapedia request or parse fails."""


class BulbapediaTrainerScraper:
    """Scrape trainer tables from Bulbapedia using the MediaWiki API."""

    def __init__(self, *, user_agent: str, delay: float, timeout: float = 30.0) -> None:
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": user_agent})
        self.delay = delay
        self.timeout = timeout
        self._last_request = 0.0

    # ------------------------------------------------------------------
    # HTTP helpers
    # ------------------------------------------------------------------
    def _respect_rate_limit(self) -> None:
        if self.delay <= 0:
            return
        elapsed = time.monotonic() - self._last_request
        if elapsed < self.delay:
            time.sleep(self.delay - elapsed)
        self._last_request = time.monotonic()

    def _get(self, params: Dict[str, object]) -> requests.Response:
        self._respect_rate_limit()
        response = self.session.get(API_URL, params=params, timeout=self.timeout)
        response.raise_for_status()
        return response

    # ------------------------------------------------------------------
    # Bulbapedia lookups
    # ------------------------------------------------------------------
    def _score_title(self, title: str) -> int:
        lowered = title.lower()
        score = 0
        if "(" not in title:
            score += 100
        if any(keyword in lowered for keyword in PREFERRED_TITLE_KEYWORDS):
            score += 60
        if any(bad in lowered for bad in DISALLOWED_TITLE_KEYWORDS):
            score -= 200
        return score

    def _search_alternative_title(self, name: str) -> Optional[str]:
        params = {
            "action": "opensearch",
            "search": name,
            "limit": 6,
            "namespace": 0,
            "format": "json",
        }
        try:
            response = self._get(params)
        except requests.RequestException as exc:  # pragma: no cover - network failure
            raise BulbapediaError(f"Search request failed for '{name}': {exc}") from exc
        data = response.json()
        candidates = data[1] if isinstance(data, list) and len(data) >= 2 else []
        if not candidates:
            return None
        scored = sorted(((self._score_title(title), title) for title in candidates), reverse=True)
        return scored[0][1]

    def _fetch_page(self, name: str) -> Tuple[str, Dict[str, object], str]:
        params = {
            "action": "parse",
            "page": name,
            "format": "json",
            "formatversion": 2,
            "redirects": 1,
            "prop": "text|displaytitle|revid",
        }
        try:
            response = self._get(params)
        except requests.RequestException as exc:  # pragma: no cover - network failure
            raise BulbapediaError(f"Request failed for '{name}': {exc}") from exc
        data = response.json()
        if "error" in data:
            alt_title = self._search_alternative_title(name)
            if not alt_title:
                raise BulbapediaError(f"No Bulbapedia page found for '{name}'")
            logging.debug("Retrying '%s' using alternative title '%s'", name, alt_title)
            params["page"] = alt_title
            try:
                response = self._get(params)
            except requests.RequestException as exc:  # pragma: no cover - network failure
                raise BulbapediaError(f"Request failed for '{alt_title}': {exc}") from exc
            data = response.json()
            if "error" in data:
                raise BulbapediaError(f"Unable to parse Bulbapedia page for '{alt_title}': {data['error']}")
        parse_data = data.get("parse")
        if not parse_data:
            raise BulbapediaError(f"Unexpected response for '{name}': {data}")
        html = parse_data.get("text", "")
        if isinstance(html, dict):
            html = html.get("*", "")
        title = parse_data.get("displaytitle") or parse_data.get("title") or name
        pageid = parse_data.get("pageid")
        revid = parse_data.get("revid")
        page_url = urljoin(BASE_URL, f"/wiki/{quote((parse_data.get('title') or title).replace(' ', '_'))}")
        meta = {
            "title": parse_data.get("title"),
            "display_title": title,
            "pageid": pageid,
            "revid": revid,
            "url": page_url,
        }
        return title, meta, html

    # ------------------------------------------------------------------
    # HTML parsing
    # ------------------------------------------------------------------
    def scrape_trainer(self, name: str) -> Dict[str, object]:
        resolved_title, page_meta, html = self._fetch_page(name)
        sections = extract_sections(html)
        return {
            "requested_name": name,
            "resolved_title": resolved_title,
            "page": page_meta,
            "sections": [section for section in sections if section["tables"]],
        }


# ----------------------------------------------------------------------
# Parsing helpers
# ----------------------------------------------------------------------

def clean_text(text: str) -> str:
    """Normalize whitespace and strip reference footnotes."""

    text = text.replace("\xa0", " ")
    text = REFERENCE_RE.sub("", text)
    text = WHITESPACE_RE.sub(" ", text)
    return text.strip(" ;,\u2020")


def cell_text(cell: Tag) -> str:
    """Extract readable text from a table cell."""

    # Work on a shallow copy so we do not mutate the original soup tree.
    cloned = BeautifulSoup(str(cell), "html.parser")
    for tag in cloned.find_all(["sup", "span", "div"]):
        classes = tag.get("class", [])
        if tag.name == "sup" or any(cls.startswith("reference") or cls.startswith("tooltip") for cls in classes):
            tag.decompose()
    text = cloned.get_text("\n", strip=True)
    if not text:
        return ""
    parts = [clean_text(part) for part in text.split("\n")]
    return "; ".join(part for part in parts if part)


def _consume_spans(row_values: List[str], span_map: Dict[int, Tuple[str, int]], col_idx: int) -> int:
    while col_idx in span_map:
        text, remaining = span_map[col_idx]
        row_values.append(text)
        remaining -= 1
        if remaining > 0:
            span_map[col_idx] = (text, remaining)
        else:
            del span_map[col_idx]
        col_idx += 1
    return col_idx


def _parse_row(cells: Iterable[Tag], span_map: Dict[int, Tuple[str, int]]) -> List[str]:
    row_values: List[str] = []
    col_idx = 0
    col_idx = _consume_spans(row_values, span_map, col_idx)
    for cell in cells:
        col_idx = _consume_spans(row_values, span_map, col_idx)
        text = cell_text(cell)
        colspan = int(cell.get("colspan", 1) or 1)
        rowspan = int(cell.get("rowspan", 1) or 1)
        for offset in range(colspan):
            row_values.append(text)
            if rowspan > 1:
                span_map[col_idx + offset] = (text, rowspan - 1)
        col_idx += colspan
    _consume_spans(row_values, span_map, col_idx)
    return row_values


def _combine_headers(header_rows: List[List[str]]) -> List[str]:
    if not header_rows:
        return []
    width = max(len(row) for row in header_rows)
    normalized = [row + [""] * (width - len(row)) for row in header_rows]
    combined = normalized[0]
    for row in normalized[1:]:
        merged: List[str] = []
        for idx, (top, bottom) in enumerate(zip(combined, row)):
            top = clean_text(top)
            bottom = clean_text(bottom)
            if top and bottom and bottom.lower() not in top.lower():
                merged.append(f"{top} - {bottom}")
            else:
                merged.append(bottom or top)
        combined = merged
    return [col if col else f"Column {idx + 1}" for idx, col in enumerate(combined)]


def _normalize_columns(columns: List[str], width: int) -> List[str]:
    result = columns[:width] + [f"Column {idx + 1}" for idx in range(len(columns), width)]
    for idx, column in enumerate(result):
        if not column:
            result[idx] = f"Column {idx + 1}"
    return result


def parse_table(table: Tag) -> Optional[TeamTable]:
    span_map: Dict[int, Tuple[str, int]] = {}
    header_rows: List[List[str]] = []
    data_rows: List[List[str]] = []

    for row in table.find_all("tr"):
        cells = row.find_all(["th", "td"])
        if not cells:
            continue
        row_values = [clean_text(value) for value in _parse_row(cells, span_map)]
        if not any(row_values):
            continue
        is_header_row = not any(cell.name == "td" for cell in cells)
        if is_header_row:
            header_rows.append(row_values)
        else:
            data_rows.append(row_values)

    if not data_rows and not header_rows:
        return None

    header = _combine_headers(header_rows)
    width = max(len(header) if header else 0, max((len(row) for row in data_rows), default=0))
    if width == 0:
        return None
    if not header:
        header = [f"Column {idx + 1}" for idx in range(width)]
    else:
        header = _normalize_columns(header, width)

    rows: List[Dict[str, str]] = []
    for row in data_rows:
        padded = row + [""] * (width - len(row))
        entry = {header[idx]: padded[idx] for idx in range(width)}
        if any(value for value in entry.values()):
            rows.append(entry)

    if not rows:
        return None

    caption_tag = table.find("caption")
    title = clean_text(caption_tag.get_text(" ", strip=True)) if caption_tag else None
    return TeamTable(title=title or None, columns=header, rows=rows)


def _is_team_table(table: Tag) -> bool:
    classes = table.get("class", [])
    if any("navbox" in cls for cls in classes):
        return False
    header_text = " ".join(cell_text(th).lower() for th in table.find_all("th"))
    if not header_text:
        return False
    return any(keyword in header_text for keyword in TABLE_KEYWORDS)


def _normalize_heading(heading: Tag) -> str:
    title = heading.get_text(" ", strip=True)
    title = title.replace("[edit]", "")
    return clean_text(title)


def extract_sections(html: str) -> List[Dict[str, object]]:
    soup = BeautifulSoup(html, "html.parser")
    container = soup.select_one(".mw-parser-output") or soup

    sections: Dict[Tuple[str, ...], Dict[str, object]] = {}
    stack: List[Tuple[int, str]] = []

    for element in container.children:
        if isinstance(element, NavigableString):
            continue
        if element.name in HEADING_TAGS:
            level = int(element.name[1])
            title = _normalize_heading(element)
            if not title:
                continue
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, title))
            continue
        if element.name != "table":
            continue
        if not stack:
            continue
        # Only keep tables that fall under a Pokémon heading at level 2 or deeper.
        if not any(level <= 2 and "pokémon" in title.lower() for level, title in stack):
            continue
        if not _is_team_table(element):
            continue
        table = parse_table(element)
        if not table:
            continue
        path = tuple(title for _, title in stack)
        section = sections.setdefault(path, {"path": list(path), "tables": []})
        section["tables"].append(table.to_dict())
    # Preserve deterministic ordering by sorting paths alphabetically.
    ordered_paths = sorted(sections.keys())
    return [sections[path] for path in ordered_paths]


# ----------------------------------------------------------------------
# Trainer name helpers
# ----------------------------------------------------------------------

def load_trainer_names(pokemondb_json: Path) -> List[str]:
    if not pokemondb_json.exists():
        raise FileNotFoundError(f"PokemonDB JSON file not found: {pokemondb_json}")
    with pokemondb_json.open("r", encoding="utf8") as handle:
        data = json.load(handle)
    names = set()
    for game in data.values():
        sections = game.get("sections", [])
        for section in sections:
            for trainer in section.get("trainers", []):
                name = trainer.get("name")
                if name:
                    names.add(name)
    return sorted(names)


# ----------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------

def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Scrape Bulbapedia trainer rosters")
    parser.add_argument(
        "--pokemondb-json",
        type=Path,
        default=Path(__file__).with_name("pokemondb_trainers.json"),
        help="Path to the PokemonDB trainer JSON used to derive trainer names",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).with_name("bulbapedia_trainers.json"),
        help="Destination JSON file",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=DEFAULT_DELAY,
        help="Delay between HTTP requests to respect Bulbapedia rate limits",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=30.0,
        help="Timeout for Bulbapedia requests (seconds)",
    )
    parser.add_argument(
        "--user-agent",
        default=DEFAULT_USER_AGENT,
        help="Custom user agent string",
    )
    parser.add_argument(
        "--trainer",
        dest="trainers",
        action="append",
        help="Restrict scraping to specific trainers (can be provided multiple times)",
    )
    parser.add_argument(
        "--max-trainers",
        type=int,
        help="Limit the number of trainers processed (useful for debugging)",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        help="Logging verbosity",
    )
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_argument_parser()
    args = parser.parse_args(argv)

    logging.basicConfig(level=getattr(logging, args.log_level.upper()), format="%(message)s")

    try:
        all_trainers = load_trainer_names(args.pokemondb_json)
    except FileNotFoundError as exc:
        logging.error("%s", exc)
        return 1

    if args.trainers:
        requested = set(args.trainers)
        missing = requested - set(all_trainers)
        if missing:
            logging.warning("%d trainers not present in PokemonDB list: %s", len(missing), ", ".join(sorted(missing)))
        trainers = [name for name in all_trainers if name in requested]
    else:
        trainers = all_trainers

    if args.max_trainers is not None:
        trainers = trainers[: args.max_trainers]

    scraper = BulbapediaTrainerScraper(user_agent=args.user_agent, delay=args.delay, timeout=args.timeout)

    results: Dict[str, object] = {}
    failures: Dict[str, str] = {}
    for index, trainer_name in enumerate(trainers, start=1):
        logging.info("[%d/%d] Scraping %s", index, len(trainers), trainer_name)
        try:
            results[trainer_name] = scraper.scrape_trainer(trainer_name)
        except BulbapediaError as exc:
            logging.warning("Failed to scrape %s: %s", trainer_name, exc)
            failures[trainer_name] = str(exc)
        except Exception as exc:  # pragma: no cover - defensive guard
            logging.exception("Unexpected error while scraping %s", trainer_name)
            failures[trainer_name] = f"Unexpected error: {exc}"

    payload = {
        "source": {
            "api": API_URL,
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "pokemondb_seed": str(args.pokemondb_json),
        },
        "trainers": results,
    }
    if failures:
        payload["failures"] = failures

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")

    logging.info("Wrote %d trainer entries to %s", len(results), args.output)
    if failures:
        logging.warning("Encountered %d failures", len(failures))
    return 0 if not failures else 2


if __name__ == "__main__":  # pragma: no cover - CLI entrypoint
    sys.exit(main())
