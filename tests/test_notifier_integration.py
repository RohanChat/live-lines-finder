#!/usr/bin/env python3
"""
Test file that integrates odds_processor output with the notifier system.
This simulates the complete flow of processing odds data and sending notifications
to subscribers via Telegram.
"""

import os
import sys
import logging
import pytest

pytest.skip("Notifier integration tests require external services", allow_module_level=True)
from datetime import datetime

# Add src directory to path
src_path = os.path.join(os.path.dirname(__file__), 'src')
sys.path.insert(0, src_path)

from config import Config
from feeds.the_odds_api import TheOddsAPI
from odds_processor import OddsProcessor
from notifier import TelegramNotifier
import pandas as pd

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class NotifierIntegrationTester:
    """Test class to verify the complete odds processing to notification flow."""
    
    def __init__(self, include_arbitrage=True, include_mispriced=False, links_only=True, use_test_mode=False):
        """
        Initialize the tester.
        
        Args:
            links_only (bool): If True, only include arbitrage opportunities with both over and under links.
            use_test_mode (bool): If True, use test mode for odds processor (loads saved data).
                                 If False, fetch live data from API.
        """
        self.use_test_mode = use_test_mode
        self.event_fetcher = TheOddsAPI()
        self.notifier = TelegramNotifier(include_arbitrage=include_arbitrage, include_mispriced=include_mispriced, links_only=links_only)
        logger.info(f"Notifier initialized with arbitrage={include_arbitrage}, mispriced={include_mispriced}, links_only={links_only}")
        
    def get_test_events(self):
        """Get events for testing - either from API or create mock data."""
        if not self.use_test_mode:
            # Fetch real events from API
            logger.info("Fetching live events from API...")
            events = self.event_fetcher.get_events_between_hours()
            if not events:
                logger.warning("No live events found. Creating mock event for testing.")
                return self.create_mock_event()
            return events[:1]  # Use just the first event for testing
        else:
            # Create a mock event for testing with saved data
            logger.info("Using mock event for test mode...")
            return self.create_mock_event()
    
    def create_mock_event(self):
        """Create a mock event for testing purposes."""
        return [{
            "id": "test_event_123",
            "sport_key": "basketball_nba",
            "sport_title": "NBA",
            "commence_time": "2025-01-23T01:30:00Z",
            "home_team": "Los Angeles Lakers",
            "away_team": "Boston Celtics"
        }]
    
    def process_odds_data(self, events):
        """
        Process odds data for the given events.
        
        Args:
            events (list): List of event dictionaries
            
        Returns:
            tuple: (arb_player_df, arb_game_df, mispriced_player_df, mispriced_game_df)
        """
        if not events:
            logger.error("No events provided for odds processing")
            return pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame()
        
        # Use the first event for testing
        event = events[0]
        logger.info(f"Processing odds for event: {event['home_team']} vs {event['away_team']}")
        
        # Initialize odds processor
        odds_processor = OddsProcessor(
            event=event,
            arb_thresh=0.01,
            p_gap=0.075,
            ev_thresh=0.10,
            bootstrap=False
        )
        
        # Set mode based on whether we're using test data
        mode = "test" if self.use_test_mode else "live"
        
        try:
            # Process odds data
            results = odds_processor.process_odds_for_event(
                event=event,
                p_gap=0.075,
                ev_thresh=0.10,
                bootstrap=False,
                arb_thresh=0.01,
                player=True,
                game=True,
                regions=Config.US,
                mode=mode,
                filepath="odds_data",
                verbose=True
            )
            
            arb_player_df, arb_game_df, mispriced_player_df, mispriced_game_df = results
            
            # Log results summary
            logger.info(f"Arbitrage opportunities found - Player: {len(arb_player_df)}, Game: {len(arb_game_df)}")
            logger.info(f"Mispriced lines found - Player: {len(mispriced_player_df)}, Game: {len(mispriced_game_df)}")
            
            return arb_player_df, arb_game_df, mispriced_player_df, mispriced_game_df
            
        except Exception as e:
            logger.error(f"Error processing odds data: {e}", exc_info=True)
            return pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame()
    
    def test_notification_flow(self):
        """Test the complete notification flow."""
        logger.info("Starting notification flow test...")
        
        try:
            # Step 1: Get events
            events = self.get_test_events()
            if not events:
                logger.error("No events available for testing")
                return False
            
            # Step 2: Process odds data
            arb_player_df, arb_game_df, mispriced_player_df, mispriced_game_df = self.process_odds_data(events)
            
            # Log DataFrame summaries
            logger.info(f"DataFrames received:")
            logger.info(f"  - Arbitrage Player: {len(arb_player_df)} rows")
            logger.info(f"  - Arbitrage Game: {len(arb_game_df)} rows")
            logger.info(f"  - Mispriced Player: {len(mispriced_player_df)} rows")
            logger.info(f"  - Mispriced Game: {len(mispriced_game_df)} rows")
            
            # Step 3: Use the notifier's formatting methods
            logger.info("Using notifier's built-in formatting methods...")
            self.notifier.process_dfs(arb_player_df, arb_game_df, mispriced_player_df, mispriced_game_df)
            message = self.notifier.message
            
            if message:
                logger.info("Formatted notification message:")
                logger.info("-" * 50)
                logger.info(message)
                logger.info("-" * 50)
            else:
                logger.warning("No message generated from DataFrames")
                return False
            
            # Step 4: Send notification
            if self.notifier.bot:
                logger.info("Sending notification to subscribers...")
                self.notifier.notify()  # This will use the already formatted message
                logger.info("Notification sent successfully!")
            else:
                logger.warning("Telegram bot not configured. Message formatted but not sent.")
                logger.info("To enable notifications, set TELEGRAM_BOT_TOKEN in your environment.")
            
            return True
            
        except Exception as e:
            logger.error(f"Error in notification flow test: {e}", exc_info=True)
            return False

    def test_with_mock_data(self):
        """Test with mock data to ensure message formatting works."""
        logger.info("Testing with mock data...")
        
        try:
            # Create mock DataFrames
            mock_arb_player = pd.DataFrame([{
                'outcome_description': 'LeBron James Points',
                'market_key': 'player_points',
                'over_point': [25.5],  # Make this an array to test your array handling
                'under_point': [26.5],
                'over_bookmaker': 'DraftKings',
                'under_bookmaker': 'FanDuel',
                'sum_prob': 0.98,
                'over_odds': '+110',
                'under_odds': '-105',
                'links': ['https://draftkings.com', 'https://fanduel.com']  # Add links
            }])
            
            mock_mispriced_player = pd.DataFrame([{
                'outcome_description': 'Stephen Curry 3-Pointers',
                'market_key': 'player_threes',
                'point': [4.5],  # Make this an array to test your array handling
                'side': 'Over',
                'bookmaker': 'BetMGM',
                'odds': '+120',
                'edge': 0.08,
                'links': ['https://betmgm.com']  # Add links
            }])
            
            mock_arb_game = pd.DataFrame()
            mock_mispriced_game = pd.DataFrame()
            
            # Use the notifier's formatting methods instead of custom formatting
            logger.info("Processing mock data with notifier's formatting methods...")
            self.notifier.process_dfs(mock_arb_player, mock_arb_game, mock_mispriced_player, mock_mispriced_game)
            message = self.notifier.message
            
            if message:
                logger.info("Mock data notification message:")
                logger.info("-" * 50)
                logger.info(message)
                logger.info("-" * 50)
                logger.info("✅ Mock data test completed successfully!")
                return True
            else:
                logger.error("❌ No message generated from mock data")
                return False
                
        except Exception as e:
            logger.error(f"Error in mock data test: {e}", exc_info=True)
            return False
        

