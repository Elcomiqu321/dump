"""Helpers for the jury results notebook.

Functions are grouped by purpose:
- ISO mapping
- Score tables
- National Jury tie-breaking (within a single jury)
- Final classification tie-breaking (across all juries)
"""
from functools import cmp_to_key
import pandas as pd


# ============================================================
# ISO mapping
# ============================================================

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


# ============================================================
# Scoring tables
# ============================================================

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

# Order in which point values are walked through for the final tie-breaker
POINTS_TIEBREAK_ORDER = [12, 10, 8, 7, 6, 5, 4, 3, 2, 1]


def rank_to_exp_score(rank):
    if rank not in EXP_SCORE_TABLE:
        raise RankError(f'Invalid Rank Value Provided for Exp. Scoring Mapping: {rank}')
    return EXP_SCORE_TABLE[rank]


def rank_to_points(rank):
    if pd.isna(rank):
        return 0
    return POINTS_SCALE.get(int(rank), 0)


# ============================================================
# NATIONAL JURY TIE-BREAKING
# ============================================================
# EBU §1.3.1 — "Tie due to the same rank from the National Jury in a given country".
# Scenario: within a single national jury, after summing each juror's exponential
# scores per country, two or more countries end up with identical sums and so
# share a provisional rank.
#
# Resolution chain (pairwise):
#   1. _jury_tie_majority         — better individual rankings by majority of jurors
#   2. _jury_tie_youngest         — vote of the youngest juror
#   3. _jury_tie_show_of_hands    — interactive prompt (chairperson asks the jury)


def _jury_tie_majority(country_a, country_b, jury_ranks, verbose=True):
    """Step 1 of within-jury tie-breaker.

    Scenario: two countries in the same jury have identical exponential-score sums.
    Resolution: count, juror by juror, who placed country_a higher (= lower rank
    number) versus country_b. Self-votes (rank 0) are excluded. The country
    placed higher by the strict majority of jurors wins.

    Returns the winner, or None if the count is itself tied.
    """
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
    if verbose:
        print(f"      majority: {country_a} preferred by {a_wins}, "
              f"{country_b} by {b_wins}")
    if a_wins > b_wins:
        return country_a
    if b_wins > a_wins:
        return country_b
    return None


def _jury_tie_youngest(country_a, country_b, jury_ranks, juror_dobs, verbose=True):
    """Step 2 of within-jury tie-breaker.

    Scenario: step 1 (majority count) was a draw.
    Resolution: identify the juror with the latest date of birth (youngest) and
    use that single juror's individual ranking. If two or more jurors share the
    same youngest DoB, this step cannot resolve and returns None.
    """
    max_dob = max(juror_dobs.values())
    youngest = [j for j, d in juror_dobs.items() if d == max_dob]
    if len(youngest) > 1:
        if verbose:
            print(f"      youngest juror: {len(youngest)} jurors share DoB "
                  f"{max_dob.date()} → unresolved")
        return None
    j = youngest[0]
    ra = jury_ranks.loc[country_a, j]
    rb = jury_ranks.loc[country_b, j]
    if verbose:
        print(f"      youngest juror ({j}, b. {max_dob.date()}): "
              f"{country_a}={ra}, {country_b}={rb}")
    if ra == 0 or rb == 0:
        return None
    return country_a if ra < rb else country_b


def _jury_tie_show_of_hands(voting_country, country_a, country_b,
                             prompt_fn=input, verbose=True):
    """Step 3 (final) of within-jury tie-breaker.

    Scenario: step 1 (majority) was a draw and step 2 (youngest) couldn't
    resolve (multiple jurors share the youngest DoB).
    Resolution: per EBU §1.3.1 the chairperson asks the jury by show of hands.
    Implementation: prompt the user interactively for the winning ISO code.
    """
    iso_a = DICT_ISO.get(country_a, country_a)
    iso_b = DICT_ISO.get(country_b, country_b)
    if verbose:
        print(f"      show of hands required: {country_a} vs {country_b}")
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


def resolve_jury_tie(voting_country, country_a, country_b, jury_ranks, juror_dobs,
                     prompt_fn=input, verbose=True):
    """Run the full within-jury tie-breaker chain on a pair of tied countries
    (majority → youngest juror → show of hands). Returns the winner.
    """
    winner = _jury_tie_majority(country_a, country_b, jury_ranks, verbose)
    if winner is not None:
        return winner
    winner = _jury_tie_youngest(country_a, country_b, jury_ranks, juror_dobs, verbose)
    if winner is not None:
        return winner
    return _jury_tie_show_of_hands(voting_country, country_a, country_b,
                                    prompt_fn, verbose)


