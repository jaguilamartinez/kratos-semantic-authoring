import json
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from uuid import uuid4

from authoring.case import (
    Case,
    CaseChanges,
    FieldChange,
    create_revision,
    update_values,
)
from authoring.compiler import compile_case, load_case, write_json


class RevisionConflict(Exception):
    def __init__(self, expected: int, actual: int):
        super().__init__(f"Expected revision {expected}, current revision is {actual}")
        self.expected = expected
        self.actual = actual


@dataclass(frozen=True)
class Snapshot:
    case: Case
    bundle_id: str


@dataclass(frozen=True)
class ChangeResult:
    snapshot: Snapshot
    changes: list[FieldChange]


class CaseStore:
    def __init__(
        self,
        template_dir: Path,
        workspace_dir: Path,
    ) -> None:
        self.template_dir = template_dir
        self.workspace_dir = workspace_dir
        self.revisions_dir = workspace_dir / "revisions"
        self.current_path = workspace_dir / "current.json"
        self.lock = Lock()

        self.revisions_dir.mkdir(parents=True, exist_ok=True)
        with self.lock:
            if not self.current_path.exists():
                self._publish(load_case(self.template_dir))

    @staticmethod
    def bundle_id(revision: int) -> str:
        return f"revision-{revision:06d}"

    def _read_unlocked(self) -> Snapshot:
        pointer = json.loads(self.current_path.read_text())
        bundle_id = pointer["bundle_id"]
        case_path = self.revisions_dir / bundle_id / "case.json"
        case = Case.model_validate_json(case_path.read_text())
        if case.revision != pointer["revision"]:
            raise RuntimeError("Current case pointer does not match its bundle")
        return Snapshot(case=case, bundle_id=bundle_id)

    def read(self) -> Snapshot:
        with self.lock:
            return self._read_unlocked()

    def read_revision(self, expected_revision: int) -> Snapshot:
        snapshot = self.read()
        if snapshot.case.revision != expected_revision:
            raise RevisionConflict(expected_revision, snapshot.case.revision)
        return snapshot

    def apply(self, expected_revision: int, changes: CaseChanges) -> ChangeResult:
        with self.lock:
            current = self._read_unlocked()
            if current.case.revision != expected_revision:
                raise RevisionConflict(expected_revision, current.case.revision)

            edited = update_values(current.case, changes)
            revised, diff = create_revision(current.case, edited)
            if not diff:
                return ChangeResult(snapshot=current, changes=[])

            return ChangeResult(snapshot=self._publish(revised), changes=diff)

    def publish(self, expected_revision: int, edited: Case) -> ChangeResult:
        with self.lock:
            current = self._read_unlocked()
            if current.case.revision != expected_revision:
                raise RevisionConflict(expected_revision, current.case.revision)

            revised, diff = create_revision(current.case, edited)
            if not diff:
                return ChangeResult(snapshot=current, changes=[])

            return ChangeResult(snapshot=self._publish(revised), changes=diff)

    def _publish(self, case: Case) -> Snapshot:
        bundle_id = self.bundle_id(case.revision)
        destination = self.revisions_dir / bundle_id

        if destination.exists():
            existing = Case.model_validate_json((destination / "case.json").read_text())
            if existing != case:
                raise FileExistsError(f"Revision already exists: {case.revision}")
        else:
            pending = self.revisions_dir / f".{bundle_id}-{uuid4().hex}"
            try:
                compile_case(case, self.template_dir, pending)
                os.replace(pending, destination)
            except Exception:
                shutil.rmtree(pending, ignore_errors=True)
                raise

        pointer = {"revision": case.revision, "bundle_id": bundle_id}
        pending_pointer = self.workspace_dir / f".current-{uuid4().hex}.json"
        try:
            write_json(pending_pointer, pointer)
            os.replace(pending_pointer, self.current_path)
        finally:
            pending_pointer.unlink(missing_ok=True)

        return Snapshot(case=case, bundle_id=bundle_id)
