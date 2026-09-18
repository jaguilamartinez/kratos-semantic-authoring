import hashlib
import json
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Literal
from uuid import UUID, uuid4

from pydantic import Field

from authoring.case import Case, FieldChange, StrictModel, diff_cases, diff_values
from authoring.commands import CaseCommand, ValidationReport, apply_commands, validate_case
from authoring.compiler import compile_case, load_case, render_case, write_json


class RevisionConflict(Exception):
    def __init__(self, expected: int, actual: int):
        super().__init__(f"Expected revision {expected}, current revision is {actual}")
        self.expected = expected
        self.actual = actual


class DraftConflict(Exception):
    pass


@dataclass(frozen=True)
class Snapshot:
    case: Case
    bundle_id: str


@dataclass(frozen=True)
class ChangeResult:
    snapshot: Snapshot
    changes: list[FieldChange]


class DraftMessage(StrictModel):
    role: Literal["user", "assistant"]
    content: str


class DraftChangeSet(StrictModel):
    sequence: int
    changes: list[FieldChange]
    native_changes: list[FieldChange]


class Draft(StrictModel):
    id: str
    base_revision: int
    content_hash: str
    case: Case
    changes: list[FieldChange]
    native_changes: list[FieldChange]
    validation: ValidationReport | None = None
    validated_hash: str | None = None
    messages: list[DraftMessage] = Field(default_factory=list)
    change_log: list[DraftChangeSet] = Field(default_factory=list)
    status: Literal["editing", "published"] = "editing"
    published_revision: int | None = None


def content_hash(case: Case) -> str:
    content = json.dumps(case.model_dump(mode="json"), sort_keys=True, allow_nan=False)
    return hashlib.sha256(content.encode()).hexdigest()