def rank_jury_with_tiebreakers(voting_country, jury_sums, jury_ranks, juror_dobs,
                                prompt_fn=input, verbose=True):
    """Compute per-jury ranks (1..K) for non-home participants, breaking sum-ties
    via the within-jury chain.

    Parameters
    ----------
    voting_country : str
    jury_sums : pd.Series indexed by participating country (NaN = home, excluded)
    jury_ranks : pd.DataFrame, index=participating, columns=jurors of this jury
    juror_dobs : dict[juror_label -> Timestamp]
    prompt_fn : callable used for show-of-hands input (overridable for testing)
    verbose : bool
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
            tied_countries = [items[k][0] for k in range(i, j + 1)]
            tied_sum = items[i][1]
            if verbose:
                print(f"  [{voting_country} jury] Tie at sum={tied_sum:.5f}: "
                      f"{tied_countries}")

            def _cmp(x, y):
                winner = resolve_jury_tie(voting_country, x, y, jury_ranks,
                                          juror_dobs, prompt_fn, verbose)
                return -1 if winner == x else 1

            sorted_group = sorted(tied_countries, key=cmp_to_key(_cmp))
            if verbose:
                print(f"    resolved order: {sorted_group}")
            ordered.extend(sorted_group)
        i = j + 1

    return pd.Series({c: idx + 1 for idx, c in enumerate(ordered)},
                     name=voting_country, dtype='Int64')


# ============================================================
# FINAL CLASSIFICATION TIE-BREAKING
# ============================================================
# EBU §1.3.1 — "Tie due to the same number of points from all National Juries".
# Scenario: across all juries, two or more participating countries end up with
# identical total point counts.
#
# Resolution chain (pairwise):
#   1. _final_tie_jury_count            — most juries that awarded any points
#   2. _final_tie_points_count(12)      — most 12-point scores
#   3. _final_tie_points_count(10..1)   — walk down the points scale
#   4. _final_tie_show_order            — earlier in the show running order


def _final_tie_jury_count(country_a, country_b, jury_points, verbose=True):
    """Step 1 of final-tie chain.

    Scenario: two countries have the same total points across all juries.
    Resolution: count juries that gave each country any points (cells > 0).
    Higher count wins.
    """
    a_count = (jury_points.loc[country_a] > 0).sum()
    b_count = (jury_points.loc[country_b] > 0).sum()
    if verbose:
        print(f"      juries giving points: {country_a}={a_count}, "
              f"{country_b}={b_count}")
    if a_count > b_count:
        return country_a
    if b_count > a_count:
        return country_b
    return None


def _final_tie_points_count(country_a, country_b, jury_points, points_value,
                             verbose=True):
    """Step keyed on a specific point value (12, 10, 8, ..., 1).

    Scenario: still tied after the previous step. Count how many times each
    country received exactly `points_value` points across all juries.
    Higher count wins.
    """
    a_count = (jury_points.loc[country_a] == points_value).sum()
    b_count = (jury_points.loc[country_b] == points_value).sum()
    if verbose:
        print(f"      {points_value}-point count: {country_a}={a_count}, "
              f"{country_b}={b_count}")
    if a_count > b_count:
        return country_a
    if b_count > a_count:
        return country_b
    return None


def _final_tie_show_order(country_a, country_b, show_order, verbose=True):
    """Final step of final-tie chain.

    Scenario: still tied after counting all point values from 12 down to 1.
    Resolution: the country earlier in the running order of the show wins.
    """
    a_order = show_order[country_a]
    b_order = show_order[country_b]
    if verbose:
        print(f"      show order: {country_a}={a_order}, {country_b}={b_order}")
    if a_order < b_order:
        return country_a
    if b_order < a_order:
        return country_b
    return None


def resolve_final_tie(country_a, country_b, jury_points, show_order, verbose=True):
    """Run the full final-classification tie-breaker chain on a pair of tied
    countries (jury count → 12s → 10s → ... → 1s → show order).
    """
    winner = _final_tie_jury_count(country_a, country_b, jury_points, verbose)
    if winner is not None:
        return winner

    for pv in POINTS_TIEBREAK_ORDER:
        winner = _final_tie_points_count(country_a, country_b, jury_points,
                                          pv, verbose)
        if winner is not None:
            return winner

    winner = _final_tie_show_order(country_a, country_b, show_order, verbose)
    if winner is not None:
        return winner

    raise ValueError(
        f"Cannot resolve tie between {country_a} and {country_b} — identical "
        f"totals, point distributions, and show orders."
    )


def rank_final_classification(jury_points, show_order, verbose=True):
    """Compute the final classification with tie-breaking via the EBU final-tie
    chain.

    Parameters
    ----------
    jury_points : pd.DataFrame (rows = participating, cols = voting,
                                values = 0..12 points)
    show_order : dict[str, int] (running order index per participating country)
    verbose : bool

    Returns a pd.DataFrame with Total_points and Rank columns, sorted by Rank.
    """
    totals = jury_points.sum(axis=1)
    countries = list(totals.index)

    # Cache resolutions so the same pair is announced and resolved only once,
    # even though Python's sort may call the comparator multiple times.
    resolved_cache = {}

    def _cmp(x, y):
        if totals[x] != totals[y]:
            return -1 if totals[x] > totals[y] else 1
        key = frozenset({x, y})
        if key not in resolved_cache:
            if verbose:
                print(f"  [Final] Tie at total={totals[x]} points: {x} vs {y}")
            winner = resolve_final_tie(x, y, jury_points, show_order, verbose)
            loser = y if winner == x else x
            if verbose:
                print(f"    resolved: {winner} ranks above {loser}")
            resolved_cache[key] = winner
        winner = resolved_cache[key]
        return -1 if winner == x else 1

    ordered = sorted(countries, key=cmp_to_key(_cmp))

    return pd.DataFrame({
        'Total_points': totals.loc[ordered],
        'Rank': range(1, len(ordered) + 1),
    })
