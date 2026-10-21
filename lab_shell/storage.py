"""Local SQLite history. Never stores API keys or captured command output."""

import os
import sqlite3
from pathlib import Path


def default_data_dir() -> Path:
    return Path(os.getenv("XDG_DATA_HOME", str(Path.home() / ".local" / "share"))) / "lab-shell"


class History:
    def __init__(self, directory: Path):
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        path = directory / "history.sqlite3"
        self.db = sqlite3.connect(path)
        # Private permissions on Unix; Windows permissions remain governed by ACLs.
        if os.name == "posix":
            path.chmod(0o600)
        self.db.row_factory = sqlite3.Row
        self.db.execute("""CREATE TABLE IF NOT EXISTS history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
            mode TEXT NOT NULL, prompt TEXT NOT NULL, answer TEXT NOT NULL,
            command TEXT NOT NULL, source TEXT NOT NULL,
            favorite INTEGER NOT NULL DEFAULT 0)""")
        self.db.commit()

    def add(self, mode, prompt, answer):
        with self.db:
            cursor = self.db.execute(
                "INSERT INTO history(mode,prompt,answer,command,source) VALUES(?,?,?,?,?)",
                (mode, prompt, answer.text, answer.command, answer.source),
            )
        return cursor.lastrowid

    def list(self, search="", limit=20, favorites=False):
        # instr gives literal substring matching; '%' and '_' have no wildcard meaning.
        return [dict(row) for row in self.db.execute(
            "SELECT * FROM history WHERE (instr(prompt,?) OR instr(answer,?) OR instr(command,?) OR ?='') "
            "AND (?=0 OR favorite=1) ORDER BY id DESC LIMIT ?",
            (search, search, search, search, int(favorites), limit),
        )]

    def favorite(self, record_id, remove=False):
        with self.db:
            result = self.db.execute("UPDATE history SET favorite=? WHERE id=?", (int(not remove), record_id))
        return bool(result.rowcount)

    def clear(self):
        with self.db:
            self.db.execute("DELETE FROM history")

    def close(self):
        self.db.close()
