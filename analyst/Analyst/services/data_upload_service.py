"""用户数据上传与记忆库解压。"""

from __future__ import annotations

import shutil
import zipfile
from datetime import datetime
from pathlib import Path

from config import get_path_config
from services.runtime_config import validate_symbol_token
from services.symbol_service import get_symbol_data_status, register_stock_name

ALLOWED_EXTENSIONS = {".csv", ".zip", ".json"}
DATA_TYPES = {
    "technical_indicators",
    "news",
    "fundamentals",
    "fundamentals_balance",
    "fundamentals_income",
    "fundamentals_cashflow",
    "result",
    "train_memory_zip",
    "test_memory_zip",
}


class DataUploadError(ValueError):
    pass


def _ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def _backup_dir(target: Path) -> Path | None:
    if not target.exists():
        return None
    backup = target.with_name(
        f"{target.name}.bak_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    )
    shutil.move(str(target), str(backup))
    return backup


def _extract_memory_zip(zip_path: Path, target_dir: Path) -> Path | None:
    _backup_dir(target_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "r") as zf:
        for member in zf.namelist():
            if member.endswith("/") or ".." in Path(member).parts:
                continue
            dest = target_dir / Path(member).name
            with zf.open(member) as src, dest.open("wb") as out:
                shutil.copyfileobj(src, out)
    return target_dir


def save_uploaded_file(
    symbol: str,
    data_type: str,
    filename: str,
    content: bytes,
    data_overrides: dict | None = None,
) -> dict:
    code = validate_symbol_token(symbol)
    if data_type not in DATA_TYPES:
        raise DataUploadError(f"不支持的数据类型: {data_type}")

    suffix = Path(filename).suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise DataUploadError("仅支持 csv / zip / json 文件")

    paths = get_path_config(data_overrides)
    data_dir = paths["data_dir"]
    result_dir = paths["result"]
    data_cache = paths["data_cache"]

    saved_path: Path

    if data_type == "technical_indicators":
        saved_path = data_dir / "technical_indicators" / f"{code}.csv"
        _ensure_parent(saved_path)
        saved_path.write_bytes(content)
    elif data_type == "news":
        saved_path = data_dir / "news" / f"{code}.csv"
        _ensure_parent(saved_path)
        saved_path.write_bytes(content)
    elif data_type == "result":
        saved_path = result_dir / f"{code}.csv"
        _ensure_parent(saved_path)
        saved_path.write_bytes(content)
    elif data_type == "fundamentals":
        saved_path = data_dir / "fundamentals" / "Balance Sheet" / f"{code}.csv"
        _ensure_parent(saved_path)
        saved_path.write_bytes(content)
    elif data_type == "fundamentals_balance":
        saved_path = data_dir / "fundamentals" / "Balance Sheet" / f"{code}.csv"
        _ensure_parent(saved_path)
        saved_path.write_bytes(content)
    elif data_type == "fundamentals_income":
        saved_path = data_dir / "fundamentals" / "Income Statement" / f"{code}.csv"
        _ensure_parent(saved_path)
        saved_path.write_bytes(content)
    elif data_type == "fundamentals_cashflow":
        saved_path = data_dir / "fundamentals" / "Cash Flow Statement" / f"{code}.csv"
        _ensure_parent(saved_path)
        saved_path.write_bytes(content)
    elif data_type in {"train_memory_zip", "test_memory_zip"}:
        if suffix != ".zip":
            raise DataUploadError("记忆库上传必须为 zip 文件")
        mode = "train" if data_type == "train_memory_zip" else "test"
        target_dir = data_cache / code / mode
        tmp_zip = data_cache / code / f".upload_{mode}.zip"
        tmp_zip.parent.mkdir(parents=True, exist_ok=True)
        tmp_zip.write_bytes(content)
        backup = _backup_dir(target_dir) if target_dir.exists() else None
        try:
            _extract_memory_zip(tmp_zip, target_dir)
        except Exception as exc:
            if backup and backup.exists() and not target_dir.exists():
                shutil.move(str(backup), str(target_dir))
            raise DataUploadError(f"记忆库解压失败: {exc}") from exc
        finally:
            tmp_zip.unlink(missing_ok=True)
        saved_path = target_dir
    else:
        raise DataUploadError(f"未实现的数据类型: {data_type}")

    status = get_symbol_data_status(code, data_overrides)
    return {
        "success": True,
        "symbol": code,
        "dataType": data_type,
        "savedPath": str(saved_path),
        "dataStatus": status,
    }