def test_links_only_comparison():
    """Test to compare output with and without links_only mode."""
    logger.info("Testing links_only mode comparison...")
    
    try:
        # Create mock arbitrage data with some entries having links and some not
        mock_arb_with_links = pd.DataFrame([
            {
                'outcome_description': 'LeBron James Points',
                'market_key': 'player_points',
                'over_point': [25.5],
                'under_point': [26.5],
                'over_bookmaker': 'DraftKings',
                'under_bookmaker': 'FanDuel',
                'sum_prob': 0.98,
                'over_odds': '+110',
                'under_odds': '-105',
                'over_link': 'https://draftkings.com/bet1',
                'under_link': 'https://fanduel.com/bet1'
            },
            {
                'outcome_description': 'Stephen Curry 3-Pointers',
                'market_key': 'player_threes',
                'over_point': [4.5],
                'under_point': [4.5],
                'over_bookmaker': 'BetMGM',
                'under_bookmaker': 'Caesars',
                'sum_prob': 0.97,
                'over_odds': '+120',
                'under_odds': '-110',
                'over_link': '',  # Empty link
                'under_link': 'https://caesars.com/bet2'  # Only under link
            },
            {
                'outcome_description': 'Giannis Antetokounmpo Rebounds',
                'market_key': 'player_rebounds',
                'over_point': [11.5],
                'under_point': [11.5],
                'over_bookmaker': 'PointsBet',
                'under_bookmaker': 'Unibet',
                'sum_prob': 0.96,
                'over_odds': '+105',
                'under_odds': '-115',
                'over_link': None,  # Null link
                'under_link': None  # Null link
            }
        ])
        
        empty_dfs = [pd.DataFrame(), pd.DataFrame()]
        
        # Test with links_only=False (should show all opportunities)
        logger.info("\n" + "="*60)
        logger.info("TESTING WITH links_only=False (show all opportunities)")
        logger.info("="*60)
        
        notifier_all = TelegramNotifier(include_arbitrage=True, include_mispriced=False, links_only=False)
        notifier_all.process_dfs(mock_arb_with_links, *empty_dfs)
        message_all = notifier_all.message
        
        if message_all:
            logger.info("Message with links_only=False:")
            logger.info("-" * 50)
            logger.info(message_all)
            logger.info("-" * 50)
        
        # Test with links_only=True (should only show opportunities with both links)
        logger.info("\n" + "="*60)
        logger.info("TESTING WITH links_only=True (only opportunities with both links)")
        logger.info("="*60)
        
        notifier_links_only = TelegramNotifier(include_arbitrage=True, include_mispriced=False, links_only=True)
        notifier_links_only.process_dfs(mock_arb_with_links, *empty_dfs)
        message_links_only = notifier_links_only.message
        
        if message_links_only:
            logger.info("Message with links_only=True:")
            logger.info("-" * 50)
            logger.info(message_links_only)
            logger.info("-" * 50)
        else:
            logger.info("No message generated with links_only=True (expected if no entries have both links)")
        
        # Compare results
        logger.info("\n" + "="*60)
        logger.info("COMPARISON SUMMARY")
        logger.info("="*60)
        
        all_count = message_all.count('💰') if message_all else 0
        links_only_count = message_links_only.count('💰') if message_links_only else 0
        
        logger.info(f"Opportunities found with links_only=False: {all_count}")
        logger.info(f"Opportunities found with links_only=True: {links_only_count}")
        logger.info(f"Filtered out: {all_count - links_only_count}")
        
        if all_count > links_only_count:
            logger.info("✅ links_only mode successfully filtered out opportunities without both links")
        elif all_count == links_only_count and all_count > 0:
            logger.info("ℹ️ All opportunities had both links - no filtering occurred")
        else:
            logger.info("ℹ️ No opportunities found in either mode")
        
        return True
        
    except Exception as e:
        logger.error(f"Error in links_only comparison test: {e}", exc_info=True)
        return False
        

