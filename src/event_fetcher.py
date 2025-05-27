import pandas as pd
import requests
from datetime import datetime, timezone, timedelta
from .config import Config

class EventFetcher:
    """Fetch today’s events (and later, props) from the Odds API."""

    BASE_URL = "https://api.the-odds-api.com/v4"

    def get_todays_events(self, commence_time_from=f"{datetime.utcnow().date().isoformat()}T00:00:00Z", commence_time_to=f"{datetime.utcnow().date().isoformat()}T23:59:59Z"):
        sport = Config.sport
        events_url = f"https://api.the-odds-api.com/v4/sports/{sport}/events"
        params_events = {
            "apiKey": Config.ODDS_API_KEY,
            "commenceTimeFrom": commence_time_from,
            "commenceTimeTo": commence_time_to,
            "dateFormat": "iso"
        }
        print("Commence From:", commence_time_from)
        print("Commence To:", commence_time_to)
        print("Fetching today's NBA events...")
        response_events = requests.get(events_url, params=params_events)
        print("URL:", response_events.url)
        if response_events.status_code != 200:
            print("Error fetching events:", response_events.status_code, response_events.text)
            exit()

        events = response_events.json()
        if not events:
            print("No NBA events found for today.")
            exit()

        return events

    def get_game_odds(self, markets=Config.game_markets, regions=Config.US):
        rows = []
        sport = Config.sport
        odds_url = f"https://api.the-odds-api.com/v4/sports/{sport}/odds"

        params_odds = {
                "apiKey": Config.ODDS_API_KEY,
                "regions": regions,
                "markets": markets,
                "oddsFormat": Config.odds_format,
                "dateFormat": "iso",
                "includeLinks": "true"
        }
        response_odds = requests.get(odds_url, params=params_odds)
        if response_odds.status_code != 200:
            print("Error fetching game odds:", response_odds.status_code, response_odds.text)
            exit()

        odds = response_odds.json()
        if not odds:
            print("No game odds found.")
            exit()


        # According to docs, a single event odds endpoint returns a JSON object.
        odds_data = response_odds.json()
        if not odds_data:
            print(f"No odds data for event {event_id}")
            
        # Loop through each bookmaker, then each market, then each outcome
        for bookmaker in odds_data.get("bookmakers", []):
            bookmaker_key = bookmaker.get("key")
            bookmaker_title = bookmaker.get("title")
            for market in bookmaker.get("markets", []):
                market_key = market.get("key")
                market_last_update = market.get("last_update")
                for outcome in market.get("outcomes", []):
                    outcome_name = outcome.get("name")
                    outcome_description = outcome.get("description", "")
                    outcome_price = outcome.get("price")
                    outcome_point = outcome.get("point", None)
                        
                    # Create a flattened row for each outcome
                    rows.append({
                            "event_id": event_id,
                            "commence_time": commence_time,
                            "home_team": home_team,
                            "away_team": away_team,
                            "bookmaker_key": bookmaker_key,
                            "bookmaker_title": bookmaker_title,
                            "market_key": market_key,
                            "market_last_update": market_last_update,
                            "outcome_name": outcome_name,
                            "outcome_description": outcome_description,
                            "outcome_price": outcome_price,
                            "outcome_point": outcome_point
                    })
        return rows

    def get_events_between_hours(self, prev_hours=6, next_hours=24):
        time_now_string = (datetime.utcnow() - timedelta(hours=prev_hours)).strftime("%Y-%m-%dT%H:%M:%SZ")
        time_x_hours_from_now = (datetime.utcnow() + timedelta(hours=next_hours)).strftime("%Y-%m-%dT%H:%M:%SZ")
        return self.get_todays_events(commence_time_from=time_now_string, commence_time_to=time_x_hours_from_now)
        
    def get_events_in_next_hours(self, hours=24):
        time_now_string = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
        time_x_hours_from_now = (datetime.utcnow() + timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")
        return self.get_todays_events(commence_time_from=time_now_string, commence_time_to=time_x_hours_from_now)

    def get_props_for_todays_events(self, events, markets=Config.player_prop_markets, regions=Config.US):
        
        rows = []  # List to hold flattened rows of data

        print(f"Fetching {markets} prop odds for each event...")
        for event in events:
            event_id = event.get("id")
            commence_time = event.get("commence_time")
            home_team = event.get("home_team")
            away_team = event.get("away_team")
            sport = Config.sport
            
            # Build URL for event-specific odds endpoint
            odds_url = f"https://api.the-odds-api.com/v4/sports/{sport}/events/{event_id}/odds"
            params_odds = {
                "apiKey": Config.ODDS_API_KEY,
                "regions": regions,
                "markets": markets,
                "oddsFormat": Config.odds_format,
                "dateFormat": "iso",
                "includeLinks": "true"
            }

            response_odds = requests.get(odds_url, params=params_odds)

            if response_odds.status_code != 200:
                print(f"Error fetching odds for event {event_id}: {response_odds.status_code} {response_odds.text}")
                print(odds_url)
                continue

            # According to docs, a single event odds endpoint returns a JSON object.
            odds_data = response_odds.json()
            if not odds_data:
                print(f"No odds data for event {event_id}")
                continue
            
            # Loop through each bookmaker, then each market, then each outcome
            for bookmaker in odds_data.get("bookmakers", []):
                bookmaker_key = bookmaker.get("key")
                bookmaker_title = bookmaker.get("title")
                for market in bookmaker.get("markets", []):
                    market_key = market.get("key")
                    market_last_update = market.get("last_update")
                    for outcome in market.get("outcomes", []):
                        outcome_name = outcome.get("name")
                        outcome_description = outcome.get("description", "")
                        outcome_price = outcome.get("price")
                        outcome_point = outcome.get("point", None)
                        link = outcome.get("link")
                        
                        # Create a flattened row for each outcome
                        rows.append({
                            "event_id": event_id,
                            "commence_time": commence_time,
                            "home_team": home_team,
                            "away_team": away_team,
                            "bookmaker_key": bookmaker_key,
                            "bookmaker_title": bookmaker_title,
                            "market_key": market_key,
                            "market_last_update": market_last_update,
                            "outcome_name": outcome_name,
                            "outcome_description": outcome_description,
                            "outcome_price": outcome_price,
                            "outcome_point": outcome_point,
                            "link": link
                        })
        return rows

    def save_todays_events_to_csv(self, rows, key="player", filepath="odds_data"):
        today = datetime.utcnow().date().isoformat()
        now = datetime.utcnow().isoformat()
        if rows:
            df = pd.DataFrame(rows)
            csv_filename = f"{filepath}/nba_{key}_props_{now}.csv"
            df.to_csv(csv_filename, index=False)
            print(f"Saved data for {len(rows)} outcomes to {csv_filename}")
        else:
            print(f"No odds data was retrieved for the market.")

