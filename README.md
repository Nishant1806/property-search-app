# Delhi Property Search & Market Intelligence

A small FastAPI app for searching NoBroker listings, with a Delhi real-estate market dashboard.

## What it does

- Opens the Delhi market dashboard at `/`.
- Keeps the property-search API at `/search`.
- Can also run as a command-line property search with `main.py`.
- Shows a source-labelled Delhi price snapshot, locality comparison tools, calculators, and a schematic locality map.

## Important data note

The dashboard's locality prices and appreciation figures are a published asking-price snapshot, not live listing prices or verified sale transactions. The included snapshot is labelled with its source and date in the app. It does not contain a complete quarterly or multi-year history.

The `/search` API fetches data from NoBroker and geocodes typed locations with OpenStreetMap's Nominatim service. Those external services can change, rate-limit requests, or stop responding; this project does not control them.

## Run it on Windows

1. Install Python 3.10 or newer.
2. Open PowerShell in this project folder.
3. Install the app's dependencies:

   ```powershell
   python -m pip install -r requirements.txt
   ```

4. Start the local web app:

   ```powershell
   python -m uvicorn main:app --reload
   ```

5. Open [http://127.0.0.1:8000](http://127.0.0.1:8000) in your browser.

Stop the server by returning to PowerShell and pressing `Ctrl+C`.

## Search API

Example: `http://127.0.0.1:8000/search?location=Delhi`

The API accepts `location`, `pages`, `min_price`, `max_price`, and `bedrooms` query parameters. The API returns JSON. The command-line script also supports searching a NoBroker URL and printing JSON with `--pretty-json`.

## Make changes

The homepage is `index.html`. The API and command-line scraper are in `main.py`.

## License

This project is released under the MIT License. See [LICENSE](LICENSE).
