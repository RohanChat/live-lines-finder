from datetime import datetime
import glob
import os
import pandas as pd


def save_todays_events_to_csv(rows, key="player", filepath="odds_data"):
    today = datetime.utcnow().date().isoformat()
    now = datetime.utcnow().isoformat()
    if rows:
        df = pd.DataFrame(rows)
        csv_filename = f"{filepath}/nba_{key}_props_{now}.csv"
        df.to_csv(csv_filename, index=False)
        print(f"Saved data for {len(rows)} outcomes to {csv_filename}")
    else:
        print(f"No odds data was retrieved for the market.")

def load_latest_csv(filepath="odds_data/events"):
    # Find all CSV files in the folder
    csv_files = glob.glob(os.path.join(filepath, "*.csv"))
    if not csv_files:
        raise FileNotFoundError(f"No CSV files found in {filepath}")
    
    # Sort by last modified time (descending)
    latest_file = max(csv_files, key=os.path.getmtime)
    
    print(f"Loading latest file: {latest_file}")
    return pd.read_csv(latest_file)

def load_file_with_string(folder_path, match_string, filetype='csv'):
    """
    Loads the first file in the folder containing the match_string in its name.

    Parameters:
    - folder_path (str): Path to the folder.
    - match_string (str): Substring to match in the filename.
    - filetype (str): File type to load ('csv', 'json', etc.)

    Returns:
    - pd.DataFrame: Loaded DataFrame from the matching file.
    """
    for filename in os.listdir(folder_path):
        if match_string in filename and filename.endswith(f'.{filetype}'):
            filepath = os.path.join(folder_path, filename)
            if filetype == 'csv':
                return pd.read_csv(filepath)
            elif filetype == 'json':
                return pd.read_json(filepath)
            else:
                raise ValueError(f"Unsupported file type: {filetype}")
    
    raise FileNotFoundError(f"No {filetype} file found in '{folder_path}' containing '{match_string}'")