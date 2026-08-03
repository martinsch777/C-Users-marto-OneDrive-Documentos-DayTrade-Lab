from __future__ import annotations

import ast
from contextlib import redirect_stderr, redirect_stdout
from datetime import date
from io import StringIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import pandas as pd

from src.research.hyp_vwap_dev_01 import (
    ACTIVE_AMENDMENT_FREEZE_COMMIT,
    ConcentrationResult,
    EXPECTED_CANONICAL_HASH,
    GateResult,
    LeaveOneOutResult,
    SUBSTANTIVE_CRITERION_IDS,
)
import src.research.hyp_vwap_dev_01_discovery as runner
from src.research.hyp_vwap_dev_01_discovery import (
    CONFIG_PATH,
    DiscoveryRequest,
    ExecutionProgress,
    RuntimeState,
    StrictSafeLoader,
    build_parser,
    crop_discovery_period,
    load_frozen_config,
    main,
    validate_discovery_preflight,
    validate_implementation,
)
from tests.test_hyp_vwap_dev_01 import CORE_TEST_ID_COVERAGE


RUNNER_ID_COUNTS = {"RUN": 15, "SEC": 5}
RUNNER_TEST_ID_COVERAGE = {
    "RUN-01": "test_contract_run_validate_opens_nothing_and_writes_nothing",
    "RUN-02": "test_contract_run_preflight_rejects_before_manifest_access",
    "RUN-03": "test_contract_run_preflight_clean_head_and_freeze",
    "RUN-04": "test_contract_run_dirty_tree_rejected",
    "RUN-05": "test_contract_run_discovery_crop",
    "RUN-06": "test_contract_run_discovery_crop",
    "RUN-07": "test_contract_run_progress_has_no_duplicate_stage",
    "RUN-08": "test_contract_run_failure_preserves_temp_and_final_absent",
    "RUN-09": "test_contract_run_results_written_not_premature",
    "RUN-10": "test_contract_run_winerror_retry",
    "RUN-11": "test_contract_run_atomic_failure_propagates",
    "RUN-12": "test_contract_run_failure_preserves_temp_and_final_absent",
    "RUN-13": "test_contract_run_inventory_and_checksums",
    "RUN-14": "test_contract_run_manifest_coherence",
    "RUN-15": "test_contract_run_fully_mocked_success",
    "SEC-01": "test_contract_sec_no_broker_network_or_order_surface",
    "SEC-02": "test_contract_sec_no_broker_network_or_order_surface",
    "SEC-03": "test_contract_sec_no_broker_network_or_order_surface",
    "SEC-04": "test_contract_sec_no_broker_network_or_order_surface",
    "SEC-05": "test_contract_run_parser_has_only_governed_modes",
}
ALL_TEST_ID_COVERAGE = {**CORE_TEST_ID_COVERAGE, **RUNNER_TEST_ID_COVERAGE}


class CoverageContractTests(unittest.TestCase):
    def test_202_ids_are_complete_unique_and_traceable(self) -> None:
        self.assertEqual(len(CORE_TEST_ID_COVERAGE), 182)
        self.assertEqual(len(RUNNER_TEST_ID_COVERAGE), 20)
        self.assertEqual(len(ALL_TEST_ID_COVERAGE), 202)
        self.assertEqual(len(set(ALL_TEST_ID_COVERAGE)), 202)
        contract = Path("docs/HYP_VWAP_DEV_01_IMPLEMENTATION_TEST_CONTRACT.md").read_text(encoding="utf-8")
        represented = {
            line.split("|")[1].strip()
            for line in contract.splitlines()
            if line.startswith("|") and len(line.split("|")) > 2
            and line.split("|")[1].strip() in ALL_TEST_ID_COVERAGE
        }
        self.assertEqual(represented, set(ALL_TEST_ID_COVERAGE))
        method_names = {
            name
            for case in (
                CoverageContractTests, ValidationModeTests, PreflightTests,
                AtomicProgressTests, SecurityTests,
            )
            for name in unittest.defaultTestLoader.getTestCaseNames(case)
        }
        self.assertTrue(set(RUNNER_TEST_ID_COVERAGE.values()).issubset(method_names))


