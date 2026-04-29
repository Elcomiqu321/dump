"""Helpers for the jury results notebook.

Functions here are meant to be imported into the notebook so the notebook itself
stays focused on the data flow.
"""
from functools import cmp_to_key
import pandas as pd


# --- ISO mapping ---

DICT_ISO = {
    "Albania": "AL", "Andorra": "AD", "Armenia": "AM", "Australia": "AU",
    "Austria": "AT", "Azerbaijan": "AZ", "Belarus": "BY", "Belgium": "BE",
    "Bosnia & Herzegovina": "BA", "Bulgaria": "BG", "Croatia": "HR",
    "Cyprus": "CY", "Czechia": "CZ", "Denmark": "DK", "Estonia": "EE",
    "Finland": "FI", "France": "FR", "Georgia": "GE", "Germany": "DE",
    "Greece": "GR", "Hungary": "HU", "Iceland": "IS", "Ireland": "IE",
    "Israel": "IL", "Italy": "IT", "Latvia": "LV", "Lithuania": "LT",
    "Luxembourg": "LU", "Malta": "MT", "Moldova": "MD", "Monaco": "MC",
    "Montenegro": "ME", "Morocco": "MA", "Netherlands": "NL",
    "North Macedonia": "MK", "Norway": "NO", "Poland": "PL",
    "Portugal": "PT", "Romania": "RO", "Russia": "RU", "San Marino": "SM",
    "Serbia": "RS", "Slovakia": "SK", "Slovenia": "SI", "Spain": "ES",
    "Sweden": "SE", "Switzerland": "CH", "Turkey": "TR", "Ukraine": "UA",
    "United Kingdom": "GB", "Rest Of World": "RoW",
}
ISO_TO_COUNTRY = {iso: name for name, iso in DICT_ISO.items()}


# --- Scoring tables ---

class RankError(Exception):
    """Raised when a rank value isn't in the supported mapping range (0–26)."""
    pass


EXP_SCORE_TABLE = {
    0:  0,        1:  12,       2:  9.92351,  3:  8.20634,  4:  6.78631,
    5:  5.612,    6:  4.64089,  7:  3.83783,  8:  3.17373,  9:  2.62454,
    10: 2.17039, 11: 1.79482, 12: 1.48425, 13: 1.22741, 14: 1.01502,
    15: 0.83938, 16: 0.69413, 17: 0.57402, 18: 0.47469, 19: 0.39255,
    20: 0.32462, 21: 0.26845, 22: 0.222,   23: 0.18358, 24: 0.15181,
    25: 0.12554, 26: 0.10382,
}

POINTS_SCALE = {1: 12, 2: 10, 3: 8, 4: 7, 5: 6,
                6:  5, 7:  4, 8: 3, 9: 2, 10: 1}


def rank_to_exp_score(rank):
    if rank not in EXP_SCORE_TABLE:
        raise RankError(f'Invalid Rank Value Provided for Exp. Scoring Mapping: {rank}')
    return EXP_SCORE_TABLE[rank]


def rank_to_points(rank):
    if pd.isna(rank):
        return 0
    return POINTS_SCALE.get(int(rank), 0)


# --- Tie-breaking ---

def _break_tie_majority(country_a, country_b, jury_ranks):
    """Count jurors who placed country_a above country_b (lower rank wins).
    Self-votes (rank 0) are ignored. Returns the winning country or None."""
    a_wins = b_wins = 0
    for juror in jury_ranks.columns:
        ra = jury_ranks.loc[country_a, juror]
        rb = jury_ranks.loc[country_b, juror]
        if ra == 0 or rb == 0:
            continue
        if ra < rb:
            a_wins += 1
        elif rb < ra:
            b_wins += 1
    if a_wins > b_wins:
        return country_a
    if b_wins > a_wins:
        return country_b
    return None


def _break_tie_youngest(country_a, country_b, jury_ranks, juror_dobs):
    """Use the youngest juror's individual ranking. Returns winner, or None
    if more than one juror shares the youngest DoB."""
    max_dob = max(juror_dobs.values())
    youngest = [j for j, d in juror_dobs.items() if d == max_dob]
    if len(youngest) > 1:
        return None
    j = youngest[0]
    ra = jury_ranks.loc[country_a, j]
    rb = jury_ranks.loc[country_b, j]
    if ra == 0 or rb == 0:
        return None
    return country_a if ra < rb else country_b


def _break_tie_show_of_hands(voting_country, country_a, country_b, prompt_fn=input):
    """Prompt the user for the winning ISO code. ``prompt_fn`` is overridable
    for testing."""
    iso_a = DICT_ISO.get(country_a, country_a)
    iso_b = DICT_ISO.get(country_b, country_b)
    while True:
        ans = prompt_fn(
            f"[{voting_country} jury] Show of hands needed between "
            f"{country_a} ({iso_a}) and {country_b} ({iso_b}). "
            f"Enter winning ISO code: "
        ).strip().upper()
        if ans == iso_a.upper():
            return country_a
        if ans == iso_b.upper():
            return country_b
        print(f"  Invalid answer. Please enter '{iso_a}' or '{iso_b}'.")


def resolve_pair(voting_country, country_a, country_b, jury_ranks, juror_dobs,
                 prompt_fn=input):
    """Apply the three-level tie-breaker to a pair of countries.
    Returns the winning country."""
    winner = _break_tie_majority(country_a, country_b, jury_ranks)
    if winner is not None:
        return winner
    winner = _break_tie_youngest(country_a, country_b, jury_ranks, juror_dobs)
    if winner is not None:
        return winner
    return _break_tie_show_of_hands(voting_country, country_a, country_b, prompt_fn)


def rank_jury_with_tiebreakers(voting_country, jury_sums, jury_ranks, juror_dobs,
                                prompt_fn=input):
    """Compute the per-jury rank Series, breaking ties when sums are equal.

    Parameters
    ----------
    voting_country : str
        Name of the voting country (its home row, if any, must already be NaN
        in jury_sums).
    jury_sums : pd.Series
        Index = participating countries, values = exponential-score sums for
        this jury. NaN entries (the home country) are excluded from the rank.
    jury_ranks : pd.DataFrame
        Rows = participating countries, columns = jurors of this jury, values =
        original ranks from the jurors.
    juror_dobs : dict[str, pd.Timestamp]
        Date of birth for each juror in this jury (key = juror label).
    prompt_fn : callable
        Used by the show-of-hands tie-breaker; overridable for testing.

    Returns
    -------
    pd.Series indexed by participating country, with ranks 1..K where K is the
    number of non-home participants. The home country (NaN sum) is left out.
    """
    candidates = jury_sums.dropna().sort_values(ascending=False)
    items = list(candidates.items())

    ordered = []
    i = 0
    while i < len(items):
        j = i
        while j + 1 < len(items) and items[j + 1][1] == items[i][1]:
            j += 1
        if j == i:
            ordered.append(items[i][0])
        else:
            group = [items[k][0] for k in range(i, j + 1)]

            def _cmp(x, y):
                winner = resolve_pair(voting_country, x, y, jury_ranks,
                                      juror_dobs, prompt_fn)
                return -1 if winner == x else 1

            ordered.extend(sorted(group, key=cmp_to_key(_cmp)))
        i = j + 1

    return pd.Series({c: idx + 1 for idx, c in enumerate(ordered)},
                     name=voting_country, dtype='Int64')
