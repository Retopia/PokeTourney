"""Debug script to inspect PokemonDB HTML structure"""
import requests
from bs4 import BeautifulSoup

url = "https://pokemondb.net/red-blue/gymleaders-elitefour"
headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
}

response = requests.get(url, headers=headers, timeout=30)
soup = BeautifulSoup(response.text, "html.parser")

print("=" * 80)
print("All H2 headings:")
for h2 in soup.find_all("h2"):
    print(f"  - {h2.get_text(strip=True)}")

print("\n" + "=" * 80)
print("All H3 headings:")
for h3 in soup.find_all("h3"):
    print(f"  - {h3.get_text(strip=True)}")

print("\n" + "=" * 80)
print("Number of tables found:", len(soup.find_all("table")))

print("\n" + "=" * 80)
print("Structure after first H2:")
first_h2 = soup.find("h2")
if first_h2:
    print(f"H2: {first_h2.get_text(strip=True)}")
    print("\nNext 10 siblings:")
    current = first_h2.find_next_sibling()
    count = 0
    while current and count < 10:
        if hasattr(current, 'name') and current.name:
            text = current.get_text(strip=True)[:100]
            classes = current.get('class', [])
            print(f"  {current.name} (classes: {classes}): {text}")
        count += 1
        current = current.find_next_sibling()

print("\n" + "=" * 80)
print("Looking for data-table or trainer-data divs:")
for cls in ['data-table', 'trainer', 'gym', 'grid', 'trainer-data', 'infocard']:
    elements = soup.find_all(class_=lambda x: x and cls in str(x).lower())
    if elements:
        print(f"  Found {len(elements)} elements with '{cls}' in class")
        if elements:
            print(f"    First one: {elements[0].name}, classes: {elements[0].get('class')}")

print("\n" + "=" * 80)
print("All div classes in the page (unique):")
all_classes = set()
for div in soup.find_all("div"):
    classes = div.get("class", [])
    for cls in classes:
        all_classes.add(cls)
print(", ".join(sorted(all_classes)[:30]))
