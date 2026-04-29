"""Jury vote simulator — generates random jury votes plus juror DoBs.

Output xlsx columns: Voting_country | Juror | Participating_country | Rank | DoB
Each (Voting_country, Juror) pair has a single DoB repeated across rows.
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
                rows.append((vc, juror, pc, ranks[pc], juror_dobs[juror]))

    return rows


def write_xlsx(rows, output_path):
    wb = Workbook()
    ws = wb.active
    ws.append(["Voting_country", "Juror", "Participating_country", "Rank", "DoB"])
    for row in rows:
        ws.append(list(row))
    for cell in ws['E'][1:]:
        cell.number_format = 'YYYY-MM-DD'
    wb.save(output_path)


def main():
    participating_countries = ["GB", "ES", "FR", "DE"]
    voting_countries = ["FR", "GB", "DE", "ES", "PT"]
    jurors_per_country = 3
    output_file = "jury_votes.xlsx"
    seed = None

    rows = simulate_jury_votes(
        participating_countries, voting_countries, jurors_per_country, seed=seed,
    )
    write_xlsx(rows, output_file)
    print(f"Wrote {len(rows)} vote rows to {output_file}")


if __name__ == "__main__":
    main()
