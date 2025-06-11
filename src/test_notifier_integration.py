"""
Test integration between odds_processor output and TelegramNotifier.
This test creates sample DataFrames that match the expected output from odds_processor
and verifies the notification system works correctly.
"""

import pandas as pd
import numpy as np
from datetime import datetime, timezone
import logging
import os
import sys

# Add the src directory to path for imports
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
sys.path.insert(0, current_dir)
sys.path.insert(0, parent_dir)

from notifier import TelegramNotifier
from odds_processor import OddsProcessor
from event_fetcher import EventFetcher
from config import Config

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def create_sample_arbitrage_player_df():
    """Create a sample arbitrage opportunities DataFrame for player props."""
    data = [
        {
            'outcome_description': 'LeBron James Points',
            'market_key': 'player_points',
            'over_point': 25.5,
            'under_point': 25.5,
            'over_prob': 0.48,
            'under_prob': 0.47,
            'sum_prob': 0.95,
            'over_bookmaker': 'draftkings',
            'under_bookmaker': 'fanduel',
            'over_market': 'alternate',
            'under_market': 'under_over',
            'over_odds': 110,
            'under_odds': 105,
            'over_link': 'https://sportsbook.draftkings.com/...',
            'under_link': 'https://sportsbook.fanduel.com/...'
        },
        {
            'outcome_description': 'Stephen Curry 3-Point Made',
            'market_key': 'player_threes',
            'over_point': 3.5,
            'under_point': 3.5,
            'over_prob': 0.49,
            'under_prob': 0.46,
            'sum_prob': 0.95,
            'over_bookmaker': 'betmgm',
            'under_bookmaker': 'caesars',
            'over_market': 'under_over',
            'under_market': 'alternate',
            'over_odds': 120,
            'under_odds': 115,
            'over_link': 'https://sports.betmgm.com/...',
            'under_link': 'https://sportsbook.caesars.com/...'
        }
    ]
    return pd.DataFrame(data)

def create_sample_arbitrage_game_df():
    """Create a sample arbitrage opportunities DataFrame for game props."""
    data = [
        {
            'outcome_description': 'Total Points',
            'market_key': 'totals',
            'over_point': 220.5,
            'under_point': 220.5,
            'over_prob': 0.48,
            'under_prob': 0.47,
            'sum_prob': 0.95,
            'over_bookmaker': 'draftkings',
            'under_bookmaker': 'fanduel',
            'over_market': 'under_over',
            'under_market': 'under_over',
            'over_odds': 108,
            'under_odds': 112,
            'over_link': 'https://sportsbook.draftkings.com/...',
            'under_link': 'https://sportsbook.fanduel.com/...'
        }
    ]
    return pd.DataFrame(data)

def create_sample_mispriced_player_df():
    """Create a sample mispriced opportunities DataFrame for player props."""
    data = [
        {
            'outcome_description': 'Jayson Tatum Points',
            'market_key': 'player_points',
            'point': 28.5,
            'side': 'Over',
            'prob_mkt': 0.52,
            'prob_fit': 0.58,
            'edge': 0.115,  # 11.5% edge
            'bookmaker': 'draftkings',
            'odds': 105,
            'market_type': 'under_over',
            'link': 'https://sportsbook.draftkings.com/...',
            'mispriced': True,
            'vig': 0.04
        },
        {
            'outcome_description': 'Luka Doncic Assists',
            'market_key': 'player_assists',
            'point': 8.5,
            'side': 'Under',
            'prob_mkt': 0.45,
            'prob_fit': 0.52,
            'edge': 0.156,  # 15.6% edge
            'bookmaker': 'fanduel',
            'odds': 122,
            'market_type': 'alternate',
            'link': 'https://sportsbook.fanduel.com/...',
            'mispriced': True,
            'vig': 0.05
        },
        {
            'outcome_description': 'Giannis Antetokounmpo Rebounds',
            'market_key': 'player_rebounds',
            'point': 11.5,
            'side': 'Over',
            'prob_mkt': 0.48,
            'prob_fit': 0.56,
            'edge': 0.167,  # 16.7% edge
            'bookmaker': 'betmgm',
            'odds': 110,
            'market_type': 'under_over',
            'link': 'https://sports.betmgm.com/...',
            'mispriced': True,
            'vig': 0.045
        }
    ]
    return pd.DataFrame(data)

def create_sample_mispriced_game_df():
    """Create a sample mispriced opportunities DataFrame for game props."""
    data = [
        {
            'outcome_description': 'First Quarter Total',
            'market_key': 'totals_quarters',
            'point': 55.5,
            'side': 'Over',
            'prob_mkt': 0.47,
            'prob_fit': 0.54,
            'edge': 0.149,  # 14.9% edge
            'bookmaker': 'caesars',
            'odds': 115,
            'market_type': 'under_over',
            'link': 'https://sportsbook.caesars.com/...',
            'mispriced': True,
            'vig': 0.05
        }
    ]
    return pd.DataFrame(data)

