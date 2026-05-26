"""Import sample command history CSV data into MySQL."""

from pathlib import Path
from typing import Optional

import pandas as pd
from sqlalchemy import create_engine

from src.config import DB_HOST, DB_NAME, DB_PORT, DB_URL, DB_USER


CSV_PATH = "data/command_history_with_hacker.csv"
IF_EXISTS = "append"
HEADER = 0

INSERT_COLUMNS = [
    "user_name",
    "command",
    "timestamp",
    "current_dir",
    "client_ip",
    "server_ip",
    "exit_code",
    "session_id",
]


def import_csv_to_command_history(
    csv_path: str,
    db_url: str,
    table_name: str = "command_history",
    if_exists: str = "append",
    header: Optional[int] = 0,
) -> None:
    """Bulk insert a CSV file into the command_history table."""
    df = pd.read_csv(
        csv_path,
        header=header,
        # names=[
        #     "id",
        #     "user_name",
        #     "command",
        #     "timestamp",
        #     "current_dir",
        #     "client_ip",
        #     "server_ip",
        #     "exit_code",
        #     "session_id",
        # ],
        parse_dates=["timestamp"],
    )

    df = df[INSERT_COLUMNS]

    engine = create_engine(db_url)
    df.to_sql(
        name=table_name,
        con=engine,
        if_exists=if_exists,
        index=False,
        chunksize=1000,
        method="multi",
    )

    print(f"{len(df)} rows successfully inserted into {table_name}")


def main() -> None:
    csv_file = Path(CSV_PATH)

    print("Command Watcher AI CSV import started")
    print(f"   CSV file : {csv_file.absolute()}")
    print(f"   DB       : {DB_HOST}:{DB_PORT}/{DB_NAME} (user: {DB_USER})")
    print(f"   Mode     : {IF_EXISTS}")
    print(f"   Header   : {HEADER}")
    print(f"   Columns  : {INSERT_COLUMNS}")
    print("-" * 70)

    if not csv_file.exists():
        print(f"Error: CSV file not found: {csv_file}")
        return

    try:
        import_csv_to_command_history(
            csv_path=str(csv_file),
            db_url=DB_URL,
            table_name="command_history",
            if_exists=IF_EXISTS,
            header=HEADER,
        )
        print("\nImport completed.")

    except Exception as e:
        print(f"\nImport failed: {e}")
        print("Check MySQL server status, credentials, and database existence.")


if __name__ == "__main__":
    main()
