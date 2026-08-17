#!/usr/bin/env python3
"""Fault-injection probes for the Task 8 Step 1 publish transaction."""
from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable


def load_builder() -> Any:
    path = Path(__file__).with_name("build-review-handoffs.py").resolve()
    spec = importlib.util.spec_from_file_location("task8_review_builder", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load builder")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


B = load_builder()
LIVE_ROOT = Path(__file__).resolve().parents[3]


def clone_inputs(destination: Path) -> None:
    snapshot = B.capture(LIVE_ROOT)
    for relative, item in snapshot.items():
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(item.data)


def output_paths() -> list[Path]:
    return [B.WORK / content_id / B.HANDOFF for content_id in B.IDS] + [B.INDEX]


def visible(root: Path) -> list[str]:
    return [B.rel_text(path) for path in output_paths() if (root / path).is_file()]


def expect_recovery_gate(root: Path) -> None:
    try:
        B.verify_release(root, root)
    except B.RecoveryRequired:
        return
    raise AssertionError("verify did not fail closed while transaction journal existed")


def assert_all_consumer_gates(root: Path) -> int:
    calls = (
        lambda: B.build_release(root, root),
        lambda: B.verify_release(root, root),
        lambda: B.prove_repro(root, root),
        lambda: B.assert_consumable_review_package(root, root),
    )
    blocked = 0
    for call in calls:
        try:
            call()
        except B.RecoveryRequired:
            blocked += 1
        else:
            raise AssertionError("transaction artifact did not close every build/verify/consume gate")
    return blocked


def interrupt_at(point: str, action: Callable[[], None] | None = None) -> Callable[[str, dict[str, Any]], None]:
    def hook(actual: str, context: dict[str, Any]) -> None:
        del context
        if actual == point:
            if action is not None:
                action()
            raise KeyboardInterrupt(point)
    return hook


def probe_fresh_and_same_bytes() -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="task8-probe-fresh-") as temp:
        root = Path(temp)
        clone_inputs(root)
        _, _, _, first, _ = B.build_release(root, root)
        before = {path: B.identity((root / path).lstat()) for path in output_paths()}
        _, _, _, second, _ = B.build_release(root, root)
        after = {path: B.identity((root / path).lstat()) for path in output_paths()}
        B.verify_release(root, root)
        assert first == {"created": 11, "verified_existing_without_rewrite": 0}
        assert second == {"created": 0, "verified_existing_without_rewrite": 11}
        assert before == after and not B.transaction_artifacts(root)
        return {"fresh_created": 11, "same_bytes_created": 0, "identities_unchanged": True}


def probe_different_bytes() -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="task8-probe-different-") as temp:
        root = Path(temp)
        clone_inputs(root)
        target = root / B.INDEX
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"different")
        try:
            B.build_release(root, root)
        except FileExistsError:
            pass
        else:
            raise AssertionError("different target did not fail")
        assert target.read_bytes() == b"different"
        assert visible(root) == [B.rel_text(B.INDEX)] and not B.transaction_artifacts(root)
        return {"failed_before_journal": True, "partial_handoffs": 0, "target_untouched": True}


def probe_ordinary_oserror() -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="task8-probe-oserror-") as temp:
        root = Path(temp)
        clone_inputs(root)

        def hook(point: str, context: dict[str, Any]) -> None:
            if point == "before_link" and context["sequence"] == 2:
                raise OSError("injected ordinary I/O failure")

        try:
            B.build_release(root, root, hook)
        except OSError:
            pass
        else:
            raise AssertionError("injected OSError did not escape")
        assert not visible(root) and not B.transaction_artifacts(root)
        return {"rolled_back": True, "index_visible": False, "journal_absent": True}


