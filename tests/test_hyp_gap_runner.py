import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from src.data import sha256_file
from src.research.hypotheses.hyp_gap import HypGapDetectionResult, HypGapDetectionSummary
from src.research.runners import HypGapRunRequest, run_hyp_gap_event_study
from tests.test_hyp_gap import CALENDAR, make_session, session_days, synthetic_frame


def write_csv(directory: Path, frame: pd.DataFrame, name: str = "QQQ_curated.csv") -> Path:
    path = directory / name
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False)
    return path


def manifest_payload(
    csv_path: Path,
    *,
    symbol: str = "QQQ",
    timeframe: str = "1min",
    sha256: str | None = None,
    curated_file: str | None = None,
    output_file: str | None = None,
    status: str = "approved_for_or_fvg_backtest",
    apt: bool = True,
    warnings: list[str] | None = None,
    excluded_sessions: list[dict] | None = None,
    safety: dict | None = None,
) -> dict:
    flags = {
        "broker_connected": False,
        "orders_sent": False,
        "live_trading_enabled": False,
        "paper_broker_enabled": False,
    }
    if safety:
        flags.update(safety)
    return {
        "symbol": symbol,
        "asset_class": "equity",
        "timeframe": timeframe,
        "provider": "synthetic",
        "feed": "synthetic",
        "adjustment": "raw",
        "source_timezone": "UTC",
        "rth_only": True,
        "start": "2024-07-01",
        "end": "2024-08-01",
        "rows": int(len(pd.read_csv(csv_path))),
        "first_timestamp": "synthetic",
        "last_timestamp": "synthetic",
        "input_file": str(csv_path),
        "output_file": str(csv_path) if output_file is None else output_file,
        "raw_input_file": None,
        "curated_file": str(csv_path) if curated_file is None else curated_file,
        "rows_input": None,
        "rows_output": None,
        "rows_removed": None,
        "sha256": sha256 or sha256_file(csv_path),
        "calendar_source": "builtin_us_equity_calendar_v1",
        "calendar_loaded": True,
        "calendar_holidays_loaded": 1,
        "calendar_early_closes_loaded": 1,
        "audit_apt_for_or_fvg_backtest": apt,
        "audit_critical_warnings": warnings or [],
        "audit_warnings": [],
        "total_excluded_sessions": len(excluded_sessions or []),
        "excluded_sessions": excluded_sessions or [],
        "dataset_status": status,
        "created_at": "2026-07-13T00:00:00+00:00",
        **flags,
        "project_safety_state": {
            "live_trading": False,
            "live_trading_enabled": False,
            "broker_connected": False,
            "orders_sent": False,
            "paper_broker_enabled": False,
        },
    }


def write_manifest(directory: Path, csv_path: Path, **kwargs) -> Path:
    path = directory / "QQQ_1min_synthetic_curated_manifest.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(manifest_payload(csv_path, **kwargs), indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return path


def request(csv_path: Path, manifest_path: Path, output: Path, **kwargs) -> HypGapRunRequest:
    return HypGapRunRequest(
        dataset_path=str(csv_path),
        manifest_path=str(manifest_path),
        symbol=kwargs.pop("symbol", "QQQ"),
        timeframe=kwargs.pop("timeframe", "1min"),
        requested_start=kwargs.pop("requested_start", "2024-08-01"),
        requested_end=kwargs.pop("requested_end", "2024-08-01"),
        preregistration_path=kwargs.pop(
            "preregistration_path",
            "configs/research/hypotheses/HYP-GAP.yaml",
        ),
        output_directory=str(output),
        run_id=kwargs.pop("run_id", None),
        research_phase=kwargs.pop("research_phase", "discovery"),
        variant_ids=kwargs.pop("variant_ids", None),
    )


