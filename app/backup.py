"""Complete local snapshots, empty-folder restore, and explicit case exports."""

import csv
import hashlib
import html
import json
import logging
import os
import shutil
import sqlite3
import tempfile
import uuid
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from app import constants, db

logger = logging.getLogger(__name__)


def _no_links(path: Path) -> None:
    for item in (path, *path.parents):
        if item.is_symlink() or item.is_junction():
            raise ValueError("Backup and restore paths cannot contain symbolic links or junctions.")


def _items(root: Path):
    pending = [root]
    while pending:
        for item in pending.pop().iterdir():
            _no_links(item)
            if item.is_dir():
                pending.append(item)
            elif not item.is_file():
                raise ValueError("The folder contains an unsupported filesystem item.")
            yield item


def _file(root: Path, relative: str) -> Path:
    if not isinstance(relative, str) or "\\" in relative or ":" in relative or "\x00" in relative:
        raise ValueError("Invalid relative document path.")
    parts = PurePosixPath(relative).parts
    if not parts or relative != "/".join(parts) or any(part in (".", "..", "/") for part in parts):
        raise ValueError("A backup path must stay within its snapshot.")
    if relative != "app.db" and (parts[0] != "documents" or len(parts) < 2):
        raise ValueError("Only the database and document files belong in a backup.")
    path = root.joinpath(*parts)
    _no_links(path)
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError("A backup path points outside its snapshot.")
    return path


def _hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _readonly(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only = ON")
    connection.execute("PRAGMA trusted_schema = OFF")
    return connection


def _database_details(path: Path) -> tuple[int, dict, dict]:
    with closing(_readonly(path)) as connection:
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        maximum = len(list(constants.MIGRATIONS_DIR.glob("[0-9][0-9][0-9]_*.sql")))
        if not 1 <= version <= maximum:
            raise ValueError("The backup has an unsupported database schema version.")
        if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("The backup database failed its integrity check.")
        if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
            raise ValueError("The backup database contains broken record references.")
        tables = [row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )]
        counts = {table: connection.execute(
            'SELECT count(*) FROM "' + table.replace('"', '""') + '"'
        ).fetchone()[0] for table in tables}
        required = {"settings"}
        if version >= 2:
            required.add("checks")
        if version >= 3:
            required.update(("cases", "companies", "case_companies", "documents", "blocks", "blocks_fts"))
        if version >= 5:
            required.add("scenarios")
        if version >= 6:
            required.add("decisions")
        if version >= 7:
            required.add("sec_imports")
        if version >= 8:
            required.update(("model_runs", "summaries"))
        if version >= 9:
            required.add('facts')
        if not required.issubset(tables):
            raise ValueError("The backup is missing required research tables.")
        references = {}
        if "documents" in tables:
            for row in connection.execute(
                "SELECT original_path, original_sha256, clean_html_path, canonical_text, text_hash FROM documents"
            ):
                original = row["original_path"]
                if original == "app.db" or row["clean_html_path"] == "app.db":
                    raise ValueError("A document path cannot refer to the research database.")
                if original in references and references[original] != row["original_sha256"]:
                    raise ValueError("Document records disagree about their original file hash.")
                references[original] = row["original_sha256"]
                if row["clean_html_path"] is not None:
                    if row["clean_html_path"] in references and references[row["clean_html_path"]] is not None:
                        raise ValueError("An original file and cleaned file cannot share a path.")
                    references[row["clean_html_path"]] = None
                    actual = hashlib.sha256(row["canonical_text"].encode("utf-8")).hexdigest()
                    if actual != row["text_hash"]:
                        raise ValueError("A saved document text version failed its hash check.")
        return version, counts, references


