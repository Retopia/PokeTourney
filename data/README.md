# PokemonDB Scraper

A Python scraper that extracts gym leader, Elite Four, and champion trainer data from [PokemonDB](https://pokemondb.net).

## Installation

Install the required dependencies:

```bash
pip install -r requirements.txt
```

## Usage

### Scrape all games

```bash
python pokemondb_scraper.py
```

This will scrape data for all known Pokémon games and save it to `pokemondb_trainers.json`.

### Scrape specific games

```bash
python pokemondb_scraper.py --game "Red/Blue" --game "X/Y"
```

### Options

- `--output PATH`: Specify output file path (default: `pokemondb_trainers.json`)
- `--delay SECONDS`: Delay between requests to be respectful to the server (default: 1.5 seconds)
- `--game NAME`: Limit scraping to specific games (can be used multiple times)
- `--user-agent STRING`: Custom user agent string

### Examples

```bash
# Scrape only Gen 1 games with a longer delay
python pokemondb_scraper.py --game "Red/Blue" --game "Yellow" --delay 3

# Save to a custom location
python pokemondb_scraper.py --output ../backend/data/trainers.json

# Scrape all games to current directory
python pokemondb_scraper.py --output ./trainers.json
```

## Supported Games

The scraper supports the following games:

- Red/Blue
- Yellow
- Gold/Silver
- Crystal
- Ruby/Sapphire
- Emerald
- FireRed/LeafGreen
- Diamond/Pearl
- Platinum
- HeartGold/SoulSilver
- Black/White
- Black 2/White 2
- X/Y
- Omega Ruby/Alpha Sapphire
- Sun/Moon
- Ultra Sun/Ultra Moon
- Let's Go Pikachu/Eevee
- Sword/Shield
- Brilliant Diamond/Shining Pearl
- Scarlet/Violet

## Output Format

The scraper outputs JSON data structured by game, with each game containing sections (Gym Leaders, Elite Four, Champion) and trainer information including their Pokémon teams:

```json
{
  "Red/Blue": {
    "source": "https://pokemondb.net/red-blue/gymleaders-elitefour",
    "sections": [
      {
        "section": "Gym #1, Pewter City",
        "trainers": [
          {
            "name": "Brock",
            "subtitle": "Boulder Badge",
            "description": null,
            "teams": [
              {
                "title": null,
                "columns": ["Pokemon", "Number", "Level", "Type"],
                "rows": [
                  {
                    "Pokemon": "Geodude",
                    "Number": "#074",
                    "Level": "12",
                    "Type": "Rock / Ground"
                  }
                ]
              }
            ]
          }
        ]
      }
    ]
  }
}
```

## Notes

- The scraper includes delays between requests to be respectful to PokemonDB's servers
- Some pages may have different layouts or structures that could require parser updates
- The scraper only extracts gym leaders, Elite Four members, and champions (not all trainers in the game)

## License

This tool is for educational and personal use. Please respect PokemonDB's terms of service and don't abuse their servers.