class HypGapRunnerTests(unittest.TestCase):
    def setup_run(self, *, frame: pd.DataFrame | None = None, **manifest_kwargs):
        directory = Path(tempfile.mkdtemp())
        csv_path = write_csv(directory, frame if frame is not None else synthetic_frame())
        manifest_path = write_manifest(directory, csv_path, **manifest_kwargs)
        output = directory / "outputs"
        return directory, csv_path, manifest_path, output

    def test_valid_curated_csv_manifest_runs_and_writes_outputs(self):
        _, csv_path, manifest_path, output = self.setup_run()

        result = run_hyp_gap_event_study(request(csv_path, manifest_path, output))

        self.assertEqual(result.event_count, 3)
        expected = {
            "run_manifest.json",
            "events.csv",
            "event_results.csv",
            "aggregate_results.csv",
            "detection_summary.json",
        }
        self.assertEqual({path.name for path in output.iterdir()}, expected)
        manifest = json.loads((output / "run_manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["dataset_sha256"], sha256_file(csv_path))
        self.assertEqual(manifest["preregistration_hash"], manifest["config_hash"])
        self.assertEqual(manifest["requested_start"], "2024-08-01")
        self.assertEqual(manifest["loaded_warmup_start"], "2024-07-01")
        self.assertEqual(manifest["effective_event_start"], "2024-08-01")
        self.assertEqual(manifest["effective_event_end"], "2024-08-01")
        self.assertFalse(manifest["safety_flags"]["orders_sent"])
        self.assertFalse(manifest["results_approved_for_validation"])
        events = pd.read_csv(output / "events.csv")
        self.assertEqual(list(events["variant_id"]), sorted(events["variant_id"]))
        event_results = pd.read_csv(output / "event_results.csv")
        self.assertEqual(set(event_results["horizon"]), {"5min", "15min", "30min", "60min", "session_close"})
        aggregates = pd.read_csv(output / "aggregate_results.csv")
        self.assertIn("variant_id+horizon", set(aggregates["aggregation_group"]))

    def test_manifest_gate_rejects_raw_missing_bad_status_hash_and_mismatches(self):
        directory = Path(tempfile.mkdtemp())
        raw_csv = write_csv(directory / "data" / "raw", synthetic_frame())
        manifest = write_manifest(directory, raw_csv)
        with self.assertRaisesRegex(ValueError, "data/raw"):
            run_hyp_gap_event_study(request(raw_csv, manifest, directory / "out-raw"))

        _, csv_path, manifest_path, output = self.setup_run()
        with self.assertRaisesRegex(FileNotFoundError, "not found"):
            run_hyp_gap_event_study(request(csv_path, manifest_path.with_name("missing.json"), output))

        cases = [
            ({"status": "failed_audit"}, "approved"),
            ({"sha256": "bad"}, "sha256"),
            ({"symbol": "SPY"}, "symbol"),
            ({"timeframe": "5min"}, "timeframe"),
            ({"curated_file": str(csv_path.with_name("other.csv")), "output_file": str(csv_path.with_name("other.csv"))}, "curated_file or output_file"),
            ({"warnings": ["bad"]}, "audit_critical_warnings"),
            ({"safety": {"orders_sent": True}}, "orders_sent"),
        ]
        for kwargs, message in cases:
            with self.subTest(kwargs=kwargs):
                directory = Path(tempfile.mkdtemp())
                local_csv = write_csv(directory, synthetic_frame())
                local_manifest = write_manifest(directory, local_csv, **kwargs)
                with self.assertRaisesRegex(ValueError, message):
                    run_hyp_gap_event_study(request(local_csv, local_manifest, directory / "out"))

    def test_manifest_accepts_output_file_match(self):
        directory = Path(tempfile.mkdtemp())
        csv_path = write_csv(directory, synthetic_frame())
        manifest = write_manifest(directory, csv_path, curated_file=str(csv_path.with_name("other.csv")))

        result = run_hyp_gap_event_study(request(csv_path, manifest, directory / "out"))

        self.assertGreater(result.event_count, 0)

    def test_exclusions_and_missing_bars_are_applied(self):
        days = session_days("2024-08-01", 24)
        excluded = days[-2]
        frame = pd.concat(
            [
                make_session(day, profile=("positive_continuation" if day == "2024-08-01" else "prior"))
                for day in days
                if day != excluded
            ],
            ignore_index=True,
        )
        excluded_record = {
            "symbol": "QQQ",
            "date": excluded,
            "reason": "synthetic excluded",
            "policy": "exclude_entire_session",
            "missing_timestamps": [],
        }
        directory, csv_path, manifest, output = self.setup_run(
            frame=frame,
            excluded_sessions=[excluded_record],
        )

        run_hyp_gap_event_study(request(csv_path, manifest, output))
        run_manifest = json.loads((output / "run_manifest.json").read_text(encoding="utf-8"))

        self.assertEqual(run_manifest["excluded_sessions"], [excluded])

        bad_directory = Path(tempfile.mkdtemp())
        bad_csv = write_csv(bad_directory, frame)
        bad_manifest = write_manifest(bad_directory, bad_csv)
        with self.assertRaisesRegex(ValueError, "quality"):
            run_hyp_gap_event_study(request(bad_csv, bad_manifest, bad_directory / "out"))

    def test_period_policy_rejects_invalid_ranges_and_phases(self):
        _, csv_path, manifest, output = self.setup_run()
        cases = [
            ({"requested_start": "2021-12-31"}, "before discovery"),
            ({"requested_end": "2025-01-01"}, "validation|holdout"),
            ({"requested_end": "2026-01-01"}, "validation|holdout"),
            ({"requested_start": "2024-12-31", "requested_end": "2025-01-01"}, "validation|holdout"),
            ({"requested_start": "2024-08-02", "requested_end": "2024-08-01"}, "on or before"),
            (
                {
                    "requested_start": "2024-12-02",
                    "requested_end": "2025-01-02",
                    "research_phase": "validation",
                },
                "frozen",
            ),
        ]
        for kwargs, message in cases:
            with self.subTest(kwargs=kwargs):
                with self.assertRaisesRegex(ValueError, message):
                    run_hyp_gap_event_study(request(csv_path, manifest, Path(tempfile.mkdtemp()) / "out", **kwargs))

    def test_calendar_boundaries_normalize_weekends_holidays_and_regular_sessions(self):
        cases = [
            ("2024-07-27", "2024-08-01", "2024-07-29", "2024-08-01"),
            ("2024-07-28", "2024-08-01", "2024-07-29", "2024-08-01"),
            ("2024-07-04", "2024-08-01", "2024-07-05", "2024-08-01"),
            ("2024-07-01", "2024-08-03", "2024-07-01", "2024-08-02"),
            ("2024-07-01", "2024-08-04", "2024-07-01", "2024-08-02"),
            ("2024-07-01", "2024-07-04", "2024-07-01", "2024-07-03"),
            ("2024-07-27", "2024-08-04", "2024-07-29", "2024-08-02"),
            ("2024-07-01", "2024-08-01", "2024-07-01", "2024-08-01"),
        ]
        frame = pd.concat(
            [
                synthetic_frame(event_day="2024-08-01", prior_count=24),
                make_session("2024-08-02"),
            ],
            ignore_index=True,
        )
        for start, end, effective_start, effective_end in cases:
            with self.subTest(start=start, end=end):
                directory, csv_path, manifest, output = self.setup_run(frame=frame)
                run_hyp_gap_event_study(
                    request(
                        csv_path,
                        manifest,
                        output,
                        requested_start=start,
                        requested_end=end,
                    )
                )
                payload = json.loads((output / "run_manifest.json").read_text(encoding="utf-8"))
                self.assertEqual(payload["requested_start"], start)
                self.assertEqual(payload["requested_end"], end)
                self.assertEqual(payload["effective_event_start"], effective_start)
                self.assertEqual(payload["effective_event_end"], effective_end)

    def test_requested_range_without_trading_session_is_rejected(self):
        _, csv_path, manifest, _ = self.setup_run()

        with self.assertRaisesRegex(ValueError, "no recognized trading sessions"):
            run_hyp_gap_event_study(
                request(
                    csv_path,
                    manifest,
                    Path(tempfile.mkdtemp()) / "out",
                    requested_start="2024-07-06",
                    requested_end="2024-07-07",
                )
            )

    def test_expected_boundary_session_absent_is_not_skipped_silently(self):
        frame = synthetic_frame(event_day="2024-08-01", prior_count=24)
        missing_boundary = frame.loc[
            frame["timestamp"].map(
                lambda value: value.tz_convert("America/New_York").date().isoformat()
            )
            != "2024-08-01"
        ].reset_index(drop=True)
        directory, csv_path, manifest, output = self.setup_run(frame=missing_boundary)

        with self.assertRaisesRegex(ValueError, "boundary.*absent from dataset: 2024-08-01"):
            run_hyp_gap_event_study(
                request(
                    csv_path,
                    manifest,
                    output,
                    requested_start="2024-08-01",
                    requested_end="2024-08-01",
                )
            )

    def test_boundary_session_excluded_is_skipped_and_audited(self):
        frame = pd.concat(
            [
                synthetic_frame(event_day="2024-08-01", prior_count=24),
                make_session("2024-08-02"),
            ],
            ignore_index=True,
        )
        excluded_record = {
            "symbol": "QQQ",
            "date": "2024-08-01",
            "reason": "synthetic excluded boundary",
            "policy": "exclude_entire_session",
            "missing_timestamps": [],
        }
        directory, csv_path, manifest, output = self.setup_run(
            frame=frame,
            excluded_sessions=[excluded_record],
        )

        run_hyp_gap_event_study(
            request(
                csv_path,
                manifest,
                output,
                requested_start="2024-07-31",
                requested_end="2024-08-02",
            )
        )
        payload = json.loads((output / "run_manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(payload["effective_event_start"], "2024-07-31")
        self.assertEqual(payload["effective_event_end"], "2024-08-02")
        self.assertIn(
            "2024-08-01",
            payload["calendar_boundary_adjustments"][
                "excluded_sessions_skipped_inside_requested_range"
            ],
        )

    def test_regression_calendar_start_2022_01_01_uses_calendar_session(self):
        frame = pd.concat(
            [
                make_session("2022-01-03"),
                make_session("2024-12-31", profile="positive_continuation"),
            ],
            ignore_index=True,
        )
        directory, csv_path, manifest, output = self.setup_run(frame=frame)
        fake_report = type("Report", (), {"is_valid": True})()
        fake_detection = HypGapDetectionResult(
            events=(),
            summary=HypGapDetectionSummary(
                total_sessions_examined=0,
                eligible_sessions=0,
                ineligible_sessions=0,
                ineligible_reasons={},
                events_by_variant={},
                events_by_symbol={},
                first_date_examined="2022-01-03",
                last_date_examined="2024-12-31",
                config_hash="synthetic",
                safety_flags={
                    "live_trading": False,
                    "broker_connected": False,
                    "orders_sent": False,
                    "paper_broker_enabled": False,
                },
            ),
        )

        with patch(
            "src.research.runners.hyp_gap_runner.load_csv",
            return_value=(frame, fake_report),
        ), patch(
            "src.research.runners.hyp_gap_runner.detect_hyp_gap_events",
            return_value=fake_detection,
        ):
            run_hyp_gap_event_study(
                request(
                    csv_path,
                    manifest,
                    output,
                    requested_start="2022-01-01",
                    requested_end="2024-12-31",
                )
            )
        payload = json.loads((output / "run_manifest.json").read_text(encoding="utf-8"))
        expected_first_session = CALENDAR.expected_timestamps(
            pd.Timestamp("2022-01-01").date(),
            pd.Timestamp("2022-01-10").date(),
            "1min",
        )[0].tz_convert("America/New_York").date().isoformat()
        self.assertEqual(payload["requested_start"], "2022-01-01")
        self.assertEqual(payload["effective_event_start"], expected_first_session)
        self.assertNotEqual(payload["effective_event_start"], "2022-01-01")

    def test_warmup_causal_no_events_before_start_and_future_bars_ignored(self):
        frame = synthetic_frame()
        directory, csv_path, manifest, output = self.setup_run(frame=frame)
        result = run_hyp_gap_event_study(request(csv_path, manifest, output))
        events = pd.read_csv(output / "events.csv")
        self.assertEqual(set(events["session_date"]), {"2024-08-01"})
        self.assertGreater(result.event_count, 0)

        with_future = pd.concat(
            [frame, make_session("2024-08-02", profile="negative_reversal")],
            ignore_index=True,
        )
        directory2, csv2, manifest2, output2 = self.setup_run(frame=with_future)
        run_hyp_gap_event_study(request(csv2, manifest2, output2))
        self.assertEqual(
            (output / "events.csv").read_text(encoding="utf-8"),
            (output2 / "events.csv").read_text(encoding="utf-8"),
        )

    def test_adding_2025_data_does_not_change_2024_discovery_run(self):
        base = synthetic_frame()
        future_days = [
            item.date().isoformat()
            for item in pd.date_range("2024-08-02", "2025-01-03", freq="D")
            if CALENDAR.session_close(item.date()) is not None
        ]
        future = pd.concat([make_session(day) for day in future_days], ignore_index=True)
        with_2025 = pd.concat([base, future], ignore_index=True)
        directory, csv_path, manifest, output = self.setup_run(frame=base)
        directory2, csv2, manifest2, output2 = self.setup_run(frame=with_2025)

        run_hyp_gap_event_study(request(csv_path, manifest, output))
        run_hyp_gap_event_study(request(csv2, manifest2, output2))

        manifest_payload_1 = json.loads((output / "run_manifest.json").read_text(encoding="utf-8"))
        manifest_payload_2 = json.loads((output2 / "run_manifest.json").read_text(encoding="utf-8"))
        self.assertNotIn("2025", json.dumps(manifest_payload_2["requested_end"]))
        self.assertEqual(
            (output / "events.csv").read_text(encoding="utf-8"),
            (output2 / "events.csv").read_text(encoding="utf-8"),
        )
        self.assertNotEqual(manifest_payload_1["dataset_sha256"], manifest_payload_2["dataset_sha256"])

    def test_zero_events_and_output_directory_rejections(self):
        frame = synthetic_frame(profile="near_threshold")
        directory, csv_path, manifest, output = self.setup_run(frame=frame)
        result = run_hyp_gap_event_study(request(csv_path, manifest, output))
        self.assertEqual(result.event_count, 0)
        events = pd.read_csv(output / "events.csv")
        self.assertEqual(len(events), 0)

        directory2, csv2, manifest2, output2 = self.setup_run()
        output2.mkdir()
        (output2 / "existing.txt").write_text("x", encoding="utf-8")
        with self.assertRaisesRegex(FileExistsError, "not empty"):
            run_hyp_gap_event_study(request(csv2, manifest2, output2))

    def test_run_id_fingerprint_is_reproducible_and_custom_run_id_not_overwritten(self):
        directory, csv_path, manifest, output = self.setup_run()
        result = run_hyp_gap_event_study(request(csv_path, manifest, output, run_id="CUSTOM-RUN"))
        payload = json.loads((output / "run_manifest.json").read_text(encoding="utf-8"))

        self.assertEqual(result.run_id, "CUSTOM-RUN")
        self.assertIn("fingerprint", payload)
        with self.assertRaisesRegex(FileExistsError, "not empty"):
            run_hyp_gap_event_study(request(csv_path, manifest, output, run_id="CUSTOM-RUN"))

    def test_no_strategy_metrics_are_persisted(self):
        _, csv_path, manifest, output = self.setup_run()
        run_hyp_gap_event_study(request(csv_path, manifest, output))
        combined = "\n".join(path.read_text(encoding="utf-8") for path in output.iterdir())

        for forbidden in ("profit_factor", "sharpe", "sortino", "drawdown", "take_profit", "stop_loss"):
            self.assertNotIn(forbidden, combined.lower())

    def test_validation_runner_is_frozen_to_hyp_gap_03_and_rejects_holdout(self):
        frame = synthetic_frame(event_day="2025-01-02", profile="positive_continuation")
        directory, csv_path, manifest, output = self.setup_run(frame=frame)

        result = run_hyp_gap_event_study(
            request(
                csv_path,
                manifest,
                output,
                requested_start="2024-12-02",
                requested_end="2025-01-02",
                research_phase="validation",
                variant_ids=("HYP-GAP-03",),
            )
        )

        self.assertEqual(result.event_count, 1)
        events = pd.read_csv(output / "events.csv")
        self.assertEqual(set(events["variant_id"]), {"HYP-GAP-03"})
        payload = json.loads((output / "run_manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(payload["research_phase"], "validation")
        self.assertEqual(payload["variant_ids_executed"], ["HYP-GAP-03"])
        self.assertEqual(payload["effective_event_start"], "2025-01-02")

        with self.assertRaisesRegex(ValueError, "holdout"):
            run_hyp_gap_event_study(
                request(
                    csv_path,
                    manifest,
                    Path(tempfile.mkdtemp()) / "out",
                    requested_start="2024-12-02",
                    requested_end="2026-01-02",
                    research_phase="validation",
                    variant_ids=("HYP-GAP-03",),
                )
            )
        with self.assertRaisesRegex(ValueError, "frozen"):
            run_hyp_gap_event_study(
                request(
                    csv_path,
                    manifest,
                    Path(tempfile.mkdtemp()) / "out",
                    requested_start="2024-12-02",
                    requested_end="2025-01-02",
                    research_phase="validation",
                    variant_ids=("HYP-GAP-02",),
                )
            )


if __name__ == "__main__":
    unittest.main()
