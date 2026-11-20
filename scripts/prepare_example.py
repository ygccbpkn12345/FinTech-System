"""Copy bundled examples if missing and register the real 000063 OHLCV snapshot."""
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]

def main():
    source = ROOT / "examples/analyst"
    target = ROOT / "analyst/Analyst"
    for path in source.rglob("*.csv"):
        destination = target / path.relative_to(source)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if not destination.exists():
            shutil.copy2(path, destination)
    subprocess.run([
        sys.executable,
        str(ROOT / "System/FinPortfolio_MVP/scripts/register_analystverse_prices.py"),
        "000063", str(ROOT / "examples/data/000063_prices.csv"),
    ], check=True, cwd=ROOT)

if __name__ == "__main__":
    main()
