"""Improved debug script to understand Pokemon card structure"""
import requests
from bs4 import BeautifulSoup

url = "https://pokemondb.net/red-blue/gymleaders-elitefour"
headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
}

response = requests.get(url, headers=headers, timeout=30)
soup = BeautifulSoup(response.text, "html.parser")

# Get first trainer card
first_h2 = soup.find("h2")
first_card = first_h2.find_next_sibling("div", class_="infocard-list-trainer-pkmn")

print("First trainer card HTML structure:\n")
print(first_card.prettify()[:2000])

print("\n" + "=" * 80)
print("Looking for trainer-pkmn divs:")
pkmn_divs = first_card.find_all("div", class_="trainer-pkmn")
print(f"Found {len(pkmn_divs)} trainer-pkmn divs")

if pkmn_divs:
    print("\nFirst Pokemon div:")
    print(pkmn_divs[0].prettify())