def probe_first_handoff_interrupt_and_rollback() -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="task8-probe-first-") as temp:
        root = Path(temp)
        clone_inputs(root)
        try:
            B.build_release(root, root, interrupt_at("after_first_handoff"))
        except KeyboardInterrupt:
            pass
        else:
            raise AssertionError("first-handoff interrupt did not fire")
        state = B.inspect_transaction(root)
        assert state["status"] == "recovery_required" and not state["index_commit_marker_visible"]
        assert len(visible(root)) == 1
        expect_recovery_gate(root)
        recovery = B.recover_rollback(root, root)
        assert recovery["removed_owned_files"] == 1
        assert not visible(root) and not B.transaction_artifacts(root)
        return {"journal_blocked": True, "index_visible": False, "rollback_removed": 1}


def probe_atomic_journal_create_interrupt() -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="task8-probe-journal-create-") as temp:
        root = Path(temp)
        clone_inputs(root)
        try:
            B.build_release(root, root, interrupt_at("after_journal_publish"))
        except KeyboardInterrupt:
            pass
        else:
            raise AssertionError("journal-create interrupt did not fire")
        artifacts = B.transaction_artifacts(root)
        assert set(artifacts) == {B.JOURNAL}
        assert not visible(root)
        expect_recovery_gate(root)
        B.recover_finish(root, root)
        B.verify_release(root, root)
        assert len(visible(root)) == 11 and not B.transaction_artifacts(root)
        return {"partial_outputs": 0, "journal_gated": True, "finish_committed": True}


def probe_ten_handoffs_interrupt_and_finish() -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="task8-probe-ten-") as temp:
        root = Path(temp)
        clone_inputs(root)
        try:
            B.build_release(root, root, interrupt_at("after_all_handoffs_before_index"))
        except KeyboardInterrupt:
            pass
        else:
            raise AssertionError("ten-handoff interrupt did not fire")
        assert len(visible(root)) == 10 and not (root / B.INDEX).exists()
        expect_recovery_gate(root)
        B.recover_finish(root, root)
        B.verify_release(root, root)
        assert len(visible(root)) == 11 and not B.transaction_artifacts(root)
        return {"journal_blocked": True, "pre_recovery_index_visible": False, "finish_committed": True}


def probe_index_visible_interrupt_and_finish() -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="task8-probe-index-") as temp:
        root = Path(temp)
        clone_inputs(root)
        try:
            B.build_release(root, root, interrupt_at("after_index_visible"))
        except KeyboardInterrupt:
            pass
        else:
            raise AssertionError("index-visible interrupt did not fire")
        before = {path: B.identity((root / path).lstat()) for path in output_paths()}
        assert len(visible(root)) == 11 and (root / B.JOURNAL).exists()
        expect_recovery_gate(root)
        B.recover_finish(root, root)
        after = {path: B.identity((root / path).lstat()) for path in output_paths()}
        B.verify_release(root, root)
        assert before == after and not B.transaction_artifacts(root)
        return {"journal_blocked_with_index": True, "finish_rewrote_outputs": False, "committed": True}


def probe_input_toctou() -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="task8-probe-toctou-") as temp:
        root = Path(temp)
        clone_inputs(root)
        fact_card = root / B.WORK / B.IDS[0] / "research/fact-card.md"

        def mutate() -> None:
            fact_card.write_bytes(fact_card.read_bytes() + b"\nchanged-during-publish")

        try:
            B.build_release(root, root, interrupt_at("after_all_handoffs_before_index", mutate))
        except KeyboardInterrupt:
            pass
        else:
            raise AssertionError("TOCTOU interrupt did not fire")
        assert len(visible(root)) == 10 and not (root / B.INDEX).exists()
        expect_recovery_gate(root)
        try:
            B.recover_finish(root, root)
        except B.RecoveryRequired:
            pass
        else:
            raise AssertionError("finish accepted changed inputs")
        rollback = B.recover_rollback(root, root)
        assert rollback["removed_owned_files"] == 10
        assert not visible(root) and not B.transaction_artifacts(root)
        return {"finish_rejected_changed_input": True, "rollback_removed": 10, "index_visible": False}


