#!/usr/bin/env python3
"""
Test file that integrates odds_processor output with the notifier system.
This simulates the complete flow of processing odds data and sending notifications
to subscribers via Telegram.
"""

import os
import sys
import logging
from datetime import datetime

# Add src directory to path
src_path = os.path.join(os.path.dirname(__file__), 'src')
sys.path.insert(0, src_path)

from config import Config
from event_fetcher import EventFetcher
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
    
    def __init__(self, use_test_mode=True):
        """
        Initialize the tester.
        
        Args:
            use_test_mode (bool): If True, use test mode for odds processor (loads saved data).
                                 If False, fetch live data from API.
        """
        self.use_test_mode = use_test_mode
        self.event_fetcher = EventFetcher()
        self.notifier = TelegramNotifier()
        
    def get_test_events(self):
        """Get events for testing - either from API or create mock data."""
        if not self.use_test_mode:
            # Fetch real events from API
            logger.info("Fetching live events from API...")
            events = self.event_fetcher.get_events_in_next_hours(hours=24)
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
    
    def format_notification_message(self, arb_player_df, arb_game_df, mispriced_player_df, mispriced_game_df):
        """
        Format the odds processing results into a notification message.
        
        Args:
            arb_player_df, arb_game_df, mispriced_player_df, mispriced_game_df: DataFrames from odds processor
            
        Returns:
            str: Formatted message for Telegram
        """
        message_parts = []
        
        # Header
        message_parts.append("🔥 **LIVE BETTING OPPORTUNITIES** 🔥\n")
        
        # Arbitrage opportunities
        if not arb_player_df.empty or not arb_game_df.empty:
            message_parts.append("⚡ **ARBITRAGE OPPORTUNITIES** ⚡\n")
            
            if not arb_player_df.empty:
                message_parts.append("**Player Props:**")
                for _, row in arb_player_df.head(5).iterrows():  # Limit to 5 for readability
                    outcome_desc = row.get('outcome_description', 'Unknown Player')
                    market_key = row.get('market_key', 'Unknown Market')
                    over_point = row.get('over_point', 'N/A')
                    under_point = row.get('under_point', 'N/A')
                    over_bookmaker = row.get('over_bookmaker', 'Unknown')
                    under_bookmaker = row.get('under_bookmaker', 'Unknown')
                    sum_prob = row.get('sum_prob', 0)
                    profit_margin = (1 / sum_prob - 1) * 100 if sum_prob > 0 else 0
                    
                    message_parts.append(
                        f"• {outcome_desc} - {market_key}\n"
                        f"  Over {over_point} @ {over_bookmaker}\n"
                        f"  Under {under_point} @ {under_bookmaker}\n"
                        f"  **Profit: {profit_margin:.2f}%**\n"
                    )
            
            if not arb_game_df.empty:
                message_parts.append("**Game Props:**")
                for _, row in arb_game_df.head(3).iterrows():  # Limit to 3 for readability
                    market_key = row.get('market_key', 'Unknown Market')
                    over_point = row.get('over_point', 'N/A')
                    under_point = row.get('under_point', 'N/A')
                    over_bookmaker = row.get('over_bookmaker', 'Unknown')
                    under_bookmaker = row.get('under_bookmaker', 'Unknown')
                    sum_prob = row.get('sum_prob', 0)
                    profit_margin = (1 / sum_prob - 1) * 100 if sum_prob > 0 else 0
                    
                    message_parts.append(
                        f"• {market_key}\n"
                        f"  Over {over_point} @ {over_bookmaker}\n"
                        f"  Under {under_point} @ {under_bookmaker}\n"
                        f"  **Profit: {profit_margin:.2f}%**\n"
                    )
        
        # Mispriced lines
        if not mispriced_player_df.empty or not mispriced_game_df.empty:
            message_parts.append("\n💰 **MISPRICED LINES (+EV)** 💰\n")
            
            if not mispriced_player_df.empty:
                message_parts.append("**Player Props:**")
                for _, row in mispriced_player_df.head(5).iterrows():  # Limit to 5 for readability
                    outcome_desc = row.get('outcome_description', 'Unknown Player')
                    market_key = row.get('market_key', 'Unknown Market')
                    point = row.get('point', 'N/A')
                    side = row.get('side', 'Unknown')
                    bookmaker = row.get('bookmaker', 'Unknown')
                    odds = row.get('odds', 'N/A')
                    edge = row.get('edge', 0)
                    edge_pct = edge * 100 if edge else 0
                    
                    message_parts.append(
                        f"• {outcome_desc} - {market_key}\n"
                        f"  {side} {point} @ {odds} ({bookmaker})\n"
                        f"  **Edge: +{edge_pct:.1f}%**\n"
                    )
            
            if not mispriced_game_df.empty:
                message_parts.append("**Game Props:**")
                for _, row in mispriced_game_df.head(3).iterrows():  # Limit to 3 for readability
                    market_key = row.get('market_key', 'Unknown Market')
                    point = row.get('point', 'N/A')
                    side = row.get('side', 'Unknown')
                    bookmaker = row.get('bookmaker', 'Unknown')
                    odds = row.get('odds', 'N/A')
                    edge = row.get('edge', 0)
                    edge_pct = edge * 100 if edge else 0
                    
                    message_parts.append(
                        f"• {market_key}\n"
                        f"  {side} {point} @ {odds} ({bookmaker})\n"
                        f"  **Edge: +{edge_pct:.1f}%**\n"
                    )
        
        # Footer
        if not message_parts or len(message_parts) <= 1:
            message_parts = ["📊 No significant opportunities found at this time.\n\nKeep watching for updates!"]
        else:
            message_parts.append(f"\n🕒 Updated: {datetime.now().strftime('%H:%M:%S')}")
        
        return "\n".join(message_parts)
    
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
            
            # Step 3: Format message
            message = self.format_notification_message(
                arb_player_df, arb_game_df, mispriced_player_df, mispriced_game_df
            )
            
            logger.info("Formatted notification message:")
            logger.info("-" * 50)
            logger.info(message)
            logger.info("-" * 50)
            
            # Step 4: Send notification
            if self.notifier.bot:
                logger.info("Sending notification to subscribers...")
                self.notifier.notify(message)
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
        
        # Create mock DataFrames
        mock_arb_player = pd.DataFrame([{
            'outcome_description': 'LeBron James Points',
            'market_key': 'player_points',
            'over_point': 25.5,
            'under_point': 26.5,
            'over_bookmaker': 'DraftKings',
            'under_bookmaker': 'FanDuel',
            'sum_prob': 0.98,
            'over_odds': '+110',
            'under_odds': '-105'
        }])
        
        mock_mispriced_player = pd.DataFrame([{
            'outcome_description': 'Stephen Curry 3-Pointers',
            'market_key': 'player_threes',
            'point': 4.5,
            'side': 'Over',
            'bookmaker': 'BetMGM',
            'odds': '+120',
            'edge': 0.08,
        }])
        
        mock_arb_game = pd.DataFrame()
        mock_mispriced_game = pd.DataFrame()
        
        # Format and display message
        message = self.format_notification_message(
            mock_arb_player, mock_arb_game, mock_mispriced_player, mock_mispriced_game
        )
        
        logger.info("Mock data notification message:")
        logger.info("-" * 50)
        logger.info(message)
        logger.info("-" * 50)
        
        return True

def main():
    """Main function to run the notifier integration test."""
    print("🧪 Live Lines Finder - Notifier Integration Test")
    print("=" * 60)
    
    # Allow user to choose test mode
    print("\nTest Options:")
    print("1. Test with saved data (test mode)")
    print("2. Test with live API data")
    print("3. Test with mock data only")
    
    choice = input("\nEnter your choice (1-3): ").strip()
    
    if choice == "1":
        tester = NotifierIntegrationTester(use_test_mode=True)
        success = tester.test_notification_flow()
    elif choice == "2":
        tester = NotifierIntegrationTester(use_test_mode=False)
        success = tester.test_notification_flow()
    elif choice == "3":
        tester = NotifierIntegrationTester(use_test_mode=True)
        success = tester.test_with_mock_data()
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
