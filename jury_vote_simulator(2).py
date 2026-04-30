"""Jury vote simulator — generates random jury votes, juror DoBs, and show order.

Output xlsx columns:
    Voting_country | Juror | Participating_country | Rank | DoB | ShowOrder

ShowOrder is a fixed-per-participating-country running order index, repeated
across rows for the same participating country.
"""

import random
import datetime
from openpyxl import Workbook


def _random_dob(min_age=20, max_age=70, today=None):
    today = today or datetime.date.today()
    age_days = random.randint(min_age * 365, max_age * 365 + 365)
    return today - datetime.timedelta(days=age_days)


def simulate_jury_votes(participating, voting, jurors_per_country, seed=None,
                         min_age=20, max_age=70):
    if seed is not None:
        random.seed(seed)

    n = len(participating)

    # One running-order index per participating country, unique 1..P
    show_order_values = list(range(1, n + 1))
    random.shuffle(show_order_values)
    show_order = dict(zip(participating, show_order_values))

    rows = []
    for vc in voting:
        juror_dobs = {f"Juror {j}": _random_dob(min_age, max_age)
                      for j in range(1, jurors_per_country + 1)}

        juror_rankings = []
        for j in range(1, jurors_per_country + 1):
            ranks = {}
            if vc in participating:
                others = [p for p in participating if p != vc]
                shuffled = list(range(1, n))
                random.shuffle(shuffled)
                for country, rank in zip(others, shuffled):
                    ranks[country] = rank
                ranks[vc] = 0
            else:
                shuffled = list(range(1, n + 1))
                random.shuffle(shuffled)
                for country, rank in zip(participating, shuffled):
                    ranks[country] = rank
            juror_rankings.append(ranks)

        for pc in participating:
            for j_idx, ranks in enumerate(juror_rankings, start=1):
                juror = f"Juror {j_idx}"
                rows.append((vc, juror, pc, ranks[pc],
                             juror_dobs[juror], show_order[pc]))

    return rows


def write_xlsx(rows, output_path):
    wb = Workbook()
    ws = wb.active
    ws.append(["Voting_country", "Juror", "Participating_country",
               "Rank", "DoB", "ShowOrder"])
    for row in rows:
        ws.append(list(row))
    for cell in ws['E'][1:]:
        cell.number_format = 'YYYY-MM-DD'
    wb.save(output_path)


def main():
    import pandas as pd

    pots_df = pd.read_csv('SF1_-_voting_countries.csv', sep=';', skiprows=1)
    pots_df = pots_df[['Country', 'ISO', 'SF1_Pot']].dropna()
    pots_df['SF1_Pot'] = pots_df['SF1_Pot'].astype(int)

    voting_countries = pots_df['ISO'].tolist()
    # Participating in SF1 = pots 1, 2, 3 (Pot 0 is pre-qualified, only votes)
    participating_countries = pots_df[pots_df['SF1_Pot'] != 0]['ISO'].tolist()

    rows = simulate_jury_votes(
        participating_countries, voting_countries,
        jurors_per_country=7, seed=None,
    )
    write_xlsx(rows, "jury_votes.xlsx")
    print(f"Wrote {len(rows)} vote rows ({len(participating_countries)} "
          f"participating × {len(voting_countries)} voting × 7 jurors)")


if __name__ == "__main__":
    main()
