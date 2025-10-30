"""Scraper for PokemonDB gym leaders, Elite Four, champions, and rivals."""
from __future__ import annotations

import argparse
import json
import re
import time
from collections import OrderedDict
from pathlib import Path
from typing import Dict, Iterable, List, Optional

try:
    import requests
except ImportError as exc:  # pragma: no cover - dependency guard
    raise SystemExit("The 'requests' package is required. Install it with 'pip install requests'.") from exc

try:
    from bs4 import BeautifulSoup, Tag
except ImportError as exc:  # pragma: no cover - dependency guard
    raise SystemExit(
        "BeautifulSoup (bs4) is required. Install it with 'pip install beautifulsoup4'."
    ) from exc


BASE_URL = "https://pokemondb.net"
GAMES_INDEX = f"{BASE_URL}/games"
REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}
REQUEST_TIMEOUT = 30
REQUEST_DELAY = 0.5

CATEGORY_ALIASES = {
    "gym_leaders": ("gym leader", "gym leaders"),
    "elite_four": ("elite four", "elite 4"),
    "champions": ("champion", "champions"),
    "rivals": ("rival", "rivals"),
}
CATEGORY_ORDER = ("gym_leaders", "elite_four", "champions", "rivals")


class PokemonTrainerScraper:
    """Scrapes trainer information from PokemonDB."""

    def __init__(self, session: Optional[requests.Session] = None) -> None:
        self.session = session or requests.Session()
        self.session.headers.update(REQUEST_HEADERS)

    def scrape(self) -> Dict[str, Dict[str, List[Dict[str, object]]]]:
        games = self._fetch_games()
        results: Dict[str, Dict[str, List[Dict[str, object]]]] = OrderedDict()
        for game_name, url in games.items():
            data = self._scrape_game(url)
            if data:
                results[game_name] = data
            time.sleep(REQUEST_DELAY)
        return results

    def _fetch_games(self) -> "OrderedDict[str, str]":
        response = self.session.get(GAMES_INDEX, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        links = OrderedDict()
        for anchor in soup.select("a[href$='gymleaders-elitefour']"):
            href = anchor.get("href")
            if not href:
                continue
            url = self._absolute_url(href)
            game_name = self._clean_text(anchor.get_text(" ", strip=True))
            if not game_name:
                continue
            game_name = self._ensure_unique_game_name(game_name, links)
            links[game_name] = url
        if not links:
            raise RuntimeError(
                "Unable to locate any game links. Page structure may have changed."
            )
        return links

    def _scrape_game(self, url: str) -> Dict[str, List[Dict[str, object]]]:
        response = self.session.get(url, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        article = soup.find("article")
        if article is None:
            raise RuntimeError(f"Unable to locate article element on page: {url}")

        category_sections: Dict[str, List[Dict[str, object]]] = {
            key: [] for key in CATEGORY_ORDER
        }

        for table in article.find_all("table"):
            heading = self._nearest_heading(table)
            if heading is None:
                continue
            heading_text = self._clean_text(heading.get_text(" ", strip=True))
            category = self._match_category(heading_text)
            if category is None:
                continue
            trainers = self._parse_trainer_table(table)
            if not trainers:
                continue
            section_payload = {
                "section": heading_text,
                "trainers": trainers,
            }
            category_sections[category].append(section_payload)

        # Remove categories without data to keep the JSON compact.
        return {
            key: value
            for key, value in category_sections.items()
            if value
        }

    def _parse_trainer_table(self, table: Tag) -> List[Dict[str, object]]:
        header_labels = self._extract_header_labels(table)
        rows: List[Dict[str, object]] = []
        for row in table.find_all("tr"):
            if row.find_parent("thead"):
                continue
            data_cells = row.find_all("td")
            row_headers = [cell for cell in row.find_all("th") if cell.get("scope") == "row"]
            if not data_cells and not row_headers:
                continue
            if data_cells:
                row_dict: Dict[str, object] = {}
                if row_headers:
                    row_dict["name"] = self._clean_cell(row_headers[0])
                cleaned_cells = [self._clean_cell(cell) for cell in data_cells]
                if header_labels:
                    if len(header_labels) == len(cleaned_cells) + (1 if row_headers else 0):
                        labels_for_data = header_labels[len(row_headers):]
                    else:
                        labels_for_data = header_labels[: len(cleaned_cells)]
                else:
                    labels_for_data = []
                for idx, value in enumerate(cleaned_cells):
                    label = (
                        labels_for_data[idx]
                        if idx < len(labels_for_data)
                        else f"column_{idx + 1}"
                    )
                    row_dict[label] = value
                rows.append(row_dict)
        return rows

    @staticmethod
    def _clean_cell(cell: Tag) -> object:
        text = cell.get_text("\n", strip=True)
        parts = [part.strip() for part in text.split("\n") if part.strip()]
        if not parts:
            return ""
        if len(parts) == 1:
            return parts[0]
        return parts

    @staticmethod
    def _extract_header_labels(table: Tag) -> List[str]:
        header_labels: List[str] = []
        thead = table.find("thead")
        if thead:
            header_row = thead.find("tr")
        else:
            header_row = table.find("tr")
            if header_row and header_row.find_all("td"):
                header_row = None
        if header_row:
            header_labels = [
                PokemonTrainerScraper._normalize_header(th.get_text(" ", strip=True))
                for th in header_row.find_all("th")
            ]
        return header_labels

    @staticmethod
    def _normalize_header(text: str) -> str:
        text = text.strip()
        text = re.sub(r"[^0-9A-Za-z]+", "_", text)
        text = re.sub(r"_+", "_", text).strip("_")
        return text.lower() or "column"

    @staticmethod
    def _clean_text(text: str) -> str:
        return re.sub(r"\s+", " ", text).strip()

    @staticmethod
    def _ensure_unique_game_name(name: str, existing: Dict[str, str]) -> str:
        if name not in existing:
            return name
        suffix = 2
        while f"{name} ({suffix})" in existing:
            suffix += 1
        return f"{name} ({suffix})"

    def _nearest_heading(self, element: Tag) -> Optional[Tag]:
        heading = element.find_previous(self._heading_tags())
        return heading

    @staticmethod
    def _heading_tags() -> Iterable[str]:
        return [f"h{level}" for level in range(1, 7)]

    def _match_category(self, text: str) -> Optional[str]:
        lowered = text.lower()
        for category, aliases in CATEGORY_ALIASES.items():
            if any(alias in lowered for alias in aliases):
                return category
        return None

    @staticmethod
    def _absolute_url(href: str) -> str:
        if href.startswith("http"):
            return href
        return f"{BASE_URL}{href}"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Scrape PokemonDB trainer data into JSON."
    )
    default_output = Path(__file__).with_name("pokemon_trainers.json")
    parser.add_argument(
        "--output",
        type=Path,
        default=default_output,
        help="Destination JSON file. Defaults to data/pokemon_trainers.json.",
    )
    args = parser.parse_args()

    scraper = PokemonTrainerScraper()
    data = scraper.scrape()

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    print(f"Wrote trainer data for {len(data)} games to {args.output}")


if __name__ == "__main__":
    main()