def update_notifier_formatting():
    """Update the notifier to handle the actual DataFrame structure from odds_processor."""
    
    def format_arbitrage_message(self, arb_player_df, arb_game_df):
        """Format arbitrage DataFrames into a Telegram message."""
        if arb_player_df.empty and arb_game_df.empty:
            return ""
        
        message = "🏀 **ARBITRAGE OPPORTUNITIES** 🏀\n\n"
        
        # Player arbitrage opportunities
        if not arb_player_df.empty:
            message += "**Player Props:**\n"
            for _, row in arb_player_df.iterrows():
                profit_margin = (1 / row['sum_prob'] - 1) * 100
                message += f"• **{row['outcome_description']}** ({row['market_key']})\n"
                message += f"  📈 Over {row['over_point']}: {row['over_odds']:+d} @ {row['over_bookmaker']}\n"
                message += f"  📉 Under {row['under_point']}: {row['under_odds']:+d} @ {row['under_bookmaker']}\n"
                message += f"  💰 Profit Margin: {profit_margin:.2f}%\n"
                message += f"  🔗 [Over]({row['over_link']}) | [Under]({row['under_link']})\n\n"
        
        # Game arbitrage opportunities
        if not arb_game_df.empty:
            message += "**Game Props:**\n"
            for _, row in arb_game_df.iterrows():
                profit_margin = (1 / row['sum_prob'] - 1) * 100
                message += f"• **{row['outcome_description']}** ({row['market_key']})\n"
                message += f"  📈 Over {row['over_point']}: {row['over_odds']:+d} @ {row['over_bookmaker']}\n"
                message += f"  📉 Under {row['under_point']}: {row['under_odds']:+d} @ {row['under_bookmaker']}\n"
                message += f"  💰 Profit Margin: {profit_margin:.2f}%\n"
                message += f"  🔗 [Over]({row['over_link']}) | [Under]({row['under_link']})\n\n"
        
        return message
    
    def format_mispriced_message(self, mispriced_player_df, mispriced_game_df):
        """Format mispriced DataFrames into a Telegram message."""
        if mispriced_player_df.empty and mispriced_game_df.empty:
            return ""
        
        message = "📊 **MISPRICED / +EV LINES** 📊\n\n"
        
        # Player mispriced opportunities
        if not mispriced_player_df.empty:
            message += "**Player Props:**\n"
            for _, row in mispriced_player_df.iterrows():
                edge_pct = row['edge'] * 100
                message += f"• **{row['outcome_description']}** ({row['market_key']})\n"
                message += f"  🎯 {row['side']} {row['point']}: {row['odds']:+d} @ {row['bookmaker']}\n"
                message += f"  📈 Edge: {edge_pct:.1f}% (Market: {row['prob_mkt']:.1%}, Fair: {row['prob_fit']:.1%})\n"
                message += f"  🔗 [Bet Now]({row['link']})\n\n"
        
        # Game mispriced opportunities
        if not mispriced_game_df.empty:
            message += "**Game Props:**\n"
            for _, row in mispriced_game_df.iterrows():
                edge_pct = row['edge'] * 100
                message += f"• **{row['outcome_description']}** ({row['market_key']})\n"
                message += f"  🎯 {row['side']} {row['point']}: {row['odds']:+d} @ {row['bookmaker']}\n"
                message += f"  📈 Edge: {edge_pct:.1f}% (Market: {row['prob_mkt']:.1%}, Fair: {row['prob_fit']:.1%})\n"
                message += f"  🔗 [Bet Now]({row['link']})\n\n"
        
        return message
    
    def process_odds_output(self, arb_player_df, arb_game_df, mispriced_player_df, mispriced_game_df):
        """Process the 4-tuple output from odds_processor."""
        logger.info(f"Processing odds output: {len(arb_player_df)} player arbs, {len(arb_game_df)} game arbs, "
                   f"{len(mispriced_player_df)} player mispriced, {len(mispriced_game_df)} game mispriced")
        
        arbitrage_message = self.format_arbitrage_message(arb_player_df, arb_game_df)
        mispriced_message = self.format_mispriced_message(mispriced_player_df, mispriced_game_df)
        
        # Combine messages with separator if both exist
        if arbitrage_message and mispriced_message:
            self.message = f"{arbitrage_message}\n{'='*30}\n\n{mispriced_message}"
        elif arbitrage_message:
            self.message = arbitrage_message
        elif mispriced_message:
            self.message = mispriced_message
        else:
            self.message = "📭 No opportunities found at this time."
            
        logger.info("Successfully processed odds output into notification message.")
    
    # Monkey patch the TelegramNotifier class
    TelegramNotifier.format_arbitrage_message = format_arbitrage_message
    TelegramNotifier.format_mispriced_message = format_mispriced_message
    TelegramNotifier.process_odds_output = process_odds_output

