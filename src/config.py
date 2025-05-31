import os
from dotenv import load_dotenv
load_dotenv()

class Config:
    """Configuration class for the application."""
    
    ODDS_API_KEY = os.getenv('ODDS_API_KEY')
    TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
    TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')
    sport = "basketball_nba"
    odds_format = "american"

    game_markets = ",".join([
        "h2h", "spreads", "totals"
    ])

    alt_markets = ",".join([
        "alternate_spreads", "alternate_totals",
        "team_totals", "alternate_team_totals"
    ])

    game_period_markets = ",".join([
        "h2h_q1", "h2h_q2", "h2h_q3", "h2h_q4", "h2h_h1", "h2h_h2", "h2h_3_way_q1",
        "h2h_3_way_q2", "h2h_3_way_q3", "h2h_3_way_q4", "h2h_3_way_h1", "h2h_3_way_h2",
        "spreads_q1", "spreads_q2", "spreads_q3", "spreads_q4", "spreads_h1", "spreads_h2",
        "alternate_spreads_q1", "alternate_spreads_q2", "alternate_spreads_q3", "alternate_spreads_q4",
        "alternate_spreads_h1", "alternate_spreads_h2", "totals_q1", "totals_q2", "totals_q3", "totals_q4",
        "totals_h1", "totals_h2", "alternate_totals_q1", "alternate_totals_q2", "alternate_totals_q3", 
        "alternate_totals_q4", "alternate_totals_h1", "alternate_totals_h2",
        "team_totals_q1", "team_totals_q2", "team_totals_q3", "team_totals_q4",
        "team_totals_h1", "team_totals_h2", "alternate_team_totals_q1", "alternate_team_totals_q2", 
        "alternate_team_totals_q3", "alternate_team_totals_q4",
        "alternate_team_totals_h1", "alternate_team_totals_h2"
    ])

    # List of all NBA player prop market keys
    player_prop_markets = ",".join([
        "player_points", "player_points_q1",
        "player_rebounds", "player_rebounds_q1",
        "player_assists", "player_assists_q1",
        "player_threes", "player_blocks", "player_steals",
        "player_blocks_steals", "player_turnovers",
        "player_points_rebounds_assists", "player_points_rebounds",
        "player_points_assists", "player_rebounds_assists",
        "player_field_goals", "player_frees_made", "player_frees_attempts",
        "player_first_basket", "player_first_team_basket",
        "player_double_double", "player_triple_double",
        "player_method_of_first_basket"
    ])

    player_alternate_markets = ",".join([
        "player_points_alternate", "player_assists_alternate",
        "player_rebounds_alternate", "player_blocks_alternate", "player_steals_alternate",
        "player_turnovers_alternate", "player_threes_alternate", "player_points_assists_alternate",
        "player_points_rebounds_alternate", "player_rebounds_assists_alternate",
        "player_points_rebounds_assists_alternate"
    ])

    player_all_markets = player_prop_markets + player_alternate_markets

    US = ",".join(["us", "us2"])
    UK = "uk"
    EU = "eu"
    AU = "au"
    all_regions = US + "," + UK + "," + EU + "," + AU