def _validate_snapshot(snapshot: Path) -> dict:
    _no_links(snapshot)
    manifest_path = snapshot / "manifest.json"
    _no_links(manifest_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict) or manifest.get("format_version") != 1 or manifest.get("complete") is not True:
        raise ValueError("This backup is incomplete or has an unsupported manifest.")
    created = datetime.fromisoformat(manifest["created_at"])
    if created.tzinfo is None:
        raise ValueError("The backup creation date has no time zone.")
    entries = manifest.get("files")
    if not isinstance(entries, dict) or "app.db" not in entries:
        raise ValueError("The backup manifest has no database file.")
    for relative, expected in entries.items():
        path = _file(snapshot, relative)
        if not path.is_file() or not isinstance(expected, dict):
            raise ValueError("A required backup file is missing.")
        if path.stat().st_size != expected.get("size") or _hash(path) != expected.get("sha256"):
            raise ValueError("A backup file failed its size or SHA-256 check.")
    actual_files = set()
    for path in _items(snapshot):
        _no_links(path)
        if path.is_file():
            actual_files.add(path.relative_to(snapshot).as_posix())
    if actual_files != set(entries) | {"manifest.json"}:
        raise ValueError("The snapshot contains files outside its manifest.")
    version, counts, references = _database_details(snapshot / "app.db")
    if version != manifest.get("schema_version") or counts != manifest.get("row_counts"):
        raise ValueError("The backup database does not match its manifest.")
    if set(entries) != {"app.db", *references}:
        raise ValueError("The backup does not contain exactly the referenced document files.")
    for relative, expected_hash in references.items():
        if expected_hash is not None and entries[relative]["sha256"] != expected_hash:
            raise ValueError("An original document does not match its saved hash.")
    return manifest


def _remove_owned(folder: Path, parent: Path) -> None:
    # Only generated direct children of the explicitly supplied directory are removed.
    _no_links(folder)
    if folder.resolve().parent != parent.resolve() or folder.resolve() == parent.resolve():
        raise ValueError("Refusing to remove a folder outside the intended directory.")
    for item in _items(folder):
        _no_links(item)
    shutil.rmtree(folder)


def _discard(folder: Path, parent: Path) -> None:
    if folder.exists():
        try:
            _remove_owned(folder, parent)
        except OSError:
            logger.exception("Could not clean up the incomplete operation folder: %s", folder)


def list_backups(backup_root: Path, *, warnings: list[str] | None = None) -> list[dict]:
    backup_root = Path(backup_root).absolute()
    _no_links(backup_root)
    try:
        candidates = list(backup_root.iterdir())
    except FileNotFoundError:
        return []
    results = []
    for snapshot in candidates:
        if not snapshot.name.startswith("backup-"):
            continue
        try:
            manifest = _validate_snapshot(snapshot)
        except (OSError, ValueError, TypeError, KeyError, sqlite3.Error) as error:
            logger.exception("Backup was excluded because verification failed: %s", snapshot)
            if warnings is not None:
                warnings.append(f"{snapshot.name} was excluded because verification failed: {error}")
            continue
        results.append({
            "name": snapshot.name, "path": str(snapshot),
            "created_at": manifest["created_at"], "schema_version": manifest["schema_version"],
        })
    return sorted(results, key=lambda item: item["created_at"], reverse=True)


def _retain(backup_root: Path) -> None:
    for item in list_backups(backup_root)[constants.BACKUP_KEEP:]:
        _remove_owned(Path(item["path"]), backup_root)


