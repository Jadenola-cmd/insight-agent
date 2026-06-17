from pathlib import Path

API_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = API_DIR / "data"


def session_dir(session_id: str) -> Path:
    return DATA_DIR / session_id


def raw_data_path(session_id: str) -> Path:
    return session_dir(session_id) / "raw.csv"


def cleaned_data_path(session_id: str) -> Path:
    return session_dir(session_id) / "cleaned.parquet"


def merged_data_path(session_id: str) -> Path:
    return session_dir(session_id) / "merged.parquet"


def report_pdf_path(session_id: str) -> Path:
    return session_dir(session_id) / "report.pdf"