def probe_index_visible_changed_input_rollback() -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="task8-probe-index-change-") as temp:
        root = Path(temp)
        clone_inputs(root)
        fact_card = root / B.WORK / B.IDS[0] / "research/fact-card.md"

        def mutate() -> None:
            fact_card.write_bytes(fact_card.read_bytes() + b"\nchanged-after-index")

        try:
            B.build_release(root, root, interrupt_at("after_index_visible", mutate))
        except KeyboardInterrupt:
            pass
        else:
            raise AssertionError("index/change interrupt did not fire")
        assert len(visible(root)) == 11 and (root / B.JOURNAL).exists()
        expect_recovery_gate(root)
        try:
            B.recover_finish(root, root)
        except B.RecoveryRequired:
            pass
        else:
            raise AssertionError("finish accepted changed inputs after index")
        rollback = B.recover_rollback(root, root)
        assert rollback["removed_owned_files"] == 11
        assert not visible(root) and not B.transaction_artifacts(root)
        return {"index_was_gated": True, "finish_rejected_changed_input": True, "rollback_removed": 11}


def probe_journal_and_lock_gate_matrix() -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="task8-probe-gates-") as temp:
        root = Path(temp)
        clone_inputs(root)
        B.build_release(root, root)

        snapshot = B.capture(root)
        outputs, _, _ = B.expected(snapshot)
        _, _, initial = B.preflight_targets(root, outputs)
        journal = B.new_journal(snapshot, outputs, initial)
        B.atomic_create_journal(root, journal)
        journal_blocked = assert_all_consumer_gates(root)
        journal_inspection = B.inspect_transaction(root)
        assert journal_inspection["journal_valid"] is True
        assert journal_inspection["transaction_id"] == journal["transaction_id"]
        B.recover_finish(root, root)
        B.verify_release(root, root)

        lock = root / B.TRANSACTION_LOCK
        lock.parent.mkdir(parents=True, exist_ok=True)
        lock.write_bytes(b"unknown-owner")
        lock_blocked = assert_all_consumer_gates(root)
        lock_inspection = B.inspect_transaction(root)
        assert lock_inspection["status"] == "recovery_required"
        try:
            B.recover_finish(root, root)
        except B.RecoveryRequired:
            pass
        else:
            raise AssertionError("explicit recovery auto-deleted or bypassed unknown lock")
        assert lock.read_bytes() == b"unknown-owner"
        lock.unlink()
        B.verify_release(root, root)
        return {
            "journal_gate_entries_blocked": journal_blocked,
            "lock_gate_entries_blocked": lock_blocked,
            "inspection_available": True,
            "unknown_lock_preserved": True,
        }


def probe_pending_external_same_inode_not_deleted() -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="task8-probe-pending-owner-") as temp:
        root = Path(temp)
        clone_inputs(root)
        external_created = False

        def hook(point: str, context: dict[str, Any]) -> None:
            nonlocal external_created
            if point == "before_link" and context["sequence"] == 1:
                stages = list(root.glob(".task8-step1-stage-*"))
                assert len(stages) == 1
                relative = Path(context["path"])
                source = stages[0] / relative
                target = root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                B.os.link(source, target)
                external_created = True

        try:
            B.build_release(root, root, hook)
        except B.RecoveryRequired:
            pass
        else:
            raise AssertionError("external same-inode race did not fail closed")
        target = root / output_paths()[0]
        assert external_created and target.is_file() and (root / B.JOURNAL).is_file()
        try:
            B.recover_rollback(root, root)
        except B.RecoveryRequired:
            pass
        else:
            raise AssertionError("rollback deleted or accepted ambiguous pending target")
        assert target.is_file() and (root / B.JOURNAL).is_file()
        B.recover_finish(root, root)
        B.verify_release(root, root)
        return {"external_target_survived_rollback": True, "journal_retained": True, "explicit_finish_adopted": True}


