def implied_probability(decimal_odds):
        """Convert Decimal odds to implied probability."""
        return 1 / decimal_odds

def american_to_decimal(american_odds):
    """Convert American odds to Decimal odds."""
    if american_odds < 0:
        return (100 / abs(american_odds)) + 1
    else:
        return (american_odds / 100) + 1
        
def decimal_to_american(decimal_odds):
    if decimal_odds >= 2:
            # For positive odds: (d - 1) * 100
        return (decimal_odds - 1) * 100
    else:
            # For negative odds: -100 / (d - 1)
        return -100 / (decimal_odds - 1)