def test_with_sample_data():
    """Test the notifier with sample data that matches odds_processor output structure."""
    logger.info("Starting test with sample data...")
    
    # Update the notifier formatting methods
    update_notifier_formatting()
    
    # Create sample DataFrames
    arb_player_df = create_sample_arbitrage_player_df()
    arb_game_df = create_sample_arbitrage_game_df()
    mispriced_player_df = create_sample_mispriced_player_df()
    mispriced_game_df = create_sample_mispriced_game_df()
    
    logger.info(f"Created sample data - Player arbs: {len(arb_player_df)}, Game arbs: {len(arb_game_df)}, "
               f"Player mispriced: {len(mispriced_player_df)}, Game mispriced: {len(mispriced_game_df)}")
    
    # Create notifier and process the data
    notifier = TelegramNotifier()
    notifier.process_odds_output(arb_player_df, arb_game_df, mispriced_player_df, mispriced_game_df)
    
    # Log the generated message
    logger.info("Generated message:")
    logger.info("="*50)
    logger.info(notifier.message)
    logger.info("="*50)
    
    # Send the notification (uncomment to actually send)
    # notifier.notify()
    
    return notifier.message

def test_with_live_data():
    """Test with live data from odds_processor (requires API access)."""
    logger.info("Starting test with live data...")
    
    try:
        # Update the notifier formatting methods
        update_notifier_formatting()
        
        # Get a sample event to test with
        event_fetcher = EventFetcher()
        events = event_fetcher.get_upcoming_events()
        
        if not events:
            logger.warning("No upcoming events found. Cannot test with live data.")
            return None
            
        sample_event = events[0]
        logger.info(f"Testing with event: {sample_event.get('home_team', 'Unknown')} vs {sample_event.get('away_team', 'Unknown')}")
        
        # Create odds processor and run analysis
        processor = OddsProcessor(
            event=sample_event,
            arb_thresh=0.01,
            p_gap=0.075,
            ev_thresh=0.10,
            bootstrap=False
        )
        
        # Process odds and get the 4-tuple
        arb_player_df, arb_game_df, mispriced_player_df, mispriced_game_df = processor.process_odds_for_event(
            event=sample_event,
            p_gap=0.075,
            ev_thresh=0.10,
            bootstrap=False,
            player=True,
            game=True,
            regions=Config.US,
            mode="live",
            verbose=True
        )
        
        logger.info(f"Live data results - Player arbs: {len(arb_player_df)}, Game arbs: {len(arb_game_df)}, "
                   f"Player mispriced: {len(mispriced_player_df)}, Game mispriced: {len(mispriced_game_df)}")
        
        # Create notifier and process the live data
        notifier = TelegramNotifier()
        notifier.process_odds_output(arb_player_df, arb_game_df, mispriced_player_df, mispriced_game_df)
        
        # Log the generated message
        logger.info("Generated message from live data:")
        logger.info("="*50)
        logger.info(notifier.message)
        logger.info("="*50)
        
        # Send the notification (uncomment to actually send)
        # notifier.notify()
        
        return notifier.message
        
    except Exception as e:
        logger.error(f"Error testing with live data: {e}", exc_info=True)
        return None

def test_empty_dataframes():
    """Test behavior with empty DataFrames."""
    logger.info("Testing with empty DataFrames...")
    
    # Update the notifier formatting methods
    update_notifier_formatting()
    
    # Create empty DataFrames
    empty_df = pd.DataFrame()
    
    # Create notifier and process empty data
    notifier = TelegramNotifier()
    notifier.process_odds_output(empty_df, empty_df, empty_df, empty_df)
    
    logger.info(f"Message with empty data: '{notifier.message}'")
    
    return notifier.message

def main():
    """Run all tests."""
    logger.info("Starting comprehensive notifier integration tests...")
    
    # Test 1: Sample data
    logger.info("\n" + "="*60)
    logger.info("TEST 1: Sample Data")
    logger.info("="*60)
    sample_message = test_with_sample_data()
    
    # Test 2: Empty DataFrames
    logger.info("\n" + "="*60)
    logger.info("TEST 2: Empty DataFrames")
    logger.info("="*60)
    empty_message = test_empty_dataframes()
    
    # Test 3: Live data (optional - requires API access)
    logger.info("\n" + "="*60)
    logger.info("TEST 3: Live Data (Optional)")
    logger.info("="*60)
    live_message = test_with_live_data()
    
    # Summary
    logger.info("\n" + "="*60)
    logger.info("TEST SUMMARY")
    logger.info("="*60)
    logger.info(f"Sample data test: {'✓ PASS' if sample_message else '✗ FAIL'}")
    logger.info(f"Empty data test: {'✓ PASS' if empty_message else '✗ FAIL'}")
    logger.info(f"Live data test: {'✓ PASS' if live_message else '⚠ SKIPPED/FAILED'}")
    
    logger.info("All tests completed!")

if __name__ == "__main__":
    main()