def probe_created_identity_replacement_rejected() -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="task8-probe-created-identity-") as temp:
        root = Path(temp)
        clone_inputs(root)
        try:
            B.build_release(root, root, interrupt_at("after_first_handoff"))
        except KeyboardInterrupt:
            pass
        else:
            raise AssertionError("identity probe interrupt did not fire")
        target = root / output_paths()[0]
        before = B.file_ownership(target)
        data = target.read_bytes()
        target.unlink()
        target.write_bytes(data)
        after = B.file_ownership(target)
        assert before != after
        for recover in (B.recover_finish, B.recover_rollback):
            try:
                recover(root, root)
            except B.RecoveryRequired:
                pass
            else:
                raise AssertionError("recovery accepted a same-bytes replacement identity")
        assert (root / B.JOURNAL).is_file() and target.read_bytes() == data
        return {"same_bytes_new_identity": True, "finish_rejected": True, "rollback_rejected": True, "journal_retained": True}


def probe_parent_reparse_swap_blocked() -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="task8-probe-parent-root-") as temp, tempfile.TemporaryDirectory(prefix="task8-probe-parent-outside-") as outside_temp:
        root, outside = Path(temp), Path(outside_temp)
        clone_inputs(root)
        relative = output_paths()[0]
        parent = (root / relative).parent
        backup = parent.with_name(parent.name + "-swap-backup")
        swap_blocked = False

        def hook(point: str, context: dict[str, Any]) -> None:
            nonlocal swap_blocked
            if point == "before_link" and context["sequence"] == 1:
                try:
                    parent.rename(backup)
                except OSError:
                    swap_blocked = True
                    return
                B.os.symlink(outside, parent, target_is_directory=True)

        B.build_release(root, root, hook)
        B.verify_release(root, root)
        assert swap_blocked and not backup.exists() and not (outside / relative.name).exists()
        return {"rename_denied_while_guarded": True, "outside_write": False, "package_valid": True}


def probe_noop_final_gate() -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="task8-probe-noop-gate-") as temp:
        root = Path(temp)
        clone_inputs(root)
        B.build_release(root, root)
        before = {path: B.file_ownership(root / path) for path in output_paths()}
        lock = root / B.TRANSACTION_LOCK

        def hook(point: str, context: dict[str, Any]) -> None:
            del context
            if point == "before_noop_final_gate":
                lock.parent.mkdir(parents=True, exist_ok=True)
                lock.write_bytes(b"appeared-before-return")

        try:
            B.build_release(root, root, hook)
        except B.RecoveryRequired:
            pass
        else:
            raise AssertionError("no-op build returned after a gate artifact appeared")
        assert lock.read_bytes() == b"appeared-before-return"
        after = {path: B.file_ownership(root / path) for path in output_paths()}
        assert before == after
        lock.unlink()
        B.verify_release(root, root)
        return {"return_gate_rejected": True, "unknown_lock_preserved": True, "outputs_unchanged": True}


def probe_move_before_created_journal_interrupt() -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="task8-probe-move-intent-") as temp:
        root = Path(temp)
        clone_inputs(root)
        try:
            B.build_release(root, root, interrupt_at("after_move_before_created_journal"))
        except KeyboardInterrupt:
            pass
        else:
            raise AssertionError("move/created journal interrupt did not fire")
        state = B.inspect_transaction(root)
        assert state["pending_create"] is not None and len(visible(root)) == 1
        try:
            B.recover_rollback(root, root)
        except B.RecoveryRequired:
            pass
        else:
            raise AssertionError("rollback deleted ambiguous intent target")
        assert len(visible(root)) == 1 and (root / B.JOURNAL).is_file()
        B.recover_finish(root, root)
        B.verify_release(root, root)
        return {"rollback_refused_ambiguous_intent": True, "explicit_finish_adopted": True, "committed": True}