class CaseStore:
    def __init__(self, template_dir: Path, workspace_dir: Path) -> None:
        self.template_dir = template_dir
        self.workspace_dir = workspace_dir
        self.revisions_dir = workspace_dir / "revisions"
        self.drafts_dir = workspace_dir / "drafts"
        self.validation_dir = workspace_dir / "validation"
        self.current_path = workspace_dir / "current.json"
        self.lock = Lock()
        for directory in (self.revisions_dir, self.drafts_dir, self.validation_dir):
            directory.mkdir(parents=True, exist_ok=True)
        with self.lock:
            if not self.current_path.exists():
                self._publish(load_case(template_dir), template_dir)

    @staticmethod
    def bundle_id(revision: int) -> str:
        return f"revision-{revision:06d}"

    def _read_revision(self, revision: int) -> Snapshot:
        bundle_id = self.bundle_id(revision)
        directory = self.revisions_dir / bundle_id
        raw = json.loads((directory / "case.json").read_text())
        if raw["schema_version"] == "ksa.structural-case/0.2":
            # Old bundles remain immutable; their own inputs contain the complete case.
            case = load_case(directory, revision=revision)
        else:
            case = Case.model_validate(raw)
        if case.revision != revision:
            raise RuntimeError("Case revision does not match its bundle")
        return Snapshot(case, bundle_id)

    def _current(self) -> Snapshot:
        pointer = json.loads(self.current_path.read_text())
        if pointer["bundle_id"] != self.bundle_id(pointer["revision"]):
            raise RuntimeError("Current case pointer does not match its bundle")
        return self._read_revision(pointer["revision"])

    def read(self) -> Snapshot:
        with self.lock:
            return self._current()

    def read_revision(self, revision: int) -> Snapshot:
        with self.lock:
            return self._read_revision(revision)

    def list_revisions(self) -> list[dict[str, object]]:
        with self.lock:
            revisions = []
            for directory in sorted(self.revisions_dir.glob("revision-*")):
                raw = json.loads((directory / "case.json").read_text())
                revisions.append({
                    "revision": raw["revision"], "bundle_id": directory.name,
                    "problem_name": raw["problem_name"], "schema_version": raw["schema_version"],
                })
            return revisions

    def _assert_revision(self, expected: int) -> Snapshot:
        current = self._current()
        if current.case.revision != expected:
            raise RevisionConflict(expected, current.case.revision)
        return current

    def editing_case(self, expected_revision: int, draft_id: str | None = None) -> Case:
        with self.lock:
            current = self._assert_revision(expected_revision)
            if draft_id is None:
                return current.case
            draft = self._read_draft(draft_id)
            self._assert_editable(draft, draft.content_hash)
            if draft.base_revision != expected_revision:
                raise RevisionConflict(draft.base_revision, expected_revision)
            return draft.case

    def _draft_path(self, draft_id: str) -> Path:
        return self.drafts_dir / f"{UUID(draft_id)}.json"

    def _read_draft(self, draft_id: str) -> Draft:
        return Draft.model_validate_json(self._draft_path(draft_id).read_text())

    def read_draft(self, draft_id: str) -> Draft:
        with self.lock:
            return self._read_draft(draft_id)

    def list_drafts(self) -> list[Draft]:
        with self.lock:
            return [Draft.model_validate_json(path.read_text())
                    for path in sorted(self.drafts_dir.glob("*.json"))]

    @staticmethod
    def _assert_editable(draft: Draft, expected_hash: str) -> None:
        if draft.status != "editing":
            raise DraftConflict("This draft has already been published")
        if draft.content_hash != expected_hash:
            raise DraftConflict("The draft changed; reload it before continuing")

    def _save_draft(self, draft: Draft) -> Draft:
        self._write_atomic(self._draft_path(draft.id), draft.model_dump(mode="json"))
        return draft

    def stage(self, expected_revision: int, edited: Case, draft_id: str | None = None,
              expected_hash: str | None = None,
              messages: list[DraftMessage] | None = None) -> Draft:
        with self.lock:
            base = self._assert_revision(expected_revision).case
            existing = self._read_draft(draft_id) if draft_id else None
            if existing:
                self._assert_editable(existing, expected_hash or "")
                if existing.base_revision != expected_revision:
                    raise RevisionConflict(existing.base_revision, expected_revision)
            candidate = edited.model_copy(deep=True, update={"revision": expected_revision})
            digest = content_hash(candidate)
            if existing and digest == existing.content_hash:
                if messages is None or messages == existing.messages:
                    return existing
                existing.messages = messages
                return self._save_draft(existing)
            conversation = messages if messages is not None else []
            if existing and messages is None:
                conversation = existing.messages
            old_native = dict(zip(("ProjectParameters", "Materials"), render_case(base)))
            new_native = dict(zip(("ProjectParameters", "Materials"), render_case(candidate)))
            previous = existing.case if existing else base
            previous_native = dict(zip(("ProjectParameters", "Materials"), render_case(previous)))
            step_changes = diff_cases(previous, candidate)
            step_native_changes = diff_values(previous_native, new_native)
            change_log = list(existing.change_log) if existing else []
            if existing and not change_log and (existing.changes or existing.native_changes):
                change_log.append(DraftChangeSet(
                    sequence=1,
                    changes=existing.changes,
                    native_changes=existing.native_changes,
                ))
            if step_changes or step_native_changes:
                change_log.append(DraftChangeSet(
                    sequence=len(change_log) + 1,
                    changes=step_changes,
                    native_changes=step_native_changes,
                ))
            return self._save_draft(Draft(
                id=existing.id if existing else str(uuid4()), base_revision=expected_revision,
                case=candidate, content_hash=digest, changes=diff_cases(base, candidate),
                native_changes=diff_values(old_native, new_native),
                messages=conversation,
                change_log=change_log,
            ))

    def propose(self, expected_revision: int, commands: list[CaseCommand],
                draft_id: str | None = None, expected_hash: str | None = None) -> Draft:
        case = self.editing_case(expected_revision, draft_id)
        return self.stage(expected_revision, apply_commands(case, commands), draft_id, expected_hash)

    def validate_draft(self, draft_id: str, expected_hash: str) -> Draft:
        with self.lock:
            draft = self._read_draft(draft_id)
            self._assert_editable(draft, expected_hash)
            self._assert_revision(draft.base_revision)
            report = validate_case(draft.case)
            if report.valid:
                destination = self.validation_dir / draft.content_hash
                if not destination.exists():
                    assets = self.revisions_dir / self.bundle_id(draft.base_revision)
                    compile_case(draft.case, assets, destination)
            draft.validation = report
            draft.validated_hash = draft.content_hash
            return self._save_draft(draft)

    def record_validation(self, draft_id: str, expected_hash: str,
                          report: ValidationReport) -> Draft:
        with self.lock:
            draft = self._read_draft(draft_id)
            self._assert_editable(draft, expected_hash)
            draft.validation = report
            draft.validated_hash = expected_hash
            return self._save_draft(draft)

    def publish_draft(self, draft_id: str, expected_hash: str,
                      require_native: bool = False) -> ChangeResult:
        with self.lock:
            draft = self._read_draft(draft_id)
            self._assert_editable(draft, expected_hash)
            current = self._assert_revision(draft.base_revision)
            report = draft.validation
            if draft.validated_hash != draft.content_hash or report is None or not report.valid:
                raise ValueError("Validate this version of the draft before publishing")
            if require_native and report.execution_supported and report.native_check != "passed":
                raise ValueError("A successful Kratos check is required before publishing")
            changes = diff_cases(current.case, draft.case)
            snapshot = current
            if changes:
                revised = draft.case.model_copy(deep=True, update={"revision": current.case.revision + 1})
                assets = self.revisions_dir / current.bundle_id
                snapshot = self._publish(revised, assets, report)
            draft.status = "published"
            draft.published_revision = snapshot.case.revision
            self._save_draft(draft)
            return ChangeResult(snapshot, changes)

    @staticmethod
    def _write_atomic(path: Path, value: object) -> None:
        pending = path.with_name(f".{path.name}-{uuid4().hex}")
        try:
            write_json(pending, value)
            os.replace(pending, path)
        finally:
            pending.unlink(missing_ok=True)

    def _publish(self, case: Case, assets: Path,
                 validation: ValidationReport | None = None) -> Snapshot:
        bundle_id = self.bundle_id(case.revision)
        destination = self.revisions_dir / bundle_id
        if destination.exists():
            existing = Case.model_validate_json((destination / "case.json").read_text())
            if existing != case:
                raise FileExistsError(f"Revision already exists: {case.revision}")
        else:
            pending = self.revisions_dir / f".{bundle_id}-{uuid4().hex}"
            try:
                compile_case(case, assets, pending)
                report = validation or validate_case(case)
                write_json(pending / "validation.json", report.model_dump(mode="json"))
                os.replace(pending, destination)
            except Exception:
                shutil.rmtree(pending, ignore_errors=True)
                raise
        self._write_atomic(self.current_path, {"revision": case.revision, "bundle_id": bundle_id})
        return Snapshot(case, bundle_id)
