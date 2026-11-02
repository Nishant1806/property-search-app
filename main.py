import argparse
import base64
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse


DEFAULT_LOCATION = "delhi"
DEFAULT_RADIUS = "2.0"
KNOWN_CITY_ALIASES = {
    "bangalore": "bangalore",
    "bengaluru": "bangalore",
    "delhi": "delhi",
    "mumbai": "mumbai",
    "chennai": "chennai",
    "hyderabad": "hyderabad",
    "pune": "pune",
    "gurgaon": "gurgaon",
    "gurugram": "gurgaon",
    "noida": "noida",
    "greater noida": "greater_noida",
    "ghaziabad": "ghaziabad",
    "faridabad": "faridabad",
}


def parse_args():
    parser = argparse.ArgumentParser(
        description="Fetch and print NoBroker listings from the public filter API."
    )
    parser.add_argument(
        "--url",
        help="Optional full NoBroker search URL to use directly.",
    )
    parser.add_argument(
        "--location",
        default=DEFAULT_LOCATION,
        help='Location to search, for example "delhi" or "adyar chennai".',
    )
    parser.add_argument(
        "--pages",
        type=int,
        default=1,
        help="How many API pages to fetch (default: 1).",
    )
    parser.add_argument(
        "--min_price",
        type=float,
        help="Minimum listing price in INR.",
    )
    parser.add_argument(
        "--max_price",
        type=float,
        help="Maximum listing price in INR.",
    )
    parser.add_argument(
        "--bedrooms",
        type=int,
        help="Exact number of bedrooms to match.",
    )
    parser.add_argument(
        "--pretty-json",
        action="store_true",
        help="Print each raw listing as JSON instead of a compact summary.",
    )
    return parser.parse_args()