def probe_cleanup_marker_interrupt() -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="task8-probe-cleanup-marker-") as temp:
        root = Path(temp)
        clone_inputs(root)
        try:
            B.build_release(root, root, interrupt_at("after_journal_cleanup_marker"))
        except KeyboardInterrupt:
            pass
        else:
            raise AssertionError("cleanup marker interrupt did not fire")
        before = {path: B.file_ownership(root / path) for path in output_paths()}
        state = B.inspect_transaction(root)
        assert state["journal_artifact"] == B.rel_text(B.JOURNAL_CLEANUP)
        assert len(visible(root)) == 11
        cleanup_blocked = assert_all_consumer_gates(root)
        B.recover_finish(root, root)
        after = {path: B.file_ownership(root / path) for path in output_paths()}
        B.verify_release(root, root)
        assert before == after and not B.transaction_artifacts(root)
        return {"cleanup_marker_gate_entries_blocked": cleanup_blocked, "finish_rewrote_outputs": False, "committed": True}


def probe_write_through_move_path() -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="task8-probe-write-through-") as temp:
        root = Path(temp)
        clone_inputs(root)
        moves: list[tuple[str, str, bool]] = []
        flushes = 0
        original_move = B.durable_move
        original_flush = B.flush_directory_guards

        def move(source: Path, target: Path, *, replace: bool) -> None:
            moves.append((str(source), str(target), replace))
            original_move(source, target, replace=replace)

        def flush(guards: list[int]) -> None:
            nonlocal flushes
            flushes += 1
            original_flush(guards)

        B.durable_move = move
        B.flush_directory_guards = flush
        try:
            B.build_release(root, root)
        finally:
            B.durable_move = original_move
            B.flush_directory_guards = original_flush
        formal = [(Path(target), replace) for _, target, replace in moves if Path(target).is_relative_to(root) and Path(target).relative_to(root) in output_paths()]
        assert len(formal) == 11 and all(replace is False for _, replace in formal)
        assert formal[-1][0].relative_to(root) == B.INDEX
        B.verify_release(root, root)
        return {"formal_write_through_moves": 11, "index_moved_last": True, "replace_forbidden": True, "directory_flush_calls": flushes}


def probe_strict_journal_schema() -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="task8-probe-journal-schema-") as temp:
        root = Path(temp)
        clone_inputs(root)
        try:
            B.build_release(root, root, interrupt_at("after_first_handoff"))
        except KeyboardInterrupt:
            pass
        else:
            raise AssertionError("journal schema interrupt did not fire")
        journal_path = root / B.JOURNAL
        envelope = json.loads(journal_path.read_text(encoding="utf-8"))
        envelope["journal_payload"]["unexpected_but_rehashed"] = True
        canonical = B.canonical_json(envelope["journal_payload"])
        envelope["journal_payload_sha256"] = B.sha256(canonical.encode("utf-8"))
        tampered = B.canonical_json(envelope).encode("utf-8")
        journal_path.write_bytes(tampered)
        state = B.inspect_transaction(root)
        assert state["journal_valid"] is False
        expect_recovery_gate(root)
        for recover in (B.recover_finish, B.recover_rollback):
            try:
                recover(root, root)
            except (B.RecoveryRequired, ValueError):
                pass
            else:
                raise AssertionError("strict journal decoder accepted an unknown rehashed field")
        assert journal_path.read_bytes() == tampered
        return {"hash_recomputed": True, "unknown_field_rejected": True, "journal_preserved": True}


def probe_successor_journal_recovery() -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="task8-probe-journal-successor-") as temp:
        root = Path(temp)
        clone_inputs(root)
        try:
            B.build_release(root, root, interrupt_at("after_first_handoff"))
        except KeyboardInterrupt:
            pass
        else:
            raise AssertionError("successor journal interrupt did not fire")
        current = B.read_journal(root)
        candidate = json.loads(json.dumps(current))
        candidate["generation"] = current["generation"] + 1
        candidate["previous_payload_sha256"] = B.payload_digest(current)
        B.write_journal_candidate(root, candidate)
        assert set(B.transaction_artifacts(root)) == {B.JOURNAL, B.JOURNAL_NEXT}
        next_blocked = assert_all_consumer_gates(root)
        B.recover_finish(root, root)
        B.verify_release(root, root)
        assert not B.transaction_artifacts(root)
        return {"exact_successor_promoted": True, "next_gate_entries_blocked": next_blocked, "committed": True}