class ValidationModeTests(unittest.TestCase):
    def test_contract_run_validate_opens_nothing_and_writes_nothing(self) -> None:
        with patch(
            "src.research.hyp_vwap_dev_01_discovery._load_discovery_inputs",
            side_effect=AssertionError("dataset path reached"),
        ), patch(
            "src.research.hyp_vwap_dev_01_discovery.require_approved_dataset_manifest_file",
            side_effect=AssertionError("manifest path reached"),
        ):
            result = validate_implementation()
        self.assertTrue(result["implementation_valid"])
        self.assertEqual(result["canonical_payload_sha256"], EXPECTED_CANONICAL_HASH)
        self.assertEqual(result["criterion_count"], 26)
        self.assertEqual(result["substantive_criterion_count"], 25)
        for key in (
            "datasets_opened", "manifests_opened", "discovery_executed",
            "artifacts_created", "strategy_created", "orders_created",
            "position_sizing_used", "broker_connected",
        ):
            self.assertFalse(result[key], key)

    def test_contract_run_cli_validation_json(self) -> None:
        output = StringIO()
        with redirect_stdout(output):
            self.assertEqual(main(["--mode", "validate_implementation"]), 0)
        payload = json.loads(output.getvalue())
        self.assertEqual(payload["mode"], "validate_implementation")
        self.assertFalse(payload["discovery_executed"])

    def test_contract_run_parser_has_only_governed_modes(self) -> None:
        parser = build_parser()
        self.assertEqual(parser.parse_args(["--mode", "validate_implementation"]).mode, "validate_implementation")
        with redirect_stderr(StringIO()), self.assertRaises(SystemExit):
            parser.parse_args(["--mode", "prepare"])

    def test_contract_run_strict_yaml_duplicate_rejected(self) -> None:
        with self.assertRaises(ValueError):
            import yaml

            yaml.load("a: 1\na: 2\n", Loader=StrictSafeLoader)
        self.assertEqual(load_frozen_config(CONFIG_PATH)["canonical_payload_sha256"], EXPECTED_CANONICAL_HASH)


class PreflightTests(unittest.TestCase):
    def _request(self) -> DiscoveryRequest:
        return DiscoveryRequest(
            mode="run_discovery",
            expected_amendment_freeze_commit=ACTIVE_AMENDMENT_FREEZE_COMMIT,
            expected_implementation_freeze_commit="a" * 40,
            expected_canonical_hash=EXPECTED_CANONICAL_HASH,
        )

    def test_contract_run_preflight_rejects_before_manifest_access(self) -> None:
        bad_requests = [
            DiscoveryRequest(mode="run_discovery"),
            DiscoveryRequest(
                mode="run_discovery",
                expected_amendment_freeze_commit="0" * 40,
                expected_implementation_freeze_commit="a" * 40,
                expected_canonical_hash=EXPECTED_CANONICAL_HASH,
            ),
        ]
        with patch(
            "src.research.hyp_vwap_dev_01_discovery.require_approved_dataset_manifest_file",
            side_effect=AssertionError("manifest opened"),
        ):
            for request in bad_requests:
                with self.subTest(request=request), self.assertRaises(PermissionError):
                    validate_discovery_preflight(request)

    def test_contract_run_preflight_clean_head_and_freeze(self) -> None:
        runtime = RuntimeState("a" * 40, True, "", True, True)
        with patch(
            "src.research.hyp_vwap_dev_01_discovery.collect_runtime_state",
            return_value=runtime,
        ), patch(
            "src.research.hyp_vwap_dev_01_discovery.DEFAULT_OUTPUT_DIR",
            Path("this/path/must/not/exist"),
        ):
            result = validate_discovery_preflight(self._request())
        self.assertTrue(result["preflight_passed"])

    def test_contract_run_dirty_tree_rejected(self) -> None:
        runtime = RuntimeState("a" * 40, False, " M file", True, True)
        with patch(
            "src.research.hyp_vwap_dev_01_discovery.collect_runtime_state",
            return_value=runtime,
        ), self.assertRaises(PermissionError):
            validate_discovery_preflight(self._request())

    def test_contract_run_discovery_crop(self) -> None:
        frame = pd.DataFrame({
            "timestamp": pd.to_datetime([
                "2021-12-31 15:00Z", "2022-01-03 15:00Z", "2024-12-31 15:00Z",
                "2025-01-02 15:00Z", "2026-01-02 15:00Z",
            ]),
            "poison": [True, False, False, True, True],
        })
        cropped = crop_discovery_period(frame)
        years = set(pd.to_datetime(cropped["timestamp"], utc=True).dt.year)
        self.assertEqual(years, {2022, 2024})
        self.assertFalse(cropped["poison"].any())