def create_backup(data_dir: Path, second_folder: Path | None = None) -> dict:
    data_dir = Path(data_dir).absolute()
    _no_links(data_dir)
    if not _file(data_dir, "app.db").is_file():
        raise ValueError("There is no research database to back up.")
    root = data_dir / "backups"
    _no_links(root)
    root.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc)
    # Keep the published path no longer than the successfully verified staging path.
    name = f"backup-{uuid.uuid4().hex[:12]}"
    stage = Path(tempfile.mkdtemp(prefix=".incomplete-", dir=root))
    final = root / name
    warnings = []
    with db.DATA_LOCK:
        try:
            with closing(_readonly(data_dir / "app.db")) as source:
                with closing(sqlite3.connect(stage / "app.db")) as target:
                    source.backup(target)
            version, counts, references = _database_details(stage / "app.db")
            for relative, expected_hash in references.items():
                source_path = _file(data_dir, relative)
                destination = _file(stage, relative)
                if not source_path.is_file():
                    raise ValueError("A referenced document file is missing; backup was not completed.")
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source_path, destination)
                if expected_hash is not None and _hash(destination) != expected_hash:
                    raise ValueError("An original document file has changed; backup was not completed.")
            entries = {}
            for relative in ("app.db", *references):
                path = _file(stage, relative)
                entries[relative] = {"size": path.stat().st_size, "sha256": _hash(path)}
            manifest = {
                "format_version": 1, "complete": True, "created_at": stamp.isoformat(),
                "schema_version": version, "row_counts": counts, "files": entries,
            }
            (stage / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
            _validate_snapshot(stage)
            stage.rename(final)
        except Exception:
            _discard(stage, root)
            raise
        if second_folder is None:
            warnings.append("No second backup folder is selected. Only the local backup was made.")
        else:
            second_root = Path(second_folder).absolute()
            second_stage = None
            try:
                _no_links(second_root)
                if second_root.resolve() == root.resolve() or second_root.resolve().is_relative_to(final.resolve()):
                    raise ValueError("The second backup folder must be separate from this snapshot.")
                second_root.mkdir(parents=True, exist_ok=True)
                if data_dir.stat().st_dev == second_root.stat().st_dev:
                    warnings.append("The second folder is on the same volume; it does not protect against that volume failing.")
                second_stage = Path(tempfile.mkdtemp(prefix=".incomplete-", dir=second_root))
                shutil.copytree(final, second_stage, dirs_exist_ok=True)
                _validate_snapshot(second_stage)
                second_stage.rename(second_root / name)
                _retain(second_root)
            except (OSError, ValueError, TypeError, KeyError, sqlite3.Error) as error:
                logger.exception("The second backup could not be completed.")
                warnings.append(f"The local backup is complete, but the second copy failed: {error}")
                if second_stage is not None:
                    _discard(second_stage, second_root)
        try:
            _retain(root)
        except OSError:
            logger.exception("Older complete backups could not be removed.")
            warnings.append("The new backup is complete, but older backups could not be removed.")
    return {"path": str(final), "warning": " ".join(warnings) or None}


def _empty_target(target: Path) -> None:
    _no_links(target)
    if not target.exists():
        return
    if not target.is_dir():
        raise ValueError("Restore needs an empty research folder.")
    for item in _items(target):
        _no_links(item)
        if item.is_file() and item != target / "app.log":
            raise ValueError("Restore requires an empty research folder and never overwrites an existing database or file.")
        if not item.is_file() and not item.is_dir():
            raise ValueError("Restore found an unsupported item in the destination.")


def restore_backup(snapshot_dir: Path, target_data_dir: Path) -> dict:
    snapshot = Path(snapshot_dir).absolute()
    target = Path(target_data_dir).absolute()
    with db.DATA_LOCK:
        manifest = _validate_snapshot(snapshot)
        _empty_target(target)
        if snapshot.resolve().is_relative_to(target.resolve()):
            raise ValueError("The backup must be outside the empty restore destination.")
        target.parent.mkdir(parents=True, exist_ok=True)
        stage = Path(tempfile.mkdtemp(prefix=f".{target.name}-restore-", dir=target.parent))
        published = []
        new_directories = []
        try:
            shutil.copytree(snapshot, stage, dirs_exist_ok=True)
            if _validate_snapshot(stage) != manifest:
                raise ValueError("The selected backup changed while being copied. Verify and select it again.")
            _empty_target(target)
            for relative in [name for name in manifest["files"] if name != "app.db"] + ["app.db"]:
                destination = _file(target, relative)
                missing = []
                parent = destination.parent
                while not parent.exists():
                    missing.append(parent)
                    parent = parent.parent
                for parent in reversed(missing):
                    parent.mkdir()
                    new_directories.append(parent)
                # A hard link publishes each complete staged file atomically and refuses overwrite.
                # The stage is a sibling, so source and destination are on the same volume.
                os.link(_file(stage, relative), destination)
                published.append(destination)
        except Exception:
            cleanup_failed = False
            for path in reversed(published):
                try:
                    path.unlink()
                except OSError:
                    cleanup_failed = True
                    logger.exception("Could not roll back a newly restored file: %s", path)
            for directory in reversed(new_directories):
                try:
                    directory.rmdir()
                except OSError:
                    cleanup_failed = True
                    logger.exception("Could not remove a newly created restore directory: %s", directory)
            if cleanup_failed:
                logger.error("Restore cleanup is incomplete; retain the original snapshot and use an empty destination.")
            raise
        finally:
            _discard(stage, target.parent)
    return {
        "path": str(target), "schema_version": manifest["schema_version"],
        "warning": "Credentials must be entered again. This restore does not install the app or its dependencies.",
    }


def _plain(value) -> str:
    text = "unknown" if value is None else str(value)
    return html.escape(text).replace("\\", "\\\\").replace("`", "\\`").replace("[", "\\[").replace("]", "\\]")


def _json_section(title: str, raw: str) -> list[str]:
    value = json.loads(raw)
    # Indented code keeps saved JSON, quotes and offsets readable without interpreting HTML.
    return [f"{title}:", "", *("    " + line for line in json.dumps(value, indent=2, ensure_ascii=False).splitlines()), ""]


def export_case(data_dir: Path, case_id: int, destination_dir: Path) -> dict:
    destination_dir = Path(destination_dir).absolute()
    _no_links(destination_dir)
    destination_dir.mkdir(parents=True, exist_ok=True)
    with db.DATA_LOCK, closing(db.connect(data_dir)) as connection:
        case = connection.execute("SELECT * FROM cases WHERE id = ?", (case_id,)).fetchone()
        if case is None:
            raise ValueError("This case does not exist.")
        documents = connection.execute(
            "SELECT id, logical_document_id, name, source_url, retrieved_at, filing_date, accession_number, "
            "form_type, exhibit_label, original_sha256, cleaner_version, text_hash FROM documents WHERE case_id = ? ORDER BY id",
            (case_id,),
        ).fetchall()
        scenarios = connection.execute("SELECT * FROM scenarios WHERE case_id = ? ORDER BY id", (case_id,)).fetchall()
        decisions = connection.execute("SELECT * FROM decisions WHERE case_id = ? ORDER BY id", (case_id,)).fetchall()
        fact_records = []
        if connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='facts'").fetchone():
            for row in connection.execute(
                "SELECT f.*, d.name AS document_name, d.source_url, d.filing_date, d.original_sha256, "
                "d.cleaner_version, d.text_hash FROM facts f LEFT JOIN documents d ON d.id=f.document_id "
                "WHERE f.case_id=? ORDER BY f.id", (case_id,),
            ):
                record = dict(row)
                record['value'] = json.loads(record.pop('value_json'))
                record['evidence'] = json.loads(record.pop('evidence_json'))
                fact_records.append(record)
        sec_imports = []
        if connection.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'sec_imports'").fetchone():
            sec_imports = connection.execute(
                "SELECT * FROM sec_imports WHERE case_id = ? ORDER BY id", (case_id,),
            ).fetchall()
        lines = [f"# {_plain(case['title'])}", "", f"Case ID: {case_id}", f"Created: {_plain(case['created_at'])}"]
        for field in ("status", "question", "updated_at"):
            if field in case.keys():
                lines.extend(["", f"{field.replace('_', ' ').capitalize()}: {_plain(case[field])}"])
        lines.extend(["", "## Summary, facts and questions", ""])
        summary = None
        if connection.execute("SELECT 1 FROM sqlite_master WHERE name='summaries'").fetchone():
            from app.cases import summary_status

            summary = summary_status(data_dir, case_id)['summary']
        if summary:
            lines.extend(_json_section("Saved summary, source portion and verified citation offsets", json.dumps(summary)))
            lines.extend(["Quote matching checks source wording, not interpretation. This summary covers only the recorded portion.", ""])
        else:
            lines.extend(["No model summary has been produced for this case.", ""])
        if fact_records:
            lines.extend(["## Saved facts and correction history", "",
                          "Every saved proposal and correction is included below and in facts.csv. Earlier rows remain historical records; only the owner marks facts checked.", ""])
            for record in fact_records:
                lines.extend(_json_section(f"Fact {record['id']}: {record['fact_key']}", json.dumps(record)))
        else:
            lines.extend(["No extracted facts have been saved for this case. The facts CSV contains its header only.", ""])
        lines.extend(["Document answers have not been produced.", "", "## Document versions", ""])
        for document in documents:
            lines.extend([f"### Document {document['id']}: {_plain(document['name'])}", ""])
            lines.extend(f"- {key.replace('_', ' ')}: {_plain(document[key])}" for key in document.keys())
            lines.append("")
        if not documents:
            lines.extend(["No documents have been saved for this case.", ""])
        lines.extend(["## SEC filing import records", ""])
        for filing in sec_imports:
            lines.extend([f"### Filing import {filing['id']}", ""])
            lines.extend(f"- {key.replace('_', ' ')}: {_plain(filing[key])}"
                         for key in filing.keys() if key != "items_json")
            lines.append("")
            lines.extend(_json_section("Filing document statuses", filing["items_json"]))
        if not sec_imports:
            lines.extend(["No SEC filing imports have been recorded for this case.", ""])
        lines.extend(["## Saved scenarios", ""])
        for scenario in scenarios:
            lines.extend([f"### Scenario {scenario['id']}: {_plain(scenario['name'])}", "", f"Kind: {_plain(scenario['kind'])}", f"Saved: {_plain(scenario['created_at'])}", ""])
            for field in ("inputs_json", "outputs_json", "display_json"):
                lines.extend(_json_section(field.removesuffix("_json").capitalize(), scenario[field]))
            if scenario["warning"]:
                lines.extend([f"Limitation: {_plain(scenario['warning'])}", ""])
        if not scenarios:
            lines.extend(["No calculation scenarios have been saved.", ""])
        lines.extend(["## Decisions and their saved references", ""])
        for decision in decisions:
            lines.extend([f"### Decision {decision['id']}", "", f"Saved: {_plain(decision['created_at'])}", f"Decision: {_plain(decision['decision'])}", "", f"Reason: {_plain(decision['reason'])}", ""])
            for field in ("document_ids_json", "scenario_ids_json", "evidence_json"):
                if field in decision.keys():
                    lines.extend(_json_section(field.removesuffix("_json").replace("_", " ").capitalize(), decision[field]))
        if not decisions:
            lines.extend(["No decisions have been saved.", ""])
    folder = Path(tempfile.mkdtemp(prefix=f"case-{case_id}-", dir=destination_dir))
    markdown = folder / "case.md"
    facts = folder / "facts.csv"
    try:
        markdown.write_text("\n".join(lines), encoding="utf-8")
        with facts.open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow(["fact_id", "fact_key", "value", "unit", "currency", "entity", "period", "basis", "kind",
                             "finding", "status", "origin", "created_at", "previous_id", "run_id", "reason", "qualifications",
                             "source_url", "document_id", "document_name", "filing_date", "original_sha256", "cleaner_version",
                             "text_hash", "quote", "evidence_json"])
            for record in fact_records:
                value = record['value']
                quotes = [(entry.get('citation', entry) or {}).get('quote', '') for entry in record['evidence']]
                writer.writerow([
                    record['id'], record['fact_key'], *(value.get(key) for key in
                    ('value', 'unit', 'currency', 'entity', 'period', 'basis', 'kind', 'finding')),
                    record['status'], record['origin'], record['created_at'], record['previous_id'], record['run_id'],
                    value.get('reason'), value.get('qualifications'),
                    *(record[key] for key in ('source_url', 'document_id', 'document_name', 'filing_date',
                                             'original_sha256', 'cleaner_version', 'text_hash')),
                    '\n'.join(quotes), json.dumps(record['evidence'], ensure_ascii=False),
                ])
    except Exception:
        _discard(folder, destination_dir)
        raise
    warning = "Document answers have not been produced."
    if not fact_records:
        warning += " No extracted facts have been saved; facts.csv has a header only."
    return {"paths": [str(markdown), str(facts)], "warning": warning}