def probe_journal_candidate_parent_swap_blocked() -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="task8-probe-journal-parent-") as temp, tempfile.TemporaryDirectory(prefix="task8-probe-journal-outside-") as outside_temp:
        root, outside = Path(temp), Path(outside_temp)
        clone_inputs(root)
        qa_parent = root / B.QA_ROOT
        backup = qa_parent.with_name(qa_parent.name + "-swap-backup")
        attempted = False
        swap_blocked = False

        def hook(point: str, context: dict[str, Any]) -> None:
            nonlocal attempted, swap_blocked
            del context
            if point == "before_journal_candidate_open" and not attempted:
                attempted = True
                try:
                    qa_parent.rename(backup)
                except OSError:
                    swap_blocked = True
                    return
                B.os.symlink(outside, qa_parent, target_is_directory=True)

        B.build_release(root, root, hook)
        B.verify_release(root, root)
        outside_files = [path for path in outside.rglob("*") if path.is_file()]
        assert attempted and swap_blocked and not backup.exists() and not outside_files
        return {"rename_denied_at_candidate_open": True, "outside_write": False, "package_valid": True}


def probe_stage_parent_swap_blocked() -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="task8-probe-stage-parent-") as temp, tempfile.TemporaryDirectory(prefix="task8-probe-stage-outside-") as outside_temp:
        root, outside = Path(temp), Path(outside_temp)
        clone_inputs(root)
        backup = root / ".task8-step1-stage-swap-backup"
        attempted = False
        swap_blocked = False

        def hook(point: str, context: dict[str, Any]) -> None:
            nonlocal attempted, swap_blocked
            if point == "before_stage_file_open" and context["sequence"] == 1 and not attempted:
                attempted = True
                stages = [path for path in root.iterdir() if path.name.startswith(".task8-step1-stage-") and path.is_dir()]
                if len(stages) != 1:
                    raise AssertionError(f"expected one controlled staging root, found {len(stages)}")
                stage = stages[0]
                try:
                    stage.rename(backup)
                except OSError:
                    swap_blocked = True
                    return
                B.os.symlink(outside, stage, target_is_directory=True)

        B.build_release(root, root, hook)
        B.verify_release(root, root)
        outside_files = [path for path in outside.rglob("*") if path.is_file()]
        assert attempted and swap_blocked and not backup.exists() and not outside_files
        return {"rename_denied_at_stage_open": True, "outside_write": False, "package_valid": True}


def probe_transaction_scope_journal_parent_guard() -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="task8-probe-journal-scope-") as temp:
        root = Path(temp)
        clone_inputs(root)
        qa_parent = root / B.QA_ROOT
        attempted = {"candidate_publish": False, "after_index_visible": False}
        blocked = {"candidate_publish": False, "after_index_visible": False}

        def hook(point: str, context: dict[str, Any]) -> None:
            key: str | None = None
            if point == "before_journal_candidate_publish" and context["phase"] == "index_visible":
                key = "candidate_publish"
            elif point == "after_index_visible":
                key = "after_index_visible"
            if key is None or attempted[key]:
                return
            attempted[key] = True
            backup = qa_parent.with_name(qa_parent.name + f"-{key}-backup")
            try:
                qa_parent.rename(backup)
            except OSError:
                blocked[key] = True
                return
            qa_parent.mkdir()

        B.build_release(root, root, hook)
        B.verify_release(root, root)
        backups = list(qa_parent.parent.glob(qa_parent.name + "-*-backup"))
        assert all(attempted.values()) and all(blocked.values()) and not backups
        assert len(visible(root)) == 11 and not B.transaction_artifacts(root)
        return {"candidate_to_publish_rename_denied": True, "journal_lifetime_rename_denied": True, "package_valid": True}


