"""python tools/restore_backup.py archive.zip --output recovered.sqlite3"""

import argparse
from pathlib import Path
import sys
import sqlite3
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backup_archive import restore_archive


def main():
    parser = argparse.ArgumentParser(description="Проверить бэкап и собрать новую базу без перезаписи старой.")
    parser.add_argument("source", help="ZIP или .backup.json рядом со всеми частями")
    parser.add_argument("--output", required=True, help="Новый, ещё не существующий файл SQLite")
    args = parser.parse_args()
    try:
        result = restore_archive(args.source, args.output)
    except (OSError, ValueError, KeyError, sqlite3.Error, zipfile.BadZipFile) as error:
        parser.exit(1, f"Ошибка: {error}\n")
    print(f"База проверена: {result}\nРабочая база бота не заменялась.")


if __name__ == "__main__":
    main()