def main():
    """Main function to run the notifier integration test."""
    print("🧪 Live Lines Finder - Notifier Integration Test")
    print("=" * 60)
    
    # Allow user to choose test mode
    print("\nTest Options:")
    print("1. Test with saved data (test mode)")
    print("2. Test with live API data")
    print("3. Test with mock data only")
    print("4. Test links_only mode comparison")
    
    choice = input("\nEnter your choice (1-4): ").strip()
    
    if choice == "1":
        tester = NotifierIntegrationTester(use_test_mode=True)
        success = tester.test_notification_flow()
    elif choice == "2":
        tester = NotifierIntegrationTester(use_test_mode=False)
        success = tester.test_notification_flow()
    elif choice == "3":
        tester = NotifierIntegrationTester(use_test_mode=True)
        success = tester.test_with_mock_data()
    elif choice == "4":
        success = test_links_only_comparison()
    else:
        print("Invalid choice. Defaulting to test mode.")
        tester = NotifierIntegrationTester(use_test_mode=True)
        success = tester.test_notification_flow()
    
    if success:
        print("\n✅ Test completed successfully!")
    else:
        print("\n❌ Test failed. Check logs for details.")
    
    # Display configuration info
    print("\n📋 Configuration Status:")
    print(f"  - Telegram Bot Token: {'✅ Configured' if Config.TELEGRAM_BOT_TOKEN else '❌ Not configured'}")
    print(f"  - Database URL: {'✅ Configured' if Config.DATABASE_URL else '❌ Not configured'}")
    print(f"  - Stripe API Key: {'✅ Configured' if Config.STRIPE_SECRET_KEY else '❌ Not configured'}")

if __name__ == "__main__":
    main()