def probe_identity_bound_rollback_delete() -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="task8-probe-bound-rollback-") as temp:
        root = Path(temp)
        clone_inputs(root)
        try:
            B.build_release(root, root, interrupt_at("after_first_handoff"))
        except KeyboardInterrupt:
            pass
        else:
            raise AssertionError("rollback identity probe interrupt did not fire")
        target = root / output_paths()[0]
        attempted = False
        swap_denied = False

        def hook(point: str, context: dict[str, Any]) -> None:
            nonlocal attempted, swap_denied
            if point == "after_owned_validation_before_delete" and not attempted:
                attempted = True
                assert Path(context["path"]) == output_paths()[0]
                try:
                    target.unlink()
                except OSError:
                    swap_denied = True
                    return
                target.write_bytes(b"external-replacement-must-survive")

        recovery = B.recover_rollback(root, root, hook)
        assert attempted and swap_denied and recovery["removed_owned_files"] == 1
        assert not target.exists() and not B.transaction_artifacts(root)
        return {"leaf_swap_denied_while_bound": True, "removed_owned_files": 1, "journal_absent": True}


def probe_identity_bound_journal_cleanup() -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="task8-probe-bound-journal-") as temp:
        root = Path(temp)
        clone_inputs(root)
        journal = root / B.JOURNAL
        attempted = False
        swap_denied = False

        def hook(point: str, context: dict[str, Any]) -> None:
            nonlocal attempted, swap_denied
            del context
            if point == "after_journal_identity_validation_before_cleanup_move" and not attempted:
                attempted = True
                try:
                    journal.unlink()
                except OSError:
                    swap_denied = True
                    return
                journal.write_bytes(b"external-journal-replacement")

        B.build_release(root, root, hook)
        B.verify_release(root, root)
        assert attempted and swap_denied and not B.transaction_artifacts(root)
        return {"journal_swap_denied_while_bound": True, "cleanup_identity_bound": True, "package_valid": True}


def probe_published_leaf_identity_guard() -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="task8-probe-bound-publish-") as temp:
        root = Path(temp)
        clone_inputs(root)
        target = root / output_paths()[0]
        attempted = False
        swap_denied = False

        def hook(point: str, context: dict[str, Any]) -> None:
            nonlocal attempted, swap_denied
            if point == "after_move_before_created_journal" and context["sequence"] == 1 and not attempted:
                attempted = True
                try:
                    target.unlink()
                except OSError:
                    swap_denied = True
                    return
                target.write_bytes(b"external-publish-replacement")

        B.build_release(root, root, hook)
        B.verify_release(root, root)
        assert attempted and swap_denied and len(visible(root)) == 11 and not B.transaction_artifacts(root)
        return {"published_leaf_swap_denied": True, "created_identity_persisted_while_bound": True, "package_valid": True}


def probe_identity_bound_journal_generation_replacement() -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="task8-probe-bound-generation-") as temp:
        root = Path(temp)
        clone_inputs(root)
        journal = root / B.JOURNAL
        attempted = False
        swap_denied = False

        def hook(point: str, context: dict[str, Any]) -> None:
            nonlocal attempted, swap_denied
            if (
                point == "before_journal_candidate_publish"
                and context["phase"] == "index_visible"
                and not attempted
            ):
                attempted = True
                try:
                    journal.unlink()
                except OSError:
                    swap_denied = True
                    return
                journal.write_bytes(b"external journal evidence must survive")

        B.build_release(root, root, hook)
        B.verify_release(root, root)
        assert attempted and swap_denied
        assert len(visible(root)) == 11 and not B.transaction_artifacts(root)
        return {
            "replacement_attempted_at_index_visible_generation": True,
            "held_current_journal_denied_swap": True,
            "unknown_evidence_overwritten": False,
            "package_valid": True,
        }