def fetch_json(url):
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json, text/plain, */*",
        "Referer": "https://www.nobroker.in/",
    }
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def normalize_location(location):
    cleaned = " ".join((location or "").strip().lower().split())
    if not cleaned:
        raise ValueError("location cannot be empty")
    return cleaned


def infer_city_and_locality(location):
    for alias, city in sorted(KNOWN_CITY_ALIASES.items(), key=lambda item: len(item[0]), reverse=True):
        if location == alias:
            return city, location.title()
        if location.endswith(" " + alias):
            locality = location[: -len(alias)].strip()
            return city, locality.title() if locality else alias.title()

    first_token = location.split()[0]
    return KNOWN_CITY_ALIASES.get(first_token, first_token), location.title()


def geocode_location(location):
    query = urllib.parse.urlencode({"q": location, "format": "jsonv2", "limit": 1})
    url = f"https://nominatim.openstreetmap.org/search?{query}"
    headers = {
        "User-Agent": "NoBrokerLocationScraper/1.0",
        "Accept": "application/json",
    }
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=30) as response:
        results = json.load(response)

    if not results:
        raise ValueError(f'Unable to geocode location "{location}"')

    top_result = results[0]
    return float(top_result["lat"]), float(top_result["lon"])


def build_search_param(location, latitude, longitude):
    payload = [
        {
            "lat": latitude,
            "lon": longitude,
            "placeId": "",
            "placeName": location.title(),
        }
    ]
    encoded = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    return base64.b64encode(encoded).decode("ascii")


def build_api_request(params, page_no):
    request_params = dict(params)
    request_params["pageNo"] = page_no
    listing_kind = request_params.pop("listingKind", "sale")
    api_url = f"https://www.nobroker.in/api/v1/multi/property/{listing_kind}/filter"
    return f"{api_url}?{urllib.parse.urlencode(request_params)}"


def get_params_from_url(url):
    parsed = urllib.parse.urlparse(url)
    if "nobroker.in" not in (parsed.netloc or ""):
        raise ValueError("url must be a NoBroker search URL")

    path_parts = [part for part in parsed.path.split("/") if part]
    listing_kind = "sale"
    if len(path_parts) >= 2 and path_parts[0] == "property":
        candidate = path_parts[1].lower()
        if candidate in {"sale", "rent"}:
            listing_kind = candidate

    query = urllib.parse.parse_qs(parsed.query)
    radius = query.get("radius", [DEFAULT_RADIUS])[0]
    city = query.get("city", [""])[0]
    locality = query.get("locality", [""])[0]
    search_param = query.get("searchParam", [""])[0]

    lat_value = query.get("lat", [None])[0] or query.get("latitude", [None])[0]
    lon_value = (
        query.get("lon", [None])[0]
        or query.get("lng", [None])[0]
        or query.get("longitude", [None])[0]
    )

    if not city and len(path_parts) >= 3:
        city = path_parts[2].lower()
    if not locality and len(path_parts) >= 4:
        locality = urllib.parse.unquote(path_parts[3]).replace("-", " ").title()

    if not search_param:
        if lat_value is None or lon_value is None:
            raise ValueError(
                "url must include either searchParam or latitude/longitude values"
            )
        seed_name = locality or city or "Search Area"
        search_param = build_search_param(seed_name, float(lat_value), float(lon_value))

    if not city:
        raise ValueError("url is missing city")
    if not locality:
        locality = city.title()

    return {
        "listingKind": listing_kind,
        "searchParam": search_param,
        "radius": radius,
        "city": city.lower(),
        "locality": locality,
    }


def get_params_from_location(location):
    normalized_location = normalize_location(location)
    city, locality = infer_city_and_locality(normalized_location)
    latitude, longitude = geocode_location(normalized_location)
    return {
        "listingKind": "sale",
        "searchParam": build_search_param(normalized_location, latitude, longitude),
        "radius": DEFAULT_RADIUS,
        "city": city,
        "locality": locality,
    }


def to_float(value):
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def to_int(value):
    if value in (None, ""):
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def extract_bedrooms(raw_listing):
    for key in ("bedrooms", "noOfBedrooms", "bedroom", "bhkType"):
        value = to_int(raw_listing.get(key))
        if value is not None:
            return value

    title = raw_listing.get("propertyTitle") or ""
    match = re.search(r"(\d+)\s*BHK", title, re.IGNORECASE)
    if match:
        return int(match.group(1))
    if "4+" in title:
        return 4
    return None


def clean_listing(raw_listing):
    return {
        "price": to_float(raw_listing.get("price")),
        "area": to_float(raw_listing.get("propertySize") or raw_listing.get("carpetArea")),
        "bedrooms": extract_bedrooms(raw_listing),
        "location": raw_listing.get("locality") or raw_listing.get("street") or raw_listing.get("city"),
    }


def filter_listings(listings, min_price=None, max_price=None, bedrooms=None):
    filtered = []
    for listing in listings:
        price = listing.get("price")
        bedroom_count = listing.get("bedrooms")

        if min_price is not None:
            if price is None or price < min_price:
                continue
        if max_price is not None:
            if price is None or price > max_price:
                continue
        if bedrooms is not None:
            if bedroom_count is None or bedroom_count != bedrooms:
                continue

        filtered.append(listing)

    return filtered


def format_clean_listing(index, listing):
    def display(value):
        return "None" if value is None else value

    lines = [
        f"{index}.",
        f"   price: {display(listing['price'])}",
        f"   area_sqft: {display(listing['area'])}",
        f"   bedrooms: {display(listing['bedrooms'])}",
        f"   location: {display(listing['location'])}",
    ]
    return "\n".join(lines)


def search_properties(location, pages=1):
    if pages < 1:
        raise ValueError("pages must be at least 1")

    params = get_params_from_location(location)
    all_items = []
    for page_no in range(pages):
        api_url = build_api_request(params, page_no)
        payload = fetch_json(api_url)
        items = payload.get("data") or []
        if not items:
            break
        all_items.extend(items)
    return all_items


def search_properties_from_url(url, pages=1):
    if pages < 1:
        raise ValueError("pages must be at least 1")

    params = get_params_from_url(url)
    all_items = []
    for page_no in range(pages):
        api_url = build_api_request(params, page_no)
        payload = fetch_json(api_url)
        items = payload.get("data") or []
        if not items:
            break
        all_items.extend(items)
    return all_items


def get_properties(location=None, url=None, pages=1, min_price=None, max_price=None, bedrooms=None):
    if url:
        raw_listings = search_properties_from_url(url, pages)
    else:
        location = normalize_location(location or DEFAULT_LOCATION)
        raw_listings = search_properties(location, pages)

    cleaned_listings = [clean_listing(item) for item in raw_listings]
    return filter_listings(
        cleaned_listings,
        min_price=min_price,
        max_price=max_price,
        bedrooms=bedrooms,
    )


app = FastAPI(title="NoBroker Search")


HOME_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>NoBroker Search</title>
</head>
<body>
  <h1>NoBroker Search</h1>
  <form id="search-form">
    <label for="location">Location</label>
    <input id="location" name="location" type="text" value="delhi" placeholder="Enter location">
    <button type="submit">Search</button>
  </form>

  <p id="status"></p>
  <pre id="results"></pre>

  <script>
    const form = document.getElementById("search-form");
    const statusEl = document.getElementById("status");
    const resultsEl = document.getElementById("results");

    function formatListings(items) {
      if (!items.length) {
        return "No listings found.";
      }

      return items.map((item, index) => {
        return [
          `${index + 1}.`,
          `  price: ${item.price}`,
          `  area_sqft: ${item.area}`,
          `  bedrooms: ${item.bedrooms}`,
          `  location: ${item.location}`
        ].join("\\n");
      }).join("\\n\\n");
    }

    async function runSearch(location) {
      statusEl.textContent = `Searching for "${location}"...`;
      resultsEl.textContent = "";

      try {
        const response = await fetch(`/search?location=${encodeURIComponent(location)}`);
        const data = await response.json();

        if (!response.ok) {
          throw new Error(data.detail || "Request failed");
        }

        statusEl.textContent = `Found ${data.count} listing(s) for "${data.location}".`;
        resultsEl.textContent = formatListings(data.results);
      } catch (error) {
        statusEl.textContent = `Error: ${error.message}`;
      }
    }

    form.addEventListener("submit", (event) => {
      event.preventDefault();
      const location = document.getElementById("location").value.trim() || "delhi";
      runSearch(location);
    });
  </script>
</body>
</html>
"""


@app.get("/", response_class=HTMLResponse)
async def home():
    return Path(__file__).with_name("index.html").read_text(encoding="utf-8")


@app.get("/search")
async def search(
    location: str = Query(DEFAULT_LOCATION),
    pages: int = Query(1, ge=1),
    min_price: float | None = Query(None),
    max_price: float | None = Query(None),
    bedrooms: int | None = Query(None),
):
    try:
        items = get_properties(
            location=location,
            pages=pages,
            min_price=min_price,
            max_price=max_price,
            bedrooms=bedrooms,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except urllib.error.HTTPError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"HTTP error: {exc.code} {exc.reason}",
        ) from exc
    except urllib.error.URLError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Network error: {exc.reason}",
        ) from exc

    return {
        "location": normalize_location(location),
        "count": len(items),
        "results": items[:10],
    }


if __name__ == "__main__":
    args = parse_args()

    try:
        label = args.url or normalize_location(args.location)
        filtered_items = get_properties(
            location=args.location,
            url=args.url,
            pages=args.pages,
            min_price=args.min_price,
            max_price=args.max_price,
            bedrooms=args.bedrooms,
        )
    except ValueError as exc:
        print(f"Input error: {exc}", file=sys.stderr)
        raise SystemExit(2)
    except urllib.error.HTTPError as exc:
        print(f"HTTP error: {exc.code} {exc.reason}", file=sys.stderr)
        raise SystemExit(1)
    except urllib.error.URLError as exc:
        print(f"Network error: {exc.reason}", file=sys.stderr)
        raise SystemExit(1)

    if not filtered_items:
        print("No listings returned.")
        raise SystemExit(0)

    visible_items = filtered_items[:10]
    print(
        f'Fetched {len(filtered_items)} cleaned listing(s) for "{label}". '
        f"Showing first {len(visible_items)}."
    )
    for index, item in enumerate(visible_items, start=1):
        if args.pretty_json:
            print(json.dumps(item, indent=2, ensure_ascii=True))
        else:
            print(format_clean_listing(index, item))
        if index != len(visible_items):
            print()