class AtomicProgressTests(unittest.TestCase):
    def _build_temp_inventory(self, directory: Path) -> ExecutionProgress:
        directory.mkdir(parents=True)
        progress = ExecutionProgress(path=directory / "execution_progress.json")
        progress.persist()
        for name in runner.REQUIRED_OUTPUT_FILES:
            path = directory / name
            if name in {"execution_progress.json", "checksums.json"}:
                continue
            if name == "run_manifest.json":
                path.write_text(json.dumps({"results_written": False}) + "\n", encoding="utf-8")
            else:
                path.write_text("{}\n" if name.endswith(".json") else "x\n", encoding="utf-8")
        checksums = {
            path.name: runner._shared_sha256_file(path)
            for path in directory.iterdir()
            if path.is_file() and path.name not in {"checksums.json", "execution_progress.json"}
        }
        runner._shared_write_json_atomic(directory / "checksums.json", checksums)
        return progress

    def test_contract_run_progress_has_no_duplicate_stage(self) -> None:
        progress = ExecutionProgress()
        progress.record("preflight")
        with self.assertRaises(RuntimeError):
            progress.record("preflight")
        self.assertEqual([item["stage"] for item in progress.stages], ["preflight"])

    def test_contract_run_results_written_not_premature(self) -> None:
        progress = ExecutionProgress()
        progress.record("outputs_verified")
        self.assertFalse(progress.summary()["results_written"])
        progress.results_written = True
        progress.record("final_promoted")
        self.assertTrue(progress.summary()["results_written"])

    def test_contract_run_atomic_progress_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "execution_progress.json"
            progress = ExecutionProgress(path=path)
            progress.record("preflight", rows=0)
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(payload["stages"][0]["stage"], "preflight")
            self.assertFalse(payload["results_written"])
            self.assertFalse(any(item.name.startswith(".execution_progress.json.tmp-") for item in path.parent.iterdir()))

    def test_contract_run_atomic_failure_propagates(self) -> None:
        progress = ExecutionProgress(path=Path("unused.json"))
        with patch(
            "src.research.hyp_vwap_dev_01_discovery._shared_write_json_atomic",
            side_effect=PermissionError(5, "denied"),
        ), self.assertRaises(PermissionError):
            progress.record("preflight")
        self.assertFalse(progress.results_written)

    def test_contract_run_winerror_retry(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "value.json"
            attempts: list[Path] = []

            def replace(source: str | Path, target: str | Path) -> None:
                source_path = Path(source)
                attempts.append(source_path)
                self.assertTrue(source_path.exists())
                if len(attempts) < 3:
                    error = PermissionError(13, "locked")
                    error.winerror = 5
                    raise error
                Path(target).write_bytes(source_path.read_bytes())
                source_path.unlink()

            with patch("src.research.hyp_drive_pb_01_discovery.os.replace", side_effect=replace), patch(
                "src.research.hyp_drive_pb_01_discovery.time.sleep"
            ) as sleeper:
                runner._shared_write_json_atomic(destination, {"ok": True})
            self.assertEqual(len(attempts), 3)
            self.assertEqual(sleeper.call_count, 2)
            self.assertTrue(destination.exists())

    def test_contract_run_failure_preserves_temp_and_final_absent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            temp_dir = root / ".final.tmp-synthetic"
            final_dir = root / "final"
            self._build_temp_inventory(temp_dir)
            with patch.object(runner, "_shared_atomic_rename", side_effect=PermissionError("locked")), self.assertRaises(PermissionError):
                runner._shared_atomic_rename(temp_dir, final_dir)
            self.assertTrue(temp_dir.exists())
            self.assertFalse(final_dir.exists())

    def test_contract_run_inventory_and_checksums(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary) / "temp"
            progress = self._build_temp_inventory(directory)
            runner._finalize_temp_inventory(directory, progress)
            self.assertEqual({path.name for path in directory.iterdir()}, set(runner.REQUIRED_OUTPUT_FILES))
            checksums = json.loads((directory / "checksums.json").read_text(encoding="utf-8"))
            for name, digest in checksums.items():
                self.assertEqual(runner._shared_sha256_file(directory / name), digest)

    def test_contract_run_manifest_coherence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary) / "temp"
            progress = self._build_temp_inventory(directory)
            runner._finalize_temp_inventory(directory, progress)
            manifest = json.loads((directory / "run_manifest.json").read_text(encoding="utf-8"))
            self.assertTrue(manifest["results_written"])
            self.assertIn("completed_at", manifest)

    def test_contract_run_fully_mocked_success(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            final_dir = Path(temporary) / "final"
            events = pd.DataFrame([{"symbol": "QQQ", "session_date": "2024-01-03"}])
            exclusions = pd.DataFrame([{"status": "none"}])
            controlled = pd.DataFrame([{
                "symbol": "QQQ", "session_date": "2024-01-03",
                "executable_timestamp": "2024-01-03T15:05:00Z", "horizon": "30min",
                "unconditional_return": 0.0, "unconditional_sample_count": 2,
                "path_complete": True,
            }])
            statuses = {criterion_id: "passed" for criterion_id in SUBSTANTIVE_CRITERION_IDS}
            concentration = ConcentrationResult(0.4, True, "PASS")
            loo = LeaveOneOutResult(
                date.fromisoformat("2024-01-02"), concentration, 0.001, 2,
                {2022: 40, 2023: 40, 2024: 40}, True,
            )
            gate = GateResult({**statuses, "PRO-01": "passed"}, True, "discovery_passed", True)
            request = DiscoveryRequest(mode="run_discovery")
            with patch.object(runner, "DEFAULT_OUTPUT_DIR", final_dir), patch.object(
                runner, "validate_discovery_preflight", return_value={"config": {"discovery_gate": {"criteria": []}}}
            ), patch.object(runner, "_load_discovery_inputs", return_value=(pd.DataFrame([{"x": 1}]), {"QQQ": {}})), patch.object(
                runner, "resample_complete_rth_1m_to_5m", return_value=pd.DataFrame([{"x": 1}])
            ), patch.object(runner, "attach_causal_session_vwap", return_value=pd.DataFrame([{"x": 1}])), patch.object(
                runner, "_detect_events", return_value=(events, exclusions)
            ), patch.object(runner, "compute_path_metrics", return_value=controlled), patch.object(
                runner, "build_unconditional_candidates", return_value=controlled
            ), patch.object(runner, "build_exact_time_control", return_value=controlled), patch.object(
                runner, "clustered_percentile_bootstrap", return_value={"gross_return": (0.1, 0.2)}
            ), patch.object(runner, "annual_concentration", return_value=concentration), patch.object(
                runner, "leave_one_largest_session_out", return_value=loo
            ), patch.object(runner, "_gate_metric_mapping", return_value={}), patch.object(
                runner, "derive_substantive_criteria", return_value=statuses
            ), patch.object(runner, "classify_gate", return_value=gate):
                result = runner.run_discovery(request)
            self.assertTrue(result["results_written"])
            self.assertTrue(final_dir.is_dir())
            self.assertEqual({path.name for path in final_dir.iterdir()}, set(runner.REQUIRED_OUTPUT_FILES))
            self.assertFalse(any(path.name.startswith(".final.tmp-") for path in final_dir.parent.iterdir()))


class SecurityTests(unittest.TestCase):
    def test_contract_sec_no_broker_network_or_order_surface(self) -> None:
        paths = [
            Path("src/research/hyp_vwap_dev_01.py"),
            Path("src/research/hyp_vwap_dev_01_discovery.py"),
        ]
        forbidden_imports = {"requests", "httpx", "socket", "alpaca", "ib_insync", "ccxt"}
        for path in paths:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            imports = {
                alias.name.split(".")[0]
                for node in ast.walk(tree)
                if isinstance(node, (ast.Import, ast.ImportFrom))
                for alias in (node.names if isinstance(node, ast.Import) else [ast.alias(node.module or "")])
            }
            self.assertTrue(forbidden_imports.isdisjoint(imports), path)
        validation = validate_implementation()
        self.assertFalse(validation["strategy_created"])
        self.assertFalse(validation["orders_created"])
        self.assertFalse(validation["broker_connected"])


if __name__ == "__main__":
    unittest.main()