def probe_predecessor_next_interrupt_and_recovery() -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="task8-probe-predecessor-next-") as temp:
        root = Path(temp)
        clone_inputs(root)
        try:
            B.build_release(
                root,
                root,
                interrupt_at("after_journal_predecessor_visible_before_candidate_publish"),
            )
        except KeyboardInterrupt:
            pass
        else:
            raise AssertionError("predecessor + next interruption did not fire")
        assert set(B.transaction_artifacts(root)) == {B.JOURNAL_PREVIOUS, B.JOURNAL_NEXT}
        assert not (root / B.JOURNAL).exists() and not visible(root)
        blocked = assert_all_consumer_gates(root)
        B.recover_finish(root, root)
        B.verify_release(root, root)
        assert len(visible(root)) == 11 and not B.transaction_artifacts(root)
        return {
            "predecessor_next_state_durable": True,
            "gate_entries_blocked": blocked,
            "finish_recovered": True,
        }


def probe_predecessor_journal_interrupt_and_recovery() -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="task8-probe-predecessor-journal-") as temp:
        root = Path(temp)
        clone_inputs(root)
        try:
            B.build_release(
                root,
                root,
                interrupt_at("after_journal_successor_visible_before_predecessor_cleanup"),
            )
        except KeyboardInterrupt:
            pass
        else:
            raise AssertionError("predecessor + journal interruption did not fire")
        assert set(B.transaction_artifacts(root)) == {B.JOURNAL_PREVIOUS, B.JOURNAL}
        assert not (root / B.JOURNAL_NEXT).exists() and not visible(root)
        blocked = assert_all_consumer_gates(root)
        B.recover_finish(root, root)
        B.verify_release(root, root)
        assert len(visible(root)) == 11 and not B.transaction_artifacts(root)
        return {
            "predecessor_journal_state_durable": True,
            "gate_entries_blocked": blocked,
            "finish_recovered": True,
        }


def main() -> int:
    results = {
        "fresh_and_same_bytes": probe_fresh_and_same_bytes(),
        "different_bytes": probe_different_bytes(),
        "ordinary_oserror": probe_ordinary_oserror(),
        "atomic_journal_create_keyboard_interrupt": probe_atomic_journal_create_interrupt(),
        "first_handoff_keyboard_interrupt": probe_first_handoff_interrupt_and_rollback(),
        "ten_handoffs_before_index_keyboard_interrupt": probe_ten_handoffs_interrupt_and_finish(),
        "index_visible_keyboard_interrupt": probe_index_visible_interrupt_and_finish(),
        "input_toctou": probe_input_toctou(),
        "index_visible_changed_input_recovery": probe_index_visible_changed_input_rollback(),
        "journal_and_lock_gate_matrix": probe_journal_and_lock_gate_matrix(),
        "pending_external_same_inode": probe_pending_external_same_inode_not_deleted(),
        "created_identity_replacement": probe_created_identity_replacement_rejected(),
        "parent_reparse_swap": probe_parent_reparse_swap_blocked(),
        "noop_final_gate": probe_noop_final_gate(),
        "move_before_created_journal": probe_move_before_created_journal_interrupt(),
        "cleanup_marker_interrupt": probe_cleanup_marker_interrupt(),
        "write_through_move_path": probe_write_through_move_path(),
        "strict_journal_schema": probe_strict_journal_schema(),
        "successor_journal_recovery": probe_successor_journal_recovery(),
        "journal_candidate_parent_swap": probe_journal_candidate_parent_swap_blocked(),
        "stage_parent_swap": probe_stage_parent_swap_blocked(),
        "transaction_scope_journal_parent_guard": probe_transaction_scope_journal_parent_guard(),
        "identity_bound_rollback_delete": probe_identity_bound_rollback_delete(),
        "identity_bound_journal_cleanup": probe_identity_bound_journal_cleanup(),
        "published_leaf_identity_guard": probe_published_leaf_identity_guard(),
        "identity_bound_journal_generation_replacement": probe_identity_bound_journal_generation_replacement(),
        "predecessor_next_interrupt_recovery": probe_predecessor_next_interrupt_and_recovery(),
        "predecessor_journal_interrupt_recovery": probe_predecessor_journal_interrupt_and_recovery(),
    }
    print(json.dumps({"status": "PASS", "probe_categories": len(results), "results": results}, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
