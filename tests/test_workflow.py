import argparse
import copy
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "skills/codex-efficient-workflow/scripts/workflow.py"
EXAMPLES = REPO / "skills/codex-efficient-workflow/assets/examples"
spec = importlib.util.spec_from_file_location("workflow", SCRIPT)
w = importlib.util.module_from_spec(spec)
spec.loader.exec_module(w)


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.project = Path(self.temp.name).resolve()
        w.init(self.project)

    def tearDown(self):
        self.temp.cleanup()

    def config(self):
        return w.load(self.project)[1]

    def receipt(self):
        # Synthetic observations are only used inside this isolated test workspace.
        catalog = w.read(EXAMPLES / "catalog.example.json")
        catalog["fixture"] = False
        catalog["checked_at"] = w.stamp()
        candidate = catalog["candidates"][0]
        candidate["released_at"] = w.stamp(w.now() - timedelta(days=1))
        candidate["availability_checked_at"] = w.stamp()
        evs = w.read(EXAMPLES / "evaluation.example.json")
        ev = evs["evaluations"][0]
        ev["fixture"] = False
        ev["evaluated_at"] = w.stamp()
        ev["config_fingerprint"] = w.fingerprint(self.config())
        return catalog, evs

    def set_role(self, **values):
        args = argparse.Namespace(role="executor", model=None, provider=None, family=None,
                                  generation=None, effort=None, update_mode="pinned")
        for key, value in values.items():
            setattr(args, key, value)
        return w.set_role(self.project, args)

    def test_initial_check_due_and_idempotent_init(self):
        before = self.config()
        self.assertTrue(w.status(self.project)["refresh_due"])
        self.set_role(model="my-model")
        w.init(self.project)
        self.assertEqual(self.config()["roles"]["executor"]["model"], "my-model")
        self.assertEqual(before["roles"]["planner"], self.config()["roles"]["planner"])

    def test_success_caches_check(self):
        catalog, _ = self.receipt()
        w.refresh(self.project, catalog)
        self.assertFalse(w.status(self.project)["refresh_due"])
        self.assertEqual(self.config()["roles"]["executor"]["model"], "gpt-6-luna")

    def test_offline_does_not_claim_success_and_backs_off(self):
        w.refresh(self.project, failed=True)
        result = w.status(self.project)
        self.assertIsNone(result["state"]["last_successful_check_at"])
        self.assertFalse(result["refresh_due"])
        self.assertIsNotNone(result["retry_after"])

    def test_old_success_due(self):
        base, _, state = w.load(self.project)
        state["last_successful_check_at"] = w.stamp(w.now() - timedelta(days=8))
        w.write(base / "state.json", state)
        self.assertTrue(w.status(self.project)["refresh_due"])

    def test_major_apply_and_rollback(self):
        catalog, evs = self.receipt()
        before = self.config()["roles"]
        result = w.refresh(self.project, catalog, evs, apply=True)
        self.assertEqual(result["applied"], ["executor"])
        self.assertEqual(self.config()["roles"]["executor"]["generation"], 7)
        self.assertFalse(result["runtime_applied"])
        w.rollback(self.project, result["backup"])
        self.assertEqual(self.config()["roles"], before)
        self.assertGreaterEqual(len(list((w.folder(self.project) / "audit").glob("*.json"))), 2)

    def test_dry_run_preserves_configuration(self):
        catalog, evs = self.receipt()
        before = self.config()
        result = w.refresh(self.project, catalog, evs)
        self.assertEqual(result["applied"], [])
        self.assertIn("executor", result["eligible"])
        self.assertEqual(before, self.config())

    def test_pinned_role_not_upgraded(self):
        self.set_role()
        catalog, evs = self.receipt()
        result = w.refresh(self.project, catalog, evs, apply=True)
        self.assertEqual(result["applied"], [])

    def test_minor_release_not_upgraded(self):
        catalog, evs = self.receipt()
        catalog["candidates"][0]["generation"] = 6
        self.assertEqual(w.refresh(self.project, catalog, evs, apply=True)["applied"], [])

    def test_other_provider_family_not_upgraded(self):
        catalog, evs = self.receipt()
        catalog["candidates"][0]["provider"] = "different-provider"
        self.assertEqual(w.refresh(self.project, catalog, evs, apply=True)["applied"], [])

    def test_ineligible_candidates_remain_pending(self):
        for key, value, fragment in (("available", False, "unavailable"),
                                     ("release_status", "preview", "stable"),
                                     ("supported_efforts", ["low"], "unsupported")):
            with self.subTest(key=key):
                catalog, evs = self.receipt()
                catalog["candidates"][0][key] = value
                result = w.refresh(self.project, catalog, evs, apply=True)
                self.assertFalse(result["applied"])
                self.assertIn(fragment, result["pending"][0]["reason"])

    def test_missing_evaluation_pending(self):
        catalog, _ = self.receipt()
        self.assertIn("missing", w.refresh(self.project, catalog, apply=True)["pending"][0]["reason"])

    def test_partial_catalog_does_not_claim_full_check(self):
        catalog, evs = self.receipt()
        catalog["checked_families"] = catalog["checked_families"][:1]
        with self.assertRaisesRegex(ValueError, "cover"):
            w.refresh(self.project, catalog, evs, apply=True)
        self.assertIsNone(w.status(self.project)["state"]["last_successful_check_at"])

    def test_quality_failure_preserves_current_model(self):
        catalog, evs = self.receipt()
        evs["evaluations"][0]["cases"][0]["candidate_mandatory_pass"] = False
        result = w.refresh(self.project, catalog, evs, apply=True)
        self.assertFalse(result["applied"])
        self.assertEqual(self.config()["roles"]["executor"]["model"], "gpt-6-luna")

    def test_zero_quality_is_not_accepted(self):
        catalog, evs = self.receipt()
        for case in evs["evaluations"][0]["cases"]:
            case["baseline_pass"] = False
            case["candidate_pass"] = False
        result = w.refresh(self.project, catalog, evs, apply=True)
        self.assertIn("floor", result["pending"][0]["reason"])

    def test_cost_regression_pending(self):
        catalog, evs = self.receipt()
        evs["evaluations"][0]["cases"][0]["candidate_usage"] = 10000
        self.assertIn("usage", w.refresh(self.project, catalog, evs, apply=True)["pending"][0]["reason"])

    def test_invalid_usage_never_counts_as_zero(self):
        for value in (None, True, float("nan"), -1):
            with self.subTest(value=value):
                catalog, evs = self.receipt()
                evs["evaluations"][0]["cases"][0]["candidate_usage"] = value
                result = w.refresh(self.project, catalog, evs, apply=True)
                self.assertFalse(result["applied"])

    def test_unknown_metric_pending(self):
        catalog, evs = self.receipt()
        evs["evaluations"][0]["usage_metric"] = "estimated_subscription_price"
        self.assertFalse(w.refresh(self.project, catalog, evs, apply=True)["applied"])

    def test_config_changed_since_evaluation(self):
        catalog, evs = self.receipt()
        self.set_role(role="reviewer", effort="medium")
        self.assertIn("configuration", w.refresh(self.project, catalog, evs, apply=True)["pending"][0]["reason"])

    def test_example_fixture_refused(self):
        with self.assertRaisesRegex(ValueError, "fixture"):
            w.refresh(self.project, w.read(EXAMPLES / "catalog.example.json"), apply=True)

    def test_evaluation_fixture_pending(self):
        catalog, evs = self.receipt()
        evs["evaluations"][0]["fixture"] = True
        self.assertFalse(w.refresh(self.project, catalog, evs, apply=True)["applied"])

    def test_stale_future_and_unofficial_evidence_refused(self):
        for value in (w.stamp(w.now() - timedelta(days=8)), w.stamp(w.now() + timedelta(days=1))):
            catalog, _ = self.receipt()
            catalog["checked_at"] = value
            with self.assertRaises(ValueError):
                w.refresh(self.project, catalog, apply=True)
        for url in ("https://developers.openai.com.evil.test/news", "http://developers.openai.com/news",
                    "https://user@developers.openai.com/news"):
            catalog, _ = self.receipt()
            catalog["candidates"][0]["source_urls"] = [url]
            with self.assertRaises(ValueError):
                w.refresh(self.project, catalog, apply=True)

    def test_generate_preserves_unrelated_config_and_detects_manual_edits(self):
        dest = self.project / ".codex"
        dest.mkdir()
        global_cfg = dest / "config.toml"
        global_cfg.write_text('model = "user-owned"\n')
        result = w.generate(self.project)
        self.assertEqual(len(result["generated"]), 4)
        self.assertEqual(global_cfg.read_text(), 'model = "user-owned"\n')
        target = dest / "agents/cew-executor.toml"
        target.write_text("user-owned customization\n")
        before = (dest / "agents/cew-planner.toml").read_bytes()
        with self.assertRaisesRegex(ValueError, "modified"):
            w.generate(self.project)
        self.assertEqual(target.read_text(), "user-owned customization\n")
        self.assertEqual((dest / "agents/cew-planner.toml").read_bytes(), before)

    def test_generated_toml_parses_when_parser_available(self):
        try:
            import tomllib
        except ImportError:
            self.skipTest("stdlib TOML parser requires Python 3.11+")
        result = w.generate(self.project)
        for file in result["generated"]:
            entry = tomllib.loads(Path(file).read_text())
            self.assertIn("model_reasoning_effort", entry)
            self.assertIn("developer_instructions", entry)

    def test_symlink_state_and_agent_directory_escape_refused(self):
        with tempfile.TemporaryDirectory() as other:
            fake_project = self.project / "fake"
            fake_project.mkdir()
            (fake_project / ".codex-efficient-workflow").symlink_to(other, target_is_directory=True)
            with self.assertRaises(ValueError):
                w.init(fake_project)
            (self.project / ".codex").symlink_to(other, target_is_directory=True)
            with self.assertRaises(ValueError):
                w.generate(self.project)

    def test_rollback_rejects_path_traversal(self):
        with self.assertRaises(ValueError):
            w.rollback(self.project, "../../secret")

    def test_unknown_run_usage_preserved(self):
        receipt = w.read(EXAMPLES / "run-receipt.example.json")
        result = w.record_run(self.project, receipt)
        self.assertIsNone(result["measured_usage"])
        self.assertIsNotNone(w.status(self.project)["state"]["last_run_at"])

    def test_cli_user_path_with_spaces(self):
        project = self.project / "my project"
        result = subprocess.run([sys.executable, str(SCRIPT), "init", "--project", str(project)],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(json.loads(result.stdout)["initialized"])


if __name__ == "__main__":
    unittest.main()
