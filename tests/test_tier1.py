import logging
import unittest

from engine.config_compile import compile_config, CompiledConfig
from engine.config_validate import ConfigValidationError, validate_compiled_config
from engine.explain import (
    build_explain_snapshot,
    format_light_command,
    source_label,
)
from engine.reconcile import Reconciler
from engine.world import WorldState
from modules.config import config as pccs_config


def _minimal_compiled() -> CompiledConfig:
    """Small valid compiled config for validation tests."""
    cfg = CompiledConfig()
    cfg.light_names = ["kitchen_panel", "accent"]
    cfg.pwm_lights = {"accent": 8}
    cfg.rgb_lights = {"kitchen_panel": {"white": 2, "red": 3, "green": 4}}
    cfg.reed_names = ["kitchen_panel"]
    cfg.reed_to_lights = {"kitchen_panel": ["kitchen_panel"]}
    cfg.light_to_reed = {"kitchen_panel": "kitchen_panel"}
    cfg.ambient_lights = ["accent"]
    cfg.reed_phase_levels = {
        "kitchen_panel": {
            "evening": (20, "white"),
            "night": (10, "red"),
        }
    }
    cfg.ambient_phase_levels = {
        "accent": {"evening": (20, "white"), "night": (5, "white")}
    }
    return cfg


class _FakeArduino:
    def read_lights(self):
        return {"kitchen_panel": 5, "accent": 0}, {"kitchen_panel": "white"}

    def set_light(self, *args, **kwargs):
        pass


class _FakeRelays:
    def read_relays(self):
        return {}

    def set_relay(self, *args, **kwargs):
        pass


class ExplainTests(unittest.TestCase):
    def test_source_label_known(self):
        self.assertEqual(source_label("automation_reed"), "reed open · phase level")

    def test_format_light_command_includes_why(self):
        line = format_light_command(
            "kitchen_panel", 20, "white", "automation_reed", "reed", 2000
        )
        self.assertIn("kitchen_panel", line)
        self.assertIn("reed open", line)
        self.assertIn("trigger:reed", line)

    def test_explain_snapshot_marks_drift(self):
        world = WorldState(
            reeds={"kitchen_panel": False},
            phase="Evening",  # phase required for non-zero desired levels
            observed_lights={"kitchen_panel": 5, "accent": 0},
            observed_light_modes={"kitchen_panel": "white"},
        )
        cfg = _minimal_compiled()
        snap = build_explain_snapshot(world, cfg)
        self.assertTrue(snap["has_drift"])
        self.assertEqual(snap["lights"]["kitchen_panel"]["source"], "automation_reed")


class ConfigValidateTests(unittest.TestCase):
    def test_real_config_passes(self):
        compiled = compile_config(pccs_config)
        self.assertGreater(len(compiled.reed_names), 0)

    def test_missing_reed_phase_fails(self):
        cfg = _minimal_compiled()
        del cfg.reed_phase_levels["kitchen_panel"]["night"]
        with self.assertRaises(ConfigValidationError) as ctx:
            validate_compiled_config(pccs_config, cfg)
        self.assertTrue(any("night" in e for e in ctx.exception.errors))

    def test_unknown_scene_light_fails(self):
        cfg = _minimal_compiled()
        cfg.scenes = {"bedtime": {"lights": {"nonexistent": {"type": "fixed", "brightness": 0}}}}
        with self.assertRaises(ConfigValidationError):
            validate_compiled_config(pccs_config, cfg)


class DriftTests(unittest.TestCase):
    def setUp(self):
        self._logger = logging.getLogger("pccs")
        self._prev_level = self._logger.level
        self._logger.setLevel(logging.CRITICAL)

    def tearDown(self):
        self._logger.setLevel(self._prev_level)

    def _make_drift_reconciler(self, observed_panel=5, observed_accent=0):
        from engine.world import WorldStore

        compiled = _minimal_compiled()
        world = WorldStore(compiled.reed_names, compiled.light_names, [])
        world.set_phase("Evening", invalidate=False)
        world.update_reeds({"kitchen_panel": False})
        world.update_observed_lights(
            {"kitchen_panel": observed_panel, "accent": observed_accent},
            {"kitchen_panel": "white"},
        )
        rec = Reconciler(
            world=world,
            cfg=compiled,
            arduino_actuator=_FakeArduino(),
            relay_actuator=_FakeRelays(),
        )
        rec._drift_grace_s = 0
        rec.reconcile(ramp_source="reed")
        return rec

    def test_drift_detected_after_grace(self):
        rec = self._make_drift_reconciler()
        drifts = rec.report_hardware_drift()
        drift_lights = {d["light"] for d in drifts if "light" in d}
        self.assertIn("kitchen_panel", drift_lights)

    def test_drift_logs_warning(self):
        rec = self._make_drift_reconciler()
        self._logger.setLevel(logging.WARNING)
        with self.assertLogs("pccs", level="WARNING") as captured:
            rec.report_hardware_drift()
        joined = "\n".join(captured.output)
        self.assertIn("Hardware drift", joined)
        self.assertIn("kitchen_panel", joined)

    def test_drift_clears_when_hardware_matches(self):
        rec = self._make_drift_reconciler(observed_panel=20, observed_accent=20)
        self.assertEqual(rec.report_hardware_drift(), [])


if __name__ == "__main__":
    unittest.main()