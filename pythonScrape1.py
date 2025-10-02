import pandas as pd
import requests

pd.set_option("display.max_rows", None)
pd.set_option("display.max_columns", None)

YEAR = "2023"
STATE = "18"
COUNTIES = ["039","099","141"]

def fetch_acs(vars, dataset="acs/acs5"):
    frames = []
    for c in COUNTIES:
        url = f"https://api.census.gov/data/{YEAR}/{dataset}"
        params = {
            "get": ",".join(["NAME"] + vars),
            "for": "tract:*",
            "in": f"state:{STATE}+county:{c}"
        }
        r = requests.get(url, params=params); r.raise_for_status()
        cols, *rows = r.json()
        df = pd.DataFrame(rows, columns=cols)
        frames.append(df)
    return pd.concat(frames, ignore_index=True)

# Median income
inc = fetch_acs(["B19013_001E"])

# Poverty percent (subject table)
pov = fetch_acs(["S1701_C03_001E"], dataset="acs/acs5/subject")

# Age/sex bins
age_vars = ["B01001_001E",
            "B01001_003E","B01001_004E","B01001_005E","B01001_006E",
            "B01001_027E","B01001_028E","B01001_029E","B01001_030E",
            "B01001_020E","B01001_021E","B01001_022E","B01001_023E","B01001_024E","B01001_025E",
            "B01001_044E","B01001_045E","B01001_046E","B01001_047E","B01001_048E","B01001_049E"]
age = fetch_acs(age_vars)

print(age)

# Join and compute Under_18Per / Over_65Per like your script
