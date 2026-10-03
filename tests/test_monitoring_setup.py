import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "tools" / "monitoring_setup.py"
_spec = importlib.util.spec_from_file_location("monitoring_setup", SCRIPT_PATH)
monitoring_setup = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(monitoring_setup)


class HighMemoryUsageTests(unittest.TestCase):
    def test_alert_uses_machine_memory_and_matches_recording_rule(self):
        alert = next(
            rule for rule in monitoring_setup.RECOMMENDED_ALERT_RULES
            if rule["name"] == "HighMemoryUsage"
        )
        recording_rule = next(
            rule for rule in monitoring_setup.RECOMMENDED_RECORDING_RULES
            if rule["name"] == "instance:memory_usage:ratio"
        )

        self.assertIn("machine_memory_bytes", alert["expr"])
        self.assertNotIn(
            "process_resident_memory_bytes / process_resident_memory_bytes",
            alert["expr"],
        )
        self.assertEqual(
            alert["expr"],
            f"{recording_rule['expr']} > 0.9",
        )

    def test_alert_keeps_ten_minute_warning(self):
        alert = next(
            rule for rule in monitoring_setup.RECOMMENDED_ALERT_RULES
            if rule["name"] == "HighMemoryUsage"
        )

        self.assertEqual(alert["duration"], "10m")
        self.assertEqual(alert["severity"], "warning")

    def test_alert_dry_run_does_not_make_network_calls(self):
        stdout = io.StringIO()
        with mock.patch.object(sys, "argv", [str(SCRIPT_PATH), "--alerts", "--dry-run"]), \
             mock.patch.object(
                 monitoring_setup, "http_request",
                 side_effect=AssertionError("dry-run attempted network I/O"),
             ) as http_request, \
             mock.patch("builtins.open", side_effect=AssertionError("dry-run wrote a file")), \
             contextlib.redirect_stdout(stdout):
            result = monitoring_setup.main()

        self.assertEqual(result, 0)
        http_request.assert_not_called()
        self.assertIn("HighMemoryUsage", stdout.getvalue())

    def test_threshold_and_duration_with_promtool(self):
        promtool = os.environ.get("PROMTOOL") or shutil.which("promtool")
        if not promtool:
            self.skipTest("Set PROMTOOL or install promtool to evaluate PromQL")
        alert = next(rule for rule in monitoring_setup.RECOMMENDED_ALERT_RULES
                     if rule["name"] == "HighMemoryUsage")
        labels = {"instance": "test:9090", "job": "test", "severity": "warning"}
        expected = [{"exp_labels": labels, "exp_annotations": {
            "summary": "High memory usage on test:9090",
            "description": alert["description"],
        }}]
        cases = []
        # A nonzero low RSS must not alert; the old self-division fails here.
        for rss, eval_time, alerts in [(100, "10m", []), (900, "10m", []),
                                       (950, "9m", []), (950, "10m", expected)]:
            cases.append({"interval": "1m", "input_series": [
                {"series": 'process_resident_memory_bytes{instance="test:9090",job="test"}',
                 "values": f"{rss}+0x15"},
                {"series": 'machine_memory_bytes{instance="test:9090",job="test"}',
                 "values": "1000+0x15"},
            ], "alert_rule_test": [{"eval_time": eval_time,
                                     "alertname": alert["name"], "exp_alerts": alerts}]})
        with tempfile.TemporaryDirectory() as directory:
            rules_path = Path(directory) / "rules.yml"
            tests_path = Path(directory) / "tests.yml"
            rules_path.write_text(json.dumps({"groups": [{"name": "memory", "rules": [{
                "alert": alert["name"], "expr": alert["expr"], "for": alert["duration"],
                "labels": {"severity": alert["severity"]},
                "annotations": {"summary": alert["summary"], "description": alert["description"]},
            }]}]}), encoding="utf-8")
            tests_path.write_text(json.dumps({"rule_files": [str(rules_path)],
                                             "evaluation_interval": "1m", "tests": cases}),
                                  encoding="utf-8")
            result = subprocess.run([promtool, "test", "rules", str(tests_path)],
                                    capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
