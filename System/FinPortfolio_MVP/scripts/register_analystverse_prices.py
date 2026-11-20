"""Import a versioned local OHLCV snapshot for the single-stock entry plugin."""
import argparse
import csv
import hashlib
import io
import re
import sys
import tempfile
from datetime import date
from math import isfinite
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.services.dataset_service import DatasetError, DatasetService  # noqa: E402


def register(source: Path, symbol: str) -> dict:
    if not re.fullmatch(r"\d{6}", symbol):
        raise ValueError("请输入六位 A 股代码")
    raw = source.read_bytes()
    with io.StringIO(raw.decode("utf-8-sig"), newline="") as file:
        reader = csv.DictReader(file)
        price_fields = ["open", "close", "volume"]
        required = {"date", *price_fields}
        if not required.issubset(reader.fieldnames or ()):
            raise ValueError("行情 CSV 需要 date、open、close、volume 字段")
        rows = []
        seen_dates = set()
        for row in reader:
            actual = row.get("tic") or row.get("symbol") or symbol
            if actual.strip().removesuffix(".SZ").removesuffix(".SH") != symbol:
                raise ValueError("行情 CSV 内有不匹配的股票代码")
            trading_date = date.fromisoformat(row["date"]).isoformat()
            if trading_date in seen_dates:
                raise ValueError(f"行情日期重复：{trading_date}")
            seen_dates.add(trading_date)
            prices = {field: float(row[field]) for field in price_fields}
            if any(not isfinite(value) or value <= 0 for value in prices.values()):
                raise ValueError(f"行情价格或成交量无效：{trading_date}")
            rows.append({"date": trading_date, "tic": symbol, **prices})
    if not rows:
        raise ValueError("行情 CSV 没有数据")
    version = hashlib.sha256(raw).hexdigest()[:12]
    dataset_id = f"analystverse_{symbol}_{version}"
    service = DatasetService()
    try:
        return service.get(dataset_id)
    except DatasetError:
        pass
    with tempfile.TemporaryDirectory(prefix="analystverse_prices_") as temp_dir:
        with (Path(temp_dir) / "prices.csv").open("w", newline="", encoding="utf-8") as file:
            writer = csv.DictWriter(file, fieldnames=["date", "tic", *price_fields])
            writer.writeheader()
            writer.writerows(sorted(rows, key=lambda row: row["date"]))
        return service.register(
            name=f"AnalystVerse · {symbol} 日线", market="CN",
            files={"prices": "prices.csv"}, available_modalities=["prices"],
            storage_mode="copy", source_dir=temp_dir, version=version, dataset_id=dataset_id,
            provenance=f"AnalystVerse 本地行情快照：{source.name}，价格口径沿用原文件",
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("symbol")
    parser.add_argument("csv_file", type=Path)
    args = parser.parse_args()
    dataset = register(args.csv_file, args.symbol)
    print(dataset["dataset_id"], dataset["date_range"])

