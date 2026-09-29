"""Download M5 from Nixtla's public mirror and restore the original Kaggle CSV layout.

The mirror drops the `id` column from the sales file and the `d` column from the calendar;
`ega prepare` expects both, so they are rebuilt here. Sales, prices and dates are unchanged.
The files are written to data/raw/m5/, which is git-ignored: do not redistribute them.
"""
from __future__ import annotations
import argparse
import tempfile
import urllib.request
import zipfile
from pathlib import Path
import pandas as pd

URL = 'https://github.com/Nixtla/m5-forecasts/raw/main/datasets/m5.zip'
FILES = ['sales_train_evaluation.csv', 'calendar.csv', 'sell_prices.csv']

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', default='data/raw/m5')
    args = ap.parse_args()
    out = Path(args.out); out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        archive = Path(tmp)/'m5.zip'
        print(f'Downloading {URL}')
        urllib.request.urlretrieve(URL, archive)
        with zipfile.ZipFile(archive) as z:
            for name in FILES: z.extract(name, out)
    sales = pd.read_csv(out/'sales_train_evaluation.csv')
    if 'id' not in sales:
        sales.insert(0, 'id', sales.item_id+'_'+sales.store_id+'_evaluation')
        sales.to_csv(out/'sales_train_evaluation.csv', index=False)
    calendar = pd.read_csv(out/'calendar.csv', keep_default_na=False)
    if 'd' not in calendar:
        calendar.insert(6, 'd', [f'd_{i}' for i in range(1, len(calendar)+1)])
        calendar.to_csv(out/'calendar.csv', index=False)
    print(f'M5: {len(sales)} series, {len(calendar)} calendar days in {out}')

if __name__ == '__main__':
    main()
