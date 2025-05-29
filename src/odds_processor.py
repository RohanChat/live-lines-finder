import ast
from datetime import datetime, timezone
import os
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from sklearn.isotonic import IsotonicRegression
from scipy.interpolate import PchipInterpolator

from utils.file_utils import load_file_with_string
from config import Config
from itertools import zip_longest   # handles uneven list lengths
from collections.abc import Iterable
from itertools import product
from event_fetcher import EventFetcher

class OddsProcessor:
    """Process and plot prop markets for an event"""

    def __init__(self, event, arb_thresh = 0.01, p_gap: float = 0.075, ev_thresh: float = 0.10, bootstrap: bool = False):
        self.event     = event
        self.arb_thresh  = arb_thresh
        self.p_gap     = p_gap
        self.ev_thresh = ev_thresh
        self.bootstrap = bootstrap
        self.event_fetcher = EventFetcher()



    def create_flattened_props(self, df, description=None, market_key=None, blank_link=""):
        """
        Explode the wide prop DataFrame into long format, one quote per row,
        WITHOUT dropping rows when 'link' (or any other list column) is shorter.

        Parameters
        ----------
        df            : wide DataFrame (lists in each cell)
        description   : optional filter on outcome_description
        market_key    : optional filter on market_key
        blank_link    : what to put when a quote has no link (default "")
                        use None if you prefer actual None values
        """
        # -------- 1) subset rows if filters are supplied --------
        if description is None and market_key is None:
            sub = df
        elif description is not None and market_key is None:
            sub = df[df["outcome_description"] == description]
        elif description is None and market_key is not None:
            sub = df[df["market_key"] == market_key]
        else:
            sub = df[
                (df["outcome_description"] == description) &
                (df["market_key"]          == market_key)
            ]

        # -------- 2) explode each row robustly -----------------
        records = []
        for _, row in sub.iterrows():
            n       = len(row["outcome_name"])          # always use this as master length
            desc    = row["outcome_description"]
            mkey    = row["market_key"]
            point   = row["outcome_point"]

            # Use zip_longest so shorter lists are padded
            for side, prob, bookmaker, odds, mtype, link in zip_longest(
                row.get("outcome_name",            []),
                row.get("implied_probability",     []),
                row.get("bookmaker_key",           []),
                row.get("outcome_price",           []),
                row.get("markets",                 []),
                row.get("link",                    []),
                fillvalue=None
            ):
                # Normalise missing link value
                link = link if link is not None else blank_link

                records.append({
                    "outcome_description": desc,
                    "market_key":          mkey,
                    "point":               point,
                    "side":                side,
                    "prob":                prob,
                    "bookmaker":           bookmaker,
                    "odds":                odds,
                    "market_type":         mtype,
                    "link":                link,
                })

        return pd.DataFrame(records)

    def plot_prop_market(
        self,
        df,
        description,
        market_key,
        hide_overs: bool = False,
        hide_unders: bool = False,
        cdf: bool = False,
        alt_cdf: bool = False
    ):
        # 1) build the flat props table
        long_df = self.create_flattened_props(df, description, market_key)
        print(long_df)
        long_df = long_df.drop(columns=['bookmaker', 'odds', 'market_type'])

        # 2) optional filtering
        if hide_overs:
            long_df = long_df[long_df['side']=='Under']
        if hide_unders:
            long_df = long_df[long_df['side']=='Over']

        # 3) scatter raw quotes
        plt.figure()
        color_map = {'Over':'red', 'Under':'blue'}
        colors = long_df['side'].map(color_map)
        plt.scatter(
            long_df['point'],
            long_df['prob'],
            c=colors,
            alpha=0.7,
            edgecolors='k',
            linewidths=0.5
        )
        # legend entries
        for side, col in color_map.items():
            if (side=='Over' and not hide_overs) or (side=='Under' and not hide_unders):
                plt.scatter([], [], c=col, label=side)
        
        # 4) build combined (x, y) for logistic fitting
        fit_df = long_df.copy()
        # Under = CDF, Over = 1 - CDF
        fit_df['y_cdf'] = np.where(
            fit_df['side']=='Under',
            fit_df['prob'],
            1 - fit_df['prob']
        )
        # clamp for stability
        fit_df['y_cdf'] = fit_df['y_cdf'].clip(1e-6, 1-1e-6)
        x = fit_df['point'].values
        logit_y = np.log(fit_df['y_cdf'] / (1 - fit_df['y_cdf']))

        # 5) fit logit(y) ≈ α + β·x
        β, α = np.polyfit(x, logit_y, 1)
        x_fit = np.linspace(x.min(), x.max(), 200)
        p_cdf_fit = 1 / (1 + np.exp(-(α + β * x_fit)))

        if cdf:

            # 6) plot the single logistic‐CDF curve
            plt.plot(
                x_fit, p_cdf_fit,
                color='green',
                linewidth=2,
                label='Logistic CDF Fit'
            )

        if alt_cdf:
            # 7) compute and plot 1−CDF (survival function)
            p_ccdf_fit = 1 - p_cdf_fit
            plt.plot(
                x_fit, p_ccdf_fit,
                color='orange',
                linestyle='--',
                linewidth=2,
                label='1 − CDF'
            )

        # # 8) compute and plot PDF of the logistic
        # #    pdf(x) = β * F(x) * (1−F(x))
        # p_pdf_fit = β * p_cdf_fit * (1 - p_cdf_fit)
        # plt.plot(
        #     x_fit, p_pdf_fit,
        #     color='purple',
        #     linestyle=':',
        #     linewidth=2,
        #     label='PDF'
        # )

        # 9) then finalize as before
        plt.xlabel('Outcome Point')
        plt.ylabel('Probability')
        plt.title(f"{description} — {market_key}")
        plt.legend(title='Side')
        plt.show()
    
    def safe_parse(self, value):
        """
        Ensure the value is a list.
        If it's already a list, return it.
        If it's a string representation of a list, safely parse it.
        Otherwise, wrap it in a list.
        """
        if isinstance(value, list):
            return value
        if isinstance(value, str):
            try:
                parsed = ast.literal_eval(value)
                if isinstance(parsed, list):
                    return parsed
            except Exception as e:
                pass
        # If not iterable, wrap it in a list.
        return [value]

    def implied_probability(self, decimal_odds):
        """Convert Decimal odds to implied probability."""
        return 1 / decimal_odds

    def american_to_decimal(self, american_odds):
        """Convert American odds to Decimal odds."""
        if american_odds < 0:
            return (100 / abs(american_odds)) + 1
        else:
            return (american_odds / 100) + 1
        
    def decimal_to_american(self, decimal_odds):
        if decimal_odds >= 2:
            # For positive odds: (d - 1) * 100
            return (decimal_odds - 1) * 100
        else:
            # For negative odds: -100 / (d - 1)
            return -100 / (decimal_odds - 1)

    def calculate_vig_for_row(self, row, mode="under_over"):
        if mode == "under_over":
            implied_probability_list = []
            vig_list = []
            market_key = row.market_key
            # check if market key contains '3_way'
            outcome_description = row.outcome_description
            if '3_way' in market_key:
                for i in range(0, len(row.outcome_name), 3):
                    home, draw, away = row.outcome_name[i:i+3]
                    home_odds, draw_odds, away_odds = row.outcome_price[i:i+3]
                    
                    # convert American odds → decimal → implied probabilities
                    p_home = self.implied_probability(self.american_to_decimal(home_odds))
                    p_draw = self.implied_probability(self.american_to_decimal(draw_odds))
                    p_away = self.implied_probability(self.american_to_decimal(away_odds))
                    
                    total_p = p_home + p_draw + p_away
                    vig     = total_p - 1.0
                    
                    # no-vig probabilities are each share of the total
                    implied_probability_list += [
                        p_home / total_p,
                        p_draw / total_p,
                        p_away / total_p
                    ]
                    # each outcome has the same vig
                    vig_list += [vig, vig, vig]
            else:
                for i in range(0, len(row.outcome_name) - 1, 2):
                    bookmaker_key = row.bookmaker_key[i]
                    over = row.outcome_name[i]
                    under = row.outcome_name[i+1]
                    over_odds = row.outcome_price[i]
                    under_odds = row.outcome_price[i+1]
                    over_imp_probability = self.implied_probability(self.american_to_decimal(over_odds))
                    under_implied_probability = self.implied_probability(self.american_to_decimal(under_odds))
                    total_probability = over_imp_probability + under_implied_probability

                    vig = total_probability - 1
                    over_vig = over_imp_probability / total_probability
                    under_vig = under_implied_probability / total_probability
                    # print(f"For {bookmaker_key}, {outcome_description}, {market_key}, Vig is {vig} and No-vig is {over_vig} and {under_vig}")
                    implied_probability_list.append(over_vig)
                    implied_probability_list.append(under_vig)
                    vig_list.append(vig)
                    vig_list.append(vig)
        else:
            implied_probability_list = []
            vig_list = []
            market_key = row.market_key
            outcome_description = row.outcome_description
            for i in range(0, len(row.outcome_name)):
                bookmaker_key = row.bookmaker_key[i]
                prop = row.outcome_name[i]
                odds = row.outcome_price[i]
                vig = 0.05
                imp_probability = self.implied_probability(self.american_to_decimal(odds)) - (vig/2)
                # print(f"For {bookmaker_key}, {outcome_description}, {market_key}, Vig is {vig} and No-vig is {over_vig} and {under_vig}")
                implied_probability_list.append(imp_probability)
                vig_list.append(vig)

        return pd.Series({
            "implied_probability": implied_probability_list,
            "vig": vig_list
        })
    

    def calculate_vig_and_no_vig(self, arranged_df, mode="under_over"):
        """
        Calculate the vig and vig‐free implied probabilities
        for each row in arranged_df.
        """
        # apply with the correct mode
        arranged_df[["implied_probability","vig"]] = arranged_df.apply(
            lambda row: self.calculate_vig_for_row(row, mode=mode),
            axis=1
        )
        return arranged_df

    def calculate_arbitrage_for_row(self, row, arb_threshold=0.02):
        # Input:
        # - row: pandas row --> Pandas dataframe row to process 
        # - arb_threshold: float -> Minimum arbitrage value to consider
        # Output:
        # - arbitrage: Pd.Series --> Pandas series of arbitrage values
        if row.outcome_point is None or row.outcome_point == "" or row.outcome_point == "None":
            return None
        outcome_names = self.safe_parse(row.outcome_name)
        outcome_prices = self.safe_parse(row.outcome_price)
        bookmaker_keys = self.safe_parse(row.bookmaker_key)
        # Outcome_point should be homogeneous; take the first value.
        outcome_points = self.safe_parse(row.outcome_point)
        links = self.safe_parse(row.link)

        # can you combine all these print's below into one line print statement?
        
        # print(f"Player props for {row.outcome_description}: Market key: {row.market_key}, Outcome names: {outcome_names}, Outcome prices: {outcome_prices}, Bookmaker keys: {bookmaker_keys}, Outcome points: {outcome_points}")

        # print("Length for", row.outcome_description + ":" + row.market_key,
        #         "\noutcome_names:", len(outcome_names),
        #         "\noutcome_prices:", len(outcome_prices),
        #         "\nbookmaker_keys:", len(bookmaker_keys),
        #         "\noutcome_points:", len(outcome_points))

        try:
            line = float(outcome_points[0])
        except ValueError:
            line = None 
        
        odds_data = []
        for i in range(len(outcome_names)):
            outcome_name = outcome_names[i]
            outcome_price = outcome_prices[i]
            bookmaker_key = bookmaker_keys[i]
            outcome_point = outcome_points[0]
            link = links[i]
            odds_data.append({
                "market_key": row.market_key,
                "outcome_description": row.outcome_description,
                "outcome_name": str(outcome_name).lower().strip(),
                "outcome_price": outcome_price,
                'decimal': self.american_to_decimal(outcome_price),
                "bookmaker_key": bookmaker_key,
                "outcome_point": outcome_point,
                "link": link
            })
        
        overs = [d for d in odds_data if d["outcome_name"] == "over"]
        unders = [d for d in odds_data if d["outcome_name"] == "under"]

        if len(overs) == 0 or len(unders) == 0:
            return None
        else:
            best_over_data = max(overs, key=lambda d: d["decimal"])
            best_under_data = max(unders, key=lambda d: d["decimal"])
            best_over = best_over_data["decimal"]
            best_under = best_under_data["decimal"]
            best_over_am = best_over_data['outcome_price']
            best_under_am = best_under_data['outcome_price']

            arb_sum = (1 / best_over) + (1 / best_under)
            if arb_sum < 1:
                profit_margin = (1 / arb_sum) - 1
                if profit_margin < arb_threshold:
                    profit_margin = 0
                
            else:
                profit_margin = 0
                
            # outcome_point is already the same for the group; take first value.
            outcome_points = self.safe_parse(row.outcome_point)
            try:
                line = float(outcome_points[0])
            except Exception:
                line = np.nan
            
            return pd.Series({
                "arb_profit_margin": profit_margin,
                "arb_sum": arb_sum,
                "line": line,
                "best_over": best_over,
                "best_under": best_under,
                "best_over_am": best_over_am,
                "best_under_am": best_under_am,
                "bookmaker_over": best_over_data["bookmaker_key"],
                "bookmaker_under": best_under_data["bookmaker_key"],
                "index_of_best_over": overs.index(best_over_data),
                "index_of_best_under": unders.index(best_under_data)
            })
        
    def add_expected_probabilities(self, df: pd.DataFrame, mode="player") -> pd.DataFrame:
        """
        Robust version that works even when `outcome_name` and
        `implied_probability` lists have different lengths.

        Returns the original DataFrame with a new column 'exp_prob'
        (list parallel to outcome_name).
        """
        records = []          # tidy rows to fit on
        sub_idx = []          # position of quote within its original row

        for idx, row in df.iterrows():
            names = row.get("outcome_name", [])
            probs = row.get("implied_probability", [])
            pts   = row.get("outcome_point", [])   # ← this is your list of signed points

            raw_pts = row.get("outcome_point", [])
            if isinstance(raw_pts, list):
                pts = raw_pts
            else:
                # broadcast scalar → list for player (or any) mode
                pts = [raw_pts] * max(len(names), len(probs))

            # Ensure we have real lists
            if not (isinstance(names, list) and isinstance(probs, list) and isinstance(pts, list)):
                continue

            # explode side ↔ prob ↔ signed-point together
            for j, (side, prob, pt) in enumerate(zip(names, probs, pts)):
                if pd.isna(prob) or pd.isna(pt):
                    continue
                records.append({
                    "orig_index":          idx,
                    "sub_idx":             j,
                    "side":                side,
                    "prob":                float(prob),
                    "outcome_point":       float(pt),               # ← now includes ±spread
                    "outcome_description": row["outcome_description"],
                    "market_key":          row["market_key"],
                })


        if not records:                       # nothing to process
            df["exp_prob"] = [[] for _ in df.index]
            return df

        tidy = pd.DataFrame.from_records(records)

        # ---- fit & add expected probabilities ----
        if mode == "game":
            # group all of a given game‐level market together
            key_cols = ["market_key"]
        else:
            # for player props we still split by description + market
            key_cols = ["outcome_description", "market_key"]
        tidy = (
            tidy
            .groupby(key_cols, group_keys=False)
            .apply(lambda group: self._add_exp_prob_to_group(group, mode=mode))
        )

        # ---- collect back into list per original row ----
        tidy_sorted = tidy.sort_values(["orig_index", "sub_idx"])
        exp_dict    = tidy_sorted.groupby("orig_index")["exp_prob"].apply(list).to_dict()

        df = df.copy()
        df["exp_prob"] = [exp_dict.get(i, []) for i in df.index]

        return df

    def calculate_ev(self, df):
        """
        Given a DataFrame with columns
        - market_key, point, side, prob  (vig-free implied prob)
        fits a logistic CDF p_fit(point) per (market_key, side)
        and returns the original df augmented with:
        - p_fit     : fitted "fair" probability at that point
        - ev_global : p_fit / prob - 1
        """
        # 1) per-strike median
        med = (
            df
            .groupby(["market_key", "side", "point"], as_index=False)["prob"]
            .median()
            .rename(columns={"prob": "p_star"})
        )

        # 2) logit transform
        med["logit_p"] = np.log(med["p_star"] / (1 - med["p_star"]))

        # 3) fit & predict per (market_key, side)
        fits = []
        for (mkt, side), sub in med.groupby(["market_key", "side"], sort=False):
            # fit logit_p ≈ α + β·point
            β, α = np.polyfit(sub["point"], sub["logit_p"], 1)
            sub = sub.copy()
            sub["p_fit"] = 1 / (1 + np.exp(-(α + β * sub["point"])))
            fits.append(sub[["market_key", "side", "point", "p_fit"]])
        fit_df = pd.concat(fits, ignore_index=True)

        # 4) merge back and compute EV
        out = df.merge(fit_df, on=["market_key", "side", "point"], how="left")
        out["ev_global"] = out["p_fit"] / out["prob"] - 1

        return out
    
    def merge_prop_dfs(self, alt_df: pd.DataFrame, reg_df: pd.DataFrame, mode="player") -> pd.DataFrame:

        df1 = alt_df.copy()
        df2 = reg_df.copy()

        df1['markets'] = df1['outcome_price'].apply(lambda prices: ['alternate'] * len(prices))
        df2['markets'] = df2['outcome_price'].apply(lambda prices: ['under_over'] * len(prices))

        if mode == "player":
            df1['market_key'] = alt_df['market_key'].str[:-10]

        elif mode == "game":
            df1['market_key'] = df1['market_key'].apply(lambda s: s[10:] if 'alternate' in s else s)

        # 1) Which columns are our "list-of-things" columns?
        list_cols = [
            'outcome_name',
            'bookmaker_key',
            'outcome_price',
            'implied_probability',
            'vig',
            'markets'
        ]

        if mode == "player":
            key_outcome = 'outcome_point'
        elif mode == "game":
            key_outcome = 'abs_point'
        
        # 2) Build the full superset of columns
        all_cols = set(df1.columns) | set(df2.columns)
        key_cols = ['outcome_description', 'market_key', key_outcome]
        scalar_cols = [c for c in all_cols if c not in key_cols + list_cols]
        
        # 3) Concatenate the two frames end-to-end
        df = pd.concat([df1, df2], ignore_index=True, sort=False)
        
        # 4) Ensure every "list-col" exists and is a Python list
        for col in list_cols:
            if col not in df:
                df[col] = [[] for _ in range(len(df))]
            else:
                def to_list(x):
                    if isinstance(x, list):
                        return x
                    if isinstance(x, (tuple, np.ndarray, pd.Series)):
                        return list(x)
                    return [x]
                df[col] = df[col].apply(to_list)
        
        # 5) Make sure every scalar column exists
        for col in scalar_cols:
            if col not in df:
                df[col] = np.nan
        
        # 6) Group & rebuild each row
        merged_rows = []
        for keys, group in df.groupby(key_cols, as_index=False):
            row = dict(zip(key_cols, keys))
            
            # flatten each list-col
            for col in list_cols:
                # sum(list_of_lists, []) flattens them
                row[col] = sum(group[col].tolist(), [])
            
            # take “first non-null” for scalars
            for col in scalar_cols:
                non_null = group[col].dropna()
                row[col] = non_null.iloc[0] if not non_null.empty else np.nan
            
            merged_rows.append(row)
        
        return pd.DataFrame(merged_rows)
    
    def _fit_monotone_cdf(self, x, y):
        """Return a callable CDF fitted with Isotonic → PCHIP smoothing."""
        iso = IsotonicRegression(out_of_bounds="clip").fit(x, y)
        y_iso = iso.predict(x)
        return PchipInterpolator(x, y_iso, extrapolate=True)  # CDF(x)

    def _row_exp_prob(self, point, side, cdf):
        """Fair P(Over) / P(Under) given the fitted CDF."""
        p_cdf = float(cdf(point))
        return 1.0 - p_cdf if side.lower() == "over" else p_cdf

    def _add_exp_prob_to_group(self, group: pd.DataFrame, mode="game") -> pd.DataFrame:
        # 1) if it’s a moneyline, just copy each bookie's own implied probability
        if group["market_key"].iat[0] == "h2h":
            avg = group.groupby("side", as_index=False)["prob"].mean()
            # map that back onto each row
            out = group.copy()
            out["exp_prob"] = out["side"].map(avg.set_index("side")["prob"])
            return out

        # 2) otherwise—spread, totals, etc.—do your normal CDF‐fitting…
        pts   = group["outcome_point"].astype(float).to_numpy()
        probs = group["prob"].astype(float).to_numpy()
        raw   = group["side"].str.lower().to_numpy()

        side = np.where(
            np.isin(raw, ["under", "over"]),
            raw,
            np.where(pts < 0, "over", "under")
        )

        y_cdf = np.where(side == "under", probs, 1.0 - probs)

        df_tmp   = (pd.DataFrame({"x": pts, "y": y_cdf})
                    .groupby("x", sort=True, as_index=False)
                    .mean()
                    .sort_values("x"))
        x_unique = df_tmp["x"].to_numpy()
        y_unique = df_tmp["y"].to_numpy()

        if len(x_unique) >= 2:
            cdf = self._fit_monotone_cdf(x_unique, y_unique)
            exp = [self._row_exp_prob(pt, sd, cdf) for pt, sd in zip(pts, side)]
        else:
            single_p = float(y_unique[0])
            exp = [single_p if s == "under" else 1.0 - single_p for s in side]

        out = group.copy()
        out["exp_prob"] = exp
        return out

    def find_player_arbs(self, df, threshold=0.01):
        # if 'side' not in df.columns or df.empty:
        #     print(df.head(5))
        #     return None
        # Separate Over and Under sides
        overs = df[df['side'].str.lower() == 'over'].reset_index(drop=True)
        unders = df[df['side'].str.lower() == 'under'].reset_index(drop=True)
        
        arb_opps = []

        # Loop through all combinations of over and under bets
        for over_idx, under_idx in product(overs.index, unders.index):
            over_row = overs.loc[over_idx]
            under_row = unders.loc[under_idx]
            
            # Arbitrage condition: Under point >= Over point AND total prob < 1
            under_real_prob = 1/self.american_to_decimal(under_row['odds'])
            over_real_prob = 1/self.american_to_decimal(over_row['odds'])
            if under_row['point'] >= over_row['point'] and (under_real_prob + over_real_prob)  < (1-threshold):
                arb_opps.append({
                    'outcome_description': over_row['outcome_description'],
                    'market_key': over_row['market_key'],
                    'over_point': over_row['point'],
                    'under_point': under_row['point'],
                    'over_prob': over_row['prob'],
                    'under_prob': under_row['prob'],
                    'sum_prob': over_row['prob'] + under_row['prob'],
                    'over_bookmaker': over_row['bookmaker'],
                    'over_market': over_row['market_type'],
                    'under_market': under_row['market_type'],
                    'under_bookmaker': under_row['bookmaker'],
                    'over_odds': over_row['odds'],
                    'under_odds': under_row['odds'],
                    'over_link': over_row['link'],
                    'under_link': under_row['link'],
                })

        return pd.DataFrame(arb_opps)

    def safe_find_player_arbs(self, group, threshold=0.01):
        try:
            return self.find_player_arbs(group, threshold)
        except Exception as e:
            print(f"Error in group: {group[['outcome_description', 'market_key']].drop_duplicates().to_dict('records')}")
            print(e)
            return None
        
    def find_all_player_arbs(self, df, threshold=0.01):
        # build a fully‑flattened master table
        flat_df_list = []
        for (player, market), grp in df.groupby(
                ['outcome_description', 'market_key']):
            flat_df_list.append(self.create_flattened_props(grp, player, market))

        flat_props = pd.concat(flat_df_list, ignore_index=True)

        # now every slice *already* has 'side'
        arb_df = (flat_props
                .groupby(['outcome_description', 'market_key'])
                .apply(self.safe_find_player_arbs, threshold=threshold)
                .reset_index(drop=True))

        return arb_df
    

    def _bootstrap_cis(self, group: pd.DataFrame, B=100, alpha=0.05):
        """
        Bootstrap (1‑alpha) CIs for the fitted probability *per quote*.
        Expects columns: outcome_point | side | prob_mkt
        """
        x_all  = group["outcome_point"].to_numpy()
        sd_all = group["side"].str.lower().to_numpy()
        n      = len(group)

        mat = np.empty((B, n), dtype=float)

        for b in range(B):
            boot = group.sample(n, replace=True)

            # Convert to CDF scale
            y_cdf = np.where(
                boot["side"].str.lower() == "under",
                boot["prob_mkt"].to_numpy(),
                1.0 - boot["prob_mkt"].to_numpy()
            )

            # Collapse duplicates
            tmp = (
                pd.DataFrame({"x": boot["outcome_point"].to_numpy(), "y": y_cdf})
                .groupby("x", as_index=False)
                .mean()
                .sort_values("x")
            )
            x_unique, y_unique = tmp["x"].to_numpy(), tmp["y"].to_numpy()

            # ---------- guard: only one unique strike ----------
            if len(x_unique) < 2:
                # print("only one unique strike: using empirical CDF")
                single_p_under = float(y_unique[0])

                # expected prob for every quote in this resample
                mat[b, :] = [
                    single_p_under if s == "under" else 1.0 - single_p_under
                    for s in sd_all
                ]
                continue
            # ---------------------------------------------------

            # Normal case: fit monotone CDF
            cdf = self._fit_monotone_cdf(x_unique, y_unique)
            mat[b, :] = [self._row_exp_prob(pt, s, cdf) for pt, s in zip(x_all, sd_all)]

        lower = np.percentile(mat, 100 * alpha/2, axis=0)
        upper = np.percentile(mat, 100 * (1-alpha/2), axis=0)
        return lower, upper


    # ---------- main mispricing wrapper ----------
    def flag_mispriced_lines(self, df, p_gap=0.05, ev_thresh=0.1, bootstrap=False):
        """
        Parameters
        ----------
        df : DataFrame  (already has exp_prob column!)
        p_gap      : absolute probability gap threshold
        ev_thresh  : edge % threshold
        bootstrap  : bool, whether to compute 95% CIs

        Returns
        -------
        DataFrame identical shape + ev_diff, edge_pct, mispriced list columns.
        """
        # 1) explode

        tidy = []
        for idx, row in df.iterrows():
            for j, (side, p_mkt, p_fit) in enumerate(
                zip(row.get("outcome_name", []),
                    row.get("implied_probability", []),
                    row.get("exp_prob", []))
            ):
                tidy.append({
                    "orig_index": idx,
                    "sub_idx":    j,
                    "side":       side,
                    "prob_mkt":   float(p_mkt),
                    "prob_fit":   float(p_fit),
                    "outcome_point": row["outcome_point"],
                    "outcome_description": row["outcome_description"],
                    "market_key": row["market_key"],
                })
        tidy = pd.DataFrame(tidy)
        if tidy.empty:
            raise RuntimeError("Exploded DataFrame is empty – check that 'implied_probability' and 'exp_prob' are lists of equal length")


        # 2) raw metrics
        tidy["ev_diff"]  = tidy["prob_mkt"] - tidy["prob_fit"]
        tidy["edge_pct"] = tidy["prob_fit"] / tidy["prob_mkt"] - 1

        # 3) optional bootstrap CI
        if bootstrap:
            for g_key, grp in tidy.groupby(["outcome_description", "market_key"]):
                uniq_pts = grp["outcome_point"].nunique()
                print(f"{g_key}: {uniq_pts} unique strike(s)")
            lower_list, upper_list = [], []
            key_cols = ["outcome_description", "market_key"]
            for _, grp in tidy.groupby(key_cols):
                lo, hi = self._bootstrap_cis(grp)
                lower_list.extend(lo)
                upper_list.extend(hi)
            tidy["lo95"], tidy["hi95"] = lower_list, upper_list
            tidy["flag_ci"] = (tidy["prob_mkt"] < tidy["lo95"]) | (tidy["prob_mkt"] > tidy["hi95"])
        else:
            tidy["flag_ci"] = False

        # 4) final boolean
        tidy["mispriced"] = (
            (tidy["flag_ci"]) |
            ((tidy["prob_mkt"] - tidy["prob_fit"] < (0 - p_gap)) &
            (tidy["edge_pct"].abs() >= ev_thresh))
        )

        # 5) collapse back to list structure
        tidy = tidy.sort_values(["orig_index", "sub_idx"])
        for col in ["ev_diff", "edge_pct", "mispriced"]:
            df[col] = [tidy.loc[tidy["orig_index"] == i, col].tolist() for i in df.index]

        return df

    def find_prop_arbs(self, merged_df: pd.DataFrame, threshold: float = 0.01) -> pd.DataFrame:
        """
        Flatten a merged prop DataFrame (with list-columns) into a tidy form,
        then identify two-way arbitrage opportunities where an Under line point
        is >= the Over line point and the sum of true probabilities < 1 - threshold.
        """
        # 1) Flatten list-columns into a tidy DataFrame
        records = []
        for _, row in merged_df.iterrows():
            desc = row['outcome_description']
            mk   = row['market_key']
            ap   = row['abs_point']
            for name, odds, prob, book, market, link, pt in zip(
                row['outcome_name'],
                row['outcome_price'],
                row['implied_probability'],
                row['bookmaker_key'],
                row['markets'],
                row['link'],
                row['outcome_point']
            ):
                records.append({
                    'outcome_description': desc,
                    'market_key': mk,
                    'abs_point': ap,
                    'side': name,
                    'odds': odds,
                    'prob': prob,
                    'bookmaker': book,
                    'market_type': market,
                    'link': link,
                    'point': pt
                })
        tidy = pd.DataFrame(records)

        # 2) Find arbitrage within each prop group
        arb_list = []
        for (desc, mk), group in tidy.groupby(['outcome_description','market_key']):

            if (mk.startswith('h2h') and '3_way' not in mk) or mk.startswith('spread'):
                for _, row1 in group.iterrows():
                    for _, row2 in group.iterrows():
                        if row1['side'] == row2['side']:
                            continue
                        if mk.startswith('spreads') and not (row1['point'] > 0 and row2['point'] < 0 and abs(row1['point']) >= abs(row2['point'])):
                            continue


                        prob1 = 1/self.american_to_decimal(row1['odds'])
                        prob2 = 1/self.american_to_decimal(row2['odds'])
                        if prob1 + prob2 < 1 - threshold:
                            arb_list.append({
                                'outcome_description': desc,
                                'market_key': mk,
                                'over_name': row1['side'],
                                'under_name': row2['side'],
                                'over_point': row1['point'],
                                'under_point': row2['point'],
                                'over_prob': prob1,
                                'under_prob': prob2,
                                'sum_prob': prob1 + prob2,
                                'over_bookmaker': row1['bookmaker'],
                                'under_bookmaker': row2['bookmaker'],
                                'over_market': row1['market_type'],
                                'under_market': row2['market_type'],
                                'over_odds': row1['odds'],
                                'under_odds': row2['odds'],
                                'over_link': row1['link'],
                                'under_link': row2['link']
                            })
                    continue

            overs  = group[group['side'].str.lower() == 'over']
            unders = group[group['side'].str.lower() == 'under']
            for _, over in overs.iterrows():
                for _, under in unders.iterrows():
                    over_real_prob  = 1 / self.american_to_decimal(over['odds'])
                    under_real_prob = 1 / self.american_to_decimal(under['odds'])
                    total_prob = over_real_prob + under_real_prob

                    if under['point'] >= over['point'] and total_prob < (1 - threshold):
                        arb_list.append({
                            'outcome_description': desc,
                            'market_key': mk,
                            'over_point': over['point'],
                            'under_point': under['point'],
                            'over_prob': over_real_prob,
                            'under_prob': under_real_prob,
                            'sum_prob': total_prob,
                            'over_bookmaker': over['bookmaker'],
                            'under_bookmaker': under['bookmaker'],
                            'over_market': over['market_type'],
                            'under_market': under['market_type'],
                            'over_odds': over['odds'],
                            'under_odds': under['odds'],
                            'over_link': over['link'],
                            'under_link': under['link']
                        })

        return pd.DataFrame(arb_list)
    
    def get_mispriced_flattened(self, flagged_df: pd.DataFrame,
                            description: str | None = None,
                            market_key: str | None = None) -> pd.DataFrame:
        """
        Flatten only quotes with mispriced == True, keeping:
            prob_mkt  : vig‑free market probability
            prob_fit  : fitted fair probability
            edge_pct  : ROI %
        """
        if "mispriced" not in flagged_df.columns:
            raise ValueError("DataFrame must first pass through "
                            "flag_mispriced_lines (missing 'mispriced').")

        records = []

        for _, row in flagged_df.iterrows():

            # optional filters
            if description is not None and row["outcome_description"] != description:
                continue
            if market_key is not None and row["market_key"] != market_key:
                continue

            # parallel lists
            names   = row.get("outcome_name", [])
            probs   = row.get("implied_probability", [])   # vig‑free market prob
            books   = row.get("bookmaker_key", [])
            odds    = row.get("outcome_price", [])
            mtypes  = row.get("markets", [])
            links   = row.get("link", [])
            flags   = row.get("mispriced", [])
            fits    = row.get("exp_prob", [])
            edges   = row.get("ev_diff", [])
            vigs    = row.get("vig", [])

            for side, p_mkt, book, odd, mtype, link, flag, p_fit, edge, vig in zip(
                names, probs, books, odds, mtypes, links, flags, fits, edges, vigs
            ):
                if not flag:                        # keep only mispriced
                    continue
                records.append({
                    "outcome_description": row["outcome_description"],
                    "market_key":          row["market_key"],
                    "point":               row["outcome_point"],
                    "side":                side,
                    "prob_mkt":            p_mkt,     # no‑vig market prob
                    "prob_fit":            p_fit,     # fitted probability
                    "edge":            edge,      # theoretical ROI %
                    "bookmaker":           book,
                    "odds":                odd,
                    "market_type":         mtype,
                    "link":                link,
                    "mispriced":           True,
                    "vig":                 vig,
                })

        return pd.DataFrame(records)
    
    def save_market_analysis(self, mispriced_df: pd.DataFrame, merged_df_with_exp: pd.DataFrame, 
                           event_id: str, timestamp: str, market_type: str, filepath: str = "odds_data"):
        """
        Save detailed market analysis for each unique market/outcome combination found in mispriced_df.
        
        Parameters:
        -----------
        mispriced_df : DataFrame with mispriced lines (flattened)
        merged_df_with_exp : DataFrame with expected probabilities (list format)
        event_id : str, event identifier
        timestamp : str, timestamp for files
        market_type : str, "player" or "game"
        filepath : str, base filepath for saving
        """
        if mispriced_df.empty:
            return
            
        # Create output directory
        analysis_dir = f"{filepath}/market_analysis/{market_type}"
        if not os.path.exists(analysis_dir):
            os.makedirs(analysis_dir)
        
        # Get unique market/outcome combinations from mispriced data
        unique_markets = mispriced_df[['outcome_description', 'market_key']].drop_duplicates()
        
        for _, market_row in unique_markets.iterrows():
            desc = market_row['outcome_description']
            mkey = market_row['market_key']
            
            # Find matching rows in merged_df_with_exp
            matching_rows = merged_df_with_exp[
                (merged_df_with_exp['outcome_description'] == desc) &
                (merged_df_with_exp['market_key'] == mkey)
            ]
            
            if matching_rows.empty:
                continue
                
            # Flatten all data for this market combination
            all_market_data = []
            for _, row in matching_rows.iterrows():
                # Get parallel lists
                names = row.get("outcome_name", [])
                probs = row.get("implied_probability", [])
                books = row.get("bookmaker_key", [])
                odds = row.get("outcome_price", [])
                mtypes = row.get("markets", [])
                links = row.get("link", [])
                exp_probs = row.get("exp_prob", [])
                vigs = row.get("vig", [])
                
                # Handle mispricing flags if they exist
                mispriced_flags = row.get("mispriced", [])
                if not mispriced_flags:
                    mispriced_flags = [False] * len(names)
                
                # Handle edge calculations if they exist
                edges = row.get("ev_diff", [])
                if not edges:
                    edges = [None] * len(names)
                
                # Flatten each quote
                for i, (side, p_mkt, book, odd, mtype, link, p_fit, vig) in enumerate(zip(
                    names, probs, books, odds, mtypes, links, exp_probs, vigs
                )):
                    mispriced_flag = mispriced_flags[i] if i < len(mispriced_flags) else False
                    edge = edges[i] if i < len(edges) else None
                    
                    all_market_data.append({
                        "outcome_description": desc,
                        "market_key": mkey,
                        "point": row["outcome_point"],
                        "side": side,
                        "prob_mkt": p_mkt,
                        "prob_fit": p_fit,
                        "edge": edge,
                        "bookmaker": book,
                        "odds": odd,
                        "market_type": mtype,
                        "link": link,
                        "vig": vig,
                        "mispriced": mispriced_flag,
                    })
            
            if all_market_data:
                # Create filename (sanitize special characters)
                safe_desc = "".join(c for c in desc if c.isalnum() or c in (' ', '-', '_')).rstrip()
                safe_mkey = "".join(c for c in mkey if c.isalnum() or c in (' ', '-', '_')).rstrip()
                filename = f"{event_id}_{safe_desc}_{safe_mkey}_{timestamp}.csv"
                
                # Save to CSV
                market_df = pd.DataFrame(all_market_data)
                filepath_full = f"{analysis_dir}/{filename}"
                market_df.to_csv(filepath_full, index=False)
                
                print(f"Saved market analysis: {filepath_full} ({len(market_df)} quotes)")
    
    def preprocess_game_props(self, game_df, alternate_df, period_df):
        if game_df.empty:
                print(f"No game data for event {self.event['id']} – skipping.")
                return
        game_df['outcome_point'] = game_df['outcome_point'].fillna(0)
        game_df['outcome_description'] = game_df['outcome_description'].fillna(0)

        game_df = game_df.copy()
        game_df['abs_point'] = game_df['outcome_point'].abs()
        game_arranged_df = game_df[
            ['outcome_name','outcome_description','bookmaker_key',
            'market_key','outcome_price', 'outcome_point', 'abs_point', 'link']
            ].groupby(['market_key', 'outcome_description', 'abs_point'], as_index=False).agg(list)
            
        if alternate_df.empty:
            print(f"No alternate data for event {self.event['id']} – skipping.")
            return
        alternate_df['outcome_point'] = alternate_df['outcome_point'].fillna(0)
        alternate_df = alternate_df.copy()
        alternate_df['abs_point'] = alternate_df['outcome_point'].abs()

        alternate_arranged_df = alternate_df[
            ['outcome_name','outcome_description','bookmaker_key',
            'market_key','outcome_price','outcome_point', 'abs_point', 'link']
            ].groupby(['outcome_description', 'market_key', 'abs_point'], as_index=False).agg(list)

        if period_df.empty:
            print(f"No game period data for event {self.event['id']} – skipping.")
            return
        period_df['outcome_point'] = period_df['outcome_point'].fillna(0)
        period_df = period_df.copy()
        period_df['abs_point'] = period_df['outcome_point'].abs()
        period_arranged_df = period_df[
            ['outcome_name','outcome_description','bookmaker_key',
            'market_key','outcome_price', 'outcome_point', 'abs_point', 'link']
            ].groupby(['outcome_description', 'market_key', 'abs_point'], as_index=False).agg(list)

        # print(game_df.head(20))
        # print(game_arranged_df.head(20))
        # print(alternate_arranged_df.head(30))
        # print(period_arranged_df.head(30))

        self.calculate_vig_and_no_vig(arranged_df=game_arranged_df, mode="under_over")
        self.calculate_vig_and_no_vig(arranged_df=alternate_arranged_df, mode="under_over")
        self.calculate_vig_and_no_vig(arranged_df=period_arranged_df, mode="under_over")

        merged_game_df = self.merge_prop_dfs(alternate_arranged_df, game_arranged_df, mode="game")
        merged_game_df = self.merge_prop_dfs(period_arranged_df, merged_game_df, mode="game")
        return merged_game_df

    
    def process_odds_for_event(
        self, event, 
        p_gap, ev_thresh, bootstrap=False, arb_thresh=0.01,
        player=True, game=False, regions=Config.US, 
        mode="live", filepath="odds_data", verbose=False
        ):
        
        timestamp = datetime.now(timezone.utc).isoformat()
        mispriced_player_df = pd.DataFrame()
        mispriced_game_df = pd.DataFrame()
        arb_player_df = pd.DataFrame()
        arb_game_df = pd.DataFrame()
        event_id = event['id']

        if player:
            if verbose:
                print("============================")
                print("PLAYER DATA PROP PROCESSING")
                # PRINT NEW LINE AND DIVIDER
                print("============================")
                print("\n")

            if mode == "live":
                player_prop_df = self.event_fetcher.get_props_for_todays_events([event], markets=Config.player_prop_markets)
                player_alt_df = self.event_fetcher.get_props_for_todays_events([event], markets=Config.player_alternate_markets)
                player_prop_df = pd.DataFrame(player_prop_df)
                player_alt_df = pd.DataFrame(player_alt_df)
                if not os.path.exists(f"{filepath}/player"):
                    os.makedirs(f"{filepath}/player")
                # save to csv with current timestamp
                if verbose:
                    print(f"Saving player data for event {event['id']} to {filepath}/player")
                player_prop_df.to_csv(f"{filepath}/player/{event_id}_player_prop_{timestamp}.csv", index=False)
                player_alt_df.to_csv(f"{filepath}/player/{event_id}_player_alt_{timestamp}.csv", index=False)
            else:
                player_prop_df = load_file_with_string(
                    f"{filepath}/player",
                    "player_prop",
                    filetype="csv"
                )
                player_alt_df = load_file_with_string(
                    f"{filepath}/player",
                    "alt",
                    filetype="csv"
                )
                if verbose:
                    print(f"Loaded player data for latest event from {filepath}/player")
            
            if player_prop_df.empty:
                print(f"No player‑prop data for event {event['id']} – skipping.")
            if player_alt_df.empty:
                print(f"No player alternate data for event {event['id']} – skipping.")
            
            player_arranged_df = player_prop_df[
                ['outcome_name','outcome_description','bookmaker_key',
                'market_key','outcome_price','outcome_point', 'link']
            ].groupby(['outcome_description', 'market_key', 'outcome_point'], as_index=False).agg(list)

            player_alt_arranged_df = player_alt_df[
                ['outcome_name','outcome_description','bookmaker_key',
                'market_key','outcome_price','outcome_point', 'link']
            ].groupby(['outcome_description', 'market_key', 'outcome_point'], as_index=False).agg(list)

            if verbose:
                print("Calculating vigs for player props")

            self.calculate_vig_and_no_vig(arranged_df=player_arranged_df, mode="under_over")
            self.calculate_vig_and_no_vig(arranged_df=player_alt_arranged_df, mode="straight")

            if verbose:
                print("Merging player props")

            merged_player_props_df = self.merge_prop_dfs(player_alt_arranged_df, player_arranged_df)

            if verbose:
                print("\n MERGED PLAYER PROPS: \n")
                print(merged_player_props_df.head(5))
                print("Adding expected probabilities")

            with_exp_prob = self.add_expected_probabilities(merged_player_props_df)

            if verbose:
                print("\n WITH EXP PROB: \n")
                print(with_exp_prob.head(5))

            if verbose:
                print("Flagging mispriced lines")

            mispriced_player_df = self.flag_mispriced_lines(with_exp_prob, p_gap=p_gap, ev_thresh=ev_thresh, bootstrap=bootstrap)

            mispriced_player_df = self.get_mispriced_flattened(mispriced_player_df)
            if verbose:
                print("\n MISPRICED DF: \n")
                print(mispriced_player_df)

            # Save market analysis for player props when mispriced lines are found
            if not mispriced_player_df.empty and mode=="test":
                self.save_market_analysis(
                    mispriced_df=mispriced_player_df,
                    merged_df_with_exp=with_exp_prob,
                    event_id=event_id,
                    timestamp=timestamp,
                    market_type="player",
                    filepath=filepath
                )

            if verbose:
                print("Finding arbitrage opportunities")

            arb_player_df = self.find_all_player_arbs(merged_player_props_df, arb_thresh)
            if verbose:
                print("\n ARB DF: \n")
                print(arb_player_df)
            
        if game:

            if verbose:
                print("\n \n============================")
                print("GAME DATA PROP PROCESSING")
                # PRINT NEW LINE AND DIVIDER
                print("============================")
                print("\n")
            
            if mode == "live":
                game_period_df = self.event_fetcher.get_props_for_todays_events([event], markets=Config.game_period_markets)
                alternate_df = self.event_fetcher.get_props_for_todays_events([event], markets=Config.alt_markets)
                game_df = self.event_fetcher.get_props_for_todays_events([event], markets=Config.game_markets)
                game_period_df = pd.DataFrame(game_period_df)
                alternate_df = pd.DataFrame(alternate_df)
                game_df = pd.DataFrame(game_df)
                if not os.path.exists(f"{filepath}/game"):
                    os.makedirs(f"{filepath}/game")
                # save to csv with current timestamp
                if verbose:
                    print(f"Saving game data for event {event['id']} to {filepath}/game")
                game_period_df.to_csv(f"{filepath}/game/{event_id}_game_period_{timestamp}.csv", index=False)
                alternate_df.to_csv(f"{filepath}/game/{event_id}_alternate_{timestamp}.csv", index=False)
                game_df.to_csv(f"{filepath}/game/{event_id}_game_{timestamp}.csv", index=False)
            else:
                game_period_df = load_file_with_string(
                    f"{filepath}/game",
                    "game_period",
                    filetype="csv"
                )
                alternate_df = load_file_with_string(
                    f"{filepath}/game",
                    "alternate",
                    filetype="csv"
                )
                game_df = load_file_with_string(
                    f"{filepath}/game",
                    "game_2025",
                    filetype="csv"
                )
                if verbose:
                    print(f"Loaded game data for latest event from {filepath}/game")
            
            if game_period_df.empty:
                print(f"No game period data for event {event['id']} – skipping.")
            if alternate_df.empty:
                print(f"No alternate data for event {event['id']} – skipping.")
            if game_df.empty:
                print(f"No game data for event {event['id']} – skipping.")

            if verbose:
                print("Merging game props and processing vigs")

            merged_game_df = self.preprocess_game_props(game_df, alternate_df, game_period_df)

            if verbose:
                print("\n MERGED GAME PROPS: \n")
                print(merged_game_df.head(5))

            if verbose:
                print("Finding arbitrage opportunities")

            arb_game_df = self.find_prop_arbs(merged_game_df)
            if verbose:
                print("\n ARB DF: \n")
                print(arb_game_df)

            if verbose:
                print("Adding expected probabilities")

            merged_game_w_exp_prob = self.add_expected_probabilities(merged_game_df, mode="game")

            if verbose:
                print("Flagging mispriced lines")

            mispriced_game_df = self.flag_mispriced_lines(merged_game_w_exp_prob, p_gap=p_gap, ev_thresh=ev_thresh, bootstrap=bootstrap)
            if verbose:
                print("Flattening mispriced df")
            mispriced_game_df = self.get_mispriced_flattened(mispriced_game_df)
            if verbose:
                print("\n MISPRICED DF: \n")
                print(mispriced_game_df)

            # Save market analysis for game props when mispriced lines are found
            if not mispriced_game_df.empty and mode=="test":
                self.save_market_analysis(
                    mispriced_df=mispriced_game_df,
                    merged_df_with_exp=merged_game_w_exp_prob,
                    event_id=event_id,
                    timestamp=timestamp,
                    market_type="game",
                    filepath=filepath
                )

        
        return (arb_player_df, arb_game_df, mispriced_player_df, mispriced_game_df)


