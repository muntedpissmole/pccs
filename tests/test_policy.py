import unittest

from engine.config_compile import CompiledConfig, compile_config
from engine.intent import LightIntent, RelayIntent
from engine.policy import desired_outputs
from engine.precedence import effective_reed_closed, resolve_light, resolve_screen
from engine.world import WorldState, WorldStore
from modules.config import config as pccs_config


def minimal_cfg() -> CompiledConfig:
    cfg = CompiledConfig()
    cfg.light_names = [
        "rooftop_tent", "accent", "ensuite", "kitchen_bench", "kitchen_panel",
        "awning", "rear_drawer",
    ]
    cfg.pwm_lights = {
        "rooftop_tent": 12,
        "accent": 8,
        "ensuite": 13,
        "kitchen_bench": 5,
        "kitchen_panel": 6,
        "awning": 9,
        "rear_drawer": 7,
    }
    cfg.rgb_lights = {
        "kitchen_panel": {"white": 2, "red": 3, "green": 4},
        "awning": {"white": 9, "red": 10, "green": 11},
    }
    cfg.relay_names = ["floodlights"]
    cfg.reed_names = [
        "rooftop_tent", "kitchen_bench", "kitchen_panel", "rear_drawer",
    ]
    cfg.reed_to_lights = {
        "rooftop_tent": ["rooftop_tent"],
        "kitchen_bench": ["kitchen_bench"],
        "kitchen_panel": ["kitchen_panel"],
        "rear_drawer": ["rear_drawer"],
    }
    cfg.light_to_reed = {
        "rooftop_tent": "rooftop_tent",
        "kitchen_bench": "kitchen_bench",
        "kitchen_panel": "kitchen_panel",
        "rear_drawer": "rear_drawer",
    }
    cfg.interlocks = {"kitchen_bench": ["kitchen_panel"]}
    cfg.ambient_lights = ["accent", "awning"]
    cfg.all_closed_action = "off"
    cfg.reed_phase_levels = {
        "rooftop_tent": {
            "day": (0, "white"),
            "evening": (20, "white"),
            "night": (5, "white"),
        },
        "kitchen_bench": {
            "day": (100, "white"),
            "evening": (30, "white"),
            "night": (5, "white"),
        },
        "kitchen_panel": {
            "day": (100, "white"),
            "evening": (40, "white"),
            "night": (5, "white"),
        },
        "rear_drawer": {
            "day": (0, "white"),
            "evening": (50, "white"),
            "night": (10, "white"),
        },
    }
    cfg.ambient_phase_levels = {
        "accent": {"day": (0, "white"), "evening": (20, "white"), "night": (5, "white")},
        "awning": {"day": (0, "white"), "evening": (20, "white"), "night": (10, "red")},
    }
    cfg.screens = {
        "kitchen": {
            "friendly": "Kitchen",
            "linked_reed": "kitchen_panel",
            "host": "10.10.10.10",
            "username": "joel",
            "brightness_path": "/sys/class/graphics/fb0/blank",
            "icon": "fa-utensils",
        }
    }
    cfg.scenes = {
        "bedtime": {
            "name": "Bedtime",
            "all_off": False,
            "lights": {
                "kitchen_panel": {"type": "fixed", "brightness": 5, "mode": "white"},
                "rooftop_tent": {"type": "fixed", "brightness": 5, "mode": "white"},
                "accent": {"type": "phase", "phase": "night"},
            },
        },
        "all_off": {"name": "All Off", "all_off": True, "lights": {}},
        "evening_mood": {
            "name": "Evening",
            "evening_levels": True,
            "lights": {"accent": {"type": "phase", "phase": "night"}},
        },
        "night_mood": {
            "name": "Night",
            "night_levels": True,
            "lights": {},
        },
        "day_mood": {
            "name": "Day",
            "day_levels": True,
            "lights": {},
        },
    }
    return cfg


def dim_cfg() -> CompiledConfig:
    cfg = minimal_cfg()
    cfg.all_closed_action = "dim"
    return cfg


def real_cfg() -> CompiledConfig:
    return compile_config(pccs_config)


def _default_reeds(open_names=(), closed_names=()) -> dict:
    """Default: tent/bench/panel/rear_drawer — unspecified default closed."""
    names = ["rooftop_tent", "kitchen_bench", "kitchen_panel", "rear_drawer"]
    reeds = {n: True for n in names}
    for n in open_names:
        reeds[n] = False
    for n in closed_names:
        reeds[n] = True
    return reeds


class PolicyTests(unittest.TestCase):
    # ── Reed-linked automation ──────────────────────────────────────────

    def test_tent_open_user_off_stays_off(self):
        world = WorldState(
            reeds=_default_reeds(open_names=["rooftop_tent"]),
            phase="Evening",
            light_intents={"rooftop_tent": LightIntent(0, expires="until_reed_close")},
        )
        out = desired_outputs(world, minimal_cfg())
        self.assertEqual(out.lights["rooftop_tent"][0], 0)
        self.assertEqual(out.light_sources["rooftop_tent"], "user_intent")

    def test_no_phase_automation_deferred(self):
        world = WorldState(reeds=_default_reeds(open_names=["rooftop_tent"]), phase="")
        out = desired_outputs(world, minimal_cfg())
        self.assertEqual(out.lights["rooftop_tent"][0], 0)
        self.assertEqual(out.light_sources["rooftop_tent"], "phase_pending")

    def test_tent_close_then_open_gets_phase_level(self):
        world = WorldState(reeds=_default_reeds(open_names=["rooftop_tent"]), phase="Evening")
        out = desired_outputs(world, minimal_cfg())
        self.assertEqual(out.lights["rooftop_tent"][0], 20)
        self.assertEqual(out.light_sources["rooftop_tent"], "automation_reed")

    def test_tent_closed_forces_off(self):
        world = WorldState(reeds=_default_reeds(closed_names=["rooftop_tent"]), phase="Evening")
        out = desired_outputs(world, minimal_cfg())
        self.assertEqual(out.lights["rooftop_tent"][0], 0)
        self.assertEqual(out.light_sources["rooftop_tent"], "reed_closed")

    def test_force_reed_closed_overrides_open_hardware(self):
        world = WorldState(
            reeds=_default_reeds(open_names=["rooftop_tent"]),
            reed_forces={"rooftop_tent": True},
            phase="Evening",
        )
        out = desired_outputs(world, minimal_cfg())
        self.assertEqual(out.lights["rooftop_tent"][0], 0)
        self.assertEqual(out.light_sources["rooftop_tent"], "reed_closed")

    def test_phase_evening_vs_night_changes_reed_level(self):
        cfg = minimal_cfg()
        reeds = _default_reeds(open_names=["rooftop_tent"])
        evening = desired_outputs(WorldState(reeds=reeds, phase="Evening"), cfg)
        night = desired_outputs(WorldState(reeds=reeds, phase="Night"), cfg)
        self.assertEqual(evening.lights["rooftop_tent"][0], 20)
        self.assertEqual(night.lights["rooftop_tent"][0], 5)

    def test_forced_phase_overrides_scheduled_phase(self):
        world = WorldState(
            reeds=_default_reeds(open_names=["rooftop_tent"]),
            phase="Day",
            phase_forced="Night",
        )
        out = desired_outputs(world, minimal_cfg())
        self.assertEqual(out.lights["rooftop_tent"][0], 5)
        self.assertEqual(out.light_sources["rooftop_tent"], "automation_reed")

    def test_day_phase_rooftop_stays_off(self):
        world = WorldState(reeds=_default_reeds(open_names=["rooftop_tent"]), phase="Day")
        out = desired_outputs(world, minimal_cfg())
        self.assertEqual(out.lights["rooftop_tent"][0], 0)

    def test_day_phase_rear_drawer_stays_off(self):
        world = WorldState(reeds=_default_reeds(open_names=["rear_drawer"]), phase="Day")
        out = desired_outputs(world, minimal_cfg())
        self.assertEqual(out.lights["rear_drawer"][0], 0)

    def test_invalid_phase_falls_back_to_evening(self):
        world = WorldState(reeds=_default_reeds(open_names=["rooftop_tent"]), phase="Bonkers")
        out = desired_outputs(world, minimal_cfg())
        self.assertEqual(out.lights["rooftop_tent"][0], 20)

    # ── Ambient lighting ──────────────────────────────────────────────────

    def test_all_reeds_closed_ambient_off(self):
        world = WorldState(reeds=_default_reeds(), phase="Evening")
        out = desired_outputs(world, minimal_cfg())
        self.assertEqual(out.lights["accent"][0], 0)
        self.assertEqual(out.light_sources["accent"], "automation_all_closed")

    def test_any_reed_open_ambient_on(self):
        world = WorldState(reeds=_default_reeds(open_names=["rooftop_tent"]), phase="Night")
        out = desired_outputs(world, minimal_cfg())
        self.assertEqual(out.lights["accent"][0], 5)

    def test_all_closed_action_dim_uses_night_level(self):
        world = WorldState(reeds=_default_reeds(), phase="Evening")
        out = desired_outputs(world, dim_cfg())
        self.assertEqual(out.lights["accent"][0], 5)
        self.assertEqual(out.light_sources["accent"], "automation_all_closed_dim")

    def test_user_intent_on_ambient_light(self):
        world = WorldState(
            reeds=_default_reeds(open_names=["rooftop_tent"]),
            phase="Evening",
            light_intents={"accent": LightIntent(40, expires="until_reed_close")},
        )
        out = desired_outputs(world, minimal_cfg())
        self.assertEqual(out.lights["accent"][0], 40)
        self.assertEqual(out.light_sources["accent"], "user_intent")

    def test_rgb_mode_on_awning_at_night(self):
        world = WorldState(reeds=_default_reeds(open_names=["rooftop_tent"]), phase="Night")
        out = desired_outputs(world, minimal_cfg())
        self.assertEqual(out.lights["awning"][0], 10)
        self.assertEqual(out.light_modes["awning"], "red")

    # ── Standalone lights ─────────────────────────────────────────────────

    def test_standalone_light_defaults_off(self):
        world = WorldState(reeds=_default_reeds(open_names=["rooftop_tent"]), phase="Evening")
        out = desired_outputs(world, minimal_cfg())
        self.assertEqual(out.lights["ensuite"][0], 0)

    # ── Scenes ────────────────────────────────────────────────────────────

    def test_user_intent_beats_scene(self):
        world = WorldState(
            reeds=_default_reeds(open_names=["kitchen_panel"]),
            phase="Evening",
            active_scene="bedtime",
            light_intents={"kitchen_panel": LightIntent(80, expires="until_reed_close")},
        )
        out = desired_outputs(world, minimal_cfg())
        self.assertEqual(out.lights["kitchen_panel"][0], 80)
        self.assertEqual(out.light_sources["kitchen_panel"], "user_intent")

    def test_scene_applies_when_no_intent(self):
        world = WorldState(
            reeds=_default_reeds(open_names=["kitchen_panel"]),
            phase="Evening",
            active_scene="bedtime",
        )
        out = desired_outputs(world, minimal_cfg())
        self.assertEqual(out.lights["kitchen_panel"][0], 5)
        self.assertEqual(out.light_sources["kitchen_panel"], "scene")

    def test_stale_intents_block_transient_scene_snapshot(self):
        """set_scene clears intents before reconciling so scene levels are not skipped."""
        cfg = minimal_cfg()
        zero_intents = {
            name: LightIntent(0, expires="until_phase_change") for name in cfg.light_names
        }
        world = WorldState(
            reeds=_default_reeds(open_names=["kitchen_panel"]),
            phase="Evening",
            active_scene="bedtime",
            light_intents=zero_intents,
        )
        out = desired_outputs(world, cfg)
        self.assertEqual(out.lights["kitchen_panel"][0], 0)
        self.assertEqual(out.light_sources["kitchen_panel"], "user_intent")

    def test_transient_scene_applies_when_intents_cleared(self):
        cfg = minimal_cfg()
        world = WorldStore(cfg.reed_names, cfg.light_names, [])
        world.set_light_to_reed_map(cfg.light_to_reed)
        world.set_phase("Evening", invalidate=False)
        world.update_reeds(_default_reeds(open_names=["kitchen_panel"]))
        for light in cfg.light_names:
            world.set_light_intent(light, 0, expires="until_phase_change")

        world.clear_all_light_intents()
        world.set_active_scene("bedtime")
        out = desired_outputs(world.snapshot(), cfg)

        self.assertEqual(out.lights["kitchen_panel"][0], 5)
        self.assertEqual(out.light_sources["kitchen_panel"], "scene")

    def test_scene_phase_reference(self):
        world = WorldState(
            reeds=_default_reeds(open_names=["rooftop_tent"]),
            phase="Evening",
            active_scene="bedtime",
        )
        out = desired_outputs(world, minimal_cfg())
        self.assertEqual(out.lights["accent"][0], 5)
        self.assertEqual(out.light_sources["accent"], "scene")

    def test_scene_skips_reed_closed_light(self):
        world = WorldState(
            reeds=_default_reeds(open_names=["kitchen_panel"], closed_names=["rooftop_tent"]),
            phase="Evening",
            active_scene="bedtime",
        )
        out = desired_outputs(world, minimal_cfg())
        self.assertEqual(out.lights["rooftop_tent"][0], 0)
        self.assertEqual(out.light_sources["rooftop_tent"], "reed_closed")
        self.assertEqual(out.lights["kitchen_panel"][0], 5)
        self.assertEqual(out.light_sources["kitchen_panel"], "scene")

    def test_scene_ambient_skipped_when_all_reeds_closed(self):
        world = WorldState(reeds=_default_reeds(), phase="Evening", active_scene="bedtime")
        out = desired_outputs(world, minimal_cfg())
        self.assertEqual(out.lights["accent"][0], 0)
        self.assertNotEqual(out.light_sources["accent"], "scene")

    def test_all_off_scene(self):
        world = WorldState(
            reeds=_default_reeds(
                open_names=["rooftop_tent", "kitchen_bench", "kitchen_panel", "rear_drawer"]
            ),
            phase="Evening",
            active_scene="all_off",
        )
        out = desired_outputs(world, minimal_cfg())
        for light in minimal_cfg().light_names:
            self.assertEqual(out.lights[light][0], 0)
            self.assertEqual(out.light_sources[light], "scene_all_off")

    def test_evening_levels_scene(self):
        world = WorldState(
            reeds=_default_reeds(open_names=["kitchen_bench", "kitchen_panel"]),
            phase="Night",
            active_scene="evening_mood",
        )
        out = desired_outputs(world, minimal_cfg())
        self.assertEqual(out.lights["kitchen_panel"][0], 40)
        self.assertEqual(out.light_sources["kitchen_panel"], "scene_evening")
        self.assertEqual(out.lights["accent"][0], 5)
        self.assertEqual(out.light_sources["accent"], "scene")

    def test_night_levels_scene(self):
        world = WorldState(
            reeds=_default_reeds(open_names=["kitchen_panel"]),
            phase="Evening",
            active_scene="night_mood",
        )
        out = desired_outputs(world, minimal_cfg())
        self.assertEqual(out.lights["kitchen_panel"][0], 5)
        self.assertEqual(out.light_sources["kitchen_panel"], "scene_night")

    def test_day_levels_scene(self):
        world = WorldState(
            reeds=_default_reeds(open_names=["kitchen_bench", "kitchen_panel"]),
            phase="Night",
            active_scene="day_mood",
        )
        out = desired_outputs(world, minimal_cfg())
        self.assertEqual(out.lights["kitchen_panel"][0], 100)
        self.assertEqual(out.light_sources["kitchen_panel"], "scene_day")

    def test_reed_closed_beats_scene(self):
        world = WorldState(
            reeds=_default_reeds(closed_names=["rooftop_tent"]),
            phase="Evening",
            active_scene="evening_mood",
        )
        out = desired_outputs(world, minimal_cfg())
        self.assertEqual(out.lights["rooftop_tent"][0], 0)
        self.assertEqual(out.light_sources["rooftop_tent"], "reed_closed")

    # ── Interlocks & forced reeds ─────────────────────────────────────────

    def test_kitchen_bench_interlock_panel_closed(self):
        cfg = minimal_cfg()
        world = WorldState(
            reeds=_default_reeds(open_names=["kitchen_bench"], closed_names=["kitchen_panel"]),
            phase="Evening",
        )
        self.assertTrue(effective_reed_closed(world, "kitchen_bench", cfg))
        out = desired_outputs(world, cfg)
        self.assertEqual(out.lights["kitchen_bench"][0], 0)
        self.assertEqual(out.light_sources["kitchen_bench"], "reed_closed")

    def test_kitchen_bench_open_when_panel_open(self):
        cfg = minimal_cfg()
        world = WorldState(
            reeds=_default_reeds(open_names=["kitchen_bench", "kitchen_panel"]),
            phase="Evening",
        )
        self.assertFalse(effective_reed_closed(world, "kitchen_bench", cfg))
        out = desired_outputs(world, cfg)
        self.assertEqual(out.lights["kitchen_bench"][0], 30)

    def test_force_panel_open_unblocks_bench_interlock(self):
        cfg = minimal_cfg()
        world = WorldState(
            reeds=_default_reeds(open_names=["kitchen_bench"], closed_names=["kitchen_panel"]),
            reed_forces={"kitchen_panel": False},
            phase="Evening",
        )
        self.assertFalse(effective_reed_closed(world, "kitchen_bench", cfg))
        out = desired_outputs(world, cfg)
        self.assertEqual(out.lights["kitchen_bench"][0], 30)

    def test_force_panel_closed_blocks_bench(self):
        cfg = minimal_cfg()
        world = WorldState(
            reeds=_default_reeds(open_names=["kitchen_bench", "kitchen_panel"]),
            reed_forces={"kitchen_panel": True},
            phase="Evening",
        )
        self.assertTrue(effective_reed_closed(world, "kitchen_bench", cfg))
        out = desired_outputs(world, cfg)
        self.assertEqual(out.lights["kitchen_bench"][0], 0)

    # ── Screens ───────────────────────────────────────────────────────────

    def test_screen_awake_when_panel_open(self):
        world = WorldState(reeds=_default_reeds(open_names=["kitchen_panel"]))
        self.assertTrue(resolve_screen("kitchen_panel", world, minimal_cfg()))

    def test_screen_asleep_when_panel_closed(self):
        world = WorldState(reeds=_default_reeds(closed_names=["kitchen_panel"]))
        self.assertFalse(resolve_screen("kitchen_panel", world, minimal_cfg()))

    def test_screen_follows_forced_panel_open(self):
        world = WorldState(
            reeds=_default_reeds(closed_names=["kitchen_panel"]),
            reed_forces={"kitchen_panel": False},
        )
        out = desired_outputs(world, minimal_cfg())
        self.assertTrue(out.screens["kitchen"])

    # ── Intent lifecycle ──────────────────────────────────────────────────

    def test_reed_close_clears_until_reed_close_intent_only(self):
        world = WorldStore(["rooftop_tent"], ["rooftop_tent", "accent"], [])
        world.set_light_to_reed_map({"rooftop_tent": "rooftop_tent"})
        world.set_light_intent("rooftop_tent", 50, expires="until_reed_close")
        world.set_light_intent("accent", 25, expires="until_phase_change")
        world.update_reeds({"rooftop_tent": True}, transition_closed=["rooftop_tent"])
        snap = world.snapshot()
        self.assertNotIn("rooftop_tent", snap.light_intents)
        self.assertIn("accent", snap.light_intents)

    def test_phase_change_clears_until_phase_change_only(self):
        world = WorldStore(["rooftop_tent"], ["rooftop_tent", "accent"], [])
        world.set_light_intent("rooftop_tent", 50, expires="until_reed_close")
        world.set_light_intent("accent", 25, expires="until_phase_change")
        world.set_phase("Night", invalidate=True)
        snap = world.snapshot()
        self.assertIn("rooftop_tent", snap.light_intents)
        self.assertNotIn("accent", snap.light_intents)

    def test_manual_intent_survives_phase_change(self):
        world = WorldStore(["rooftop_tent"], ["accent"], [])
        world.set_light_intent("accent", 60, expires="manual")
        world.set_phase("Night", invalidate=True)
        snap = world.snapshot()
        self.assertEqual(snap.light_intents["accent"].brightness, 60)

    def test_until_scene_clear_wiped_on_scene_activate(self):
        world = WorldStore([], ["accent"], [])
        world.set_light_intent("accent", 33, expires="until_scene_clear")
        world.set_active_scene("bedtime")
        snap = world.snapshot()
        self.assertNotIn("accent", snap.light_intents)

    def test_reed_reopen_after_intent_cleared_restores_automation(self):
        cfg = minimal_cfg()
        world = WorldStore(
            ["rooftop_tent", "kitchen_bench", "kitchen_panel", "rear_drawer"],
            cfg.light_names,
            [],
        )
        world.set_light_to_reed_map(cfg.light_to_reed)
        world.set_phase("Evening")
        world.set_light_intent("rooftop_tent", 0, expires="until_reed_close")
        world.update_reeds(
            _default_reeds(closed_names=["rooftop_tent"]),
            transition_closed=["rooftop_tent"],
        )
        self.assertNotIn("rooftop_tent", world.snapshot().light_intents)
        world.update_reeds(_default_reeds(open_names=["rooftop_tent"]))
        out = desired_outputs(world.snapshot(), cfg)
        self.assertEqual(out.lights["rooftop_tent"][0], 20)
        self.assertEqual(out.light_sources["rooftop_tent"], "automation_reed")

    def test_intent_brightness_clamped(self):
        world = WorldState(
            reeds=_default_reeds(open_names=["rooftop_tent"]),
            phase="Evening",
            light_intents={"rooftop_tent": LightIntent(150, expires="until_reed_close")},
        )
        out = desired_outputs(world, minimal_cfg())
        self.assertEqual(out.lights["rooftop_tent"][0], 100)

    def test_rooftop_safety_clamp(self):
        world = WorldState(
            reeds=_default_reeds(closed_names=["rooftop_tent"]),
            phase="Evening",
            light_intents={"rooftop_tent": LightIntent(50, expires="manual")},
        )
        resolved = resolve_light("rooftop_tent", world, minimal_cfg())
        self.assertEqual(resolved.brightness, 0)
        self.assertEqual(resolved.source, "safety_rooftop")

    def test_user_intent_overrides_reed_closed(self):
        world = WorldState(
            reeds=_default_reeds(closed_names=["kitchen_bench", "kitchen_panel"]),
            phase="Evening",
            light_intents={"kitchen_bench": LightIntent(39, expires="until_reed_close")},
        )
        resolved = resolve_light("kitchen_bench", world, minimal_cfg())
        self.assertEqual(resolved.brightness, 39)
        self.assertEqual(resolved.source, "user_intent")

    # ── Relays ────────────────────────────────────────────────────────────

    def test_relay_intent_overrides_observed(self):
        world = WorldState(
            observed_relays={"floodlights": False},
            relay_intents={"floodlights": RelayIntent(True)},
        )
        out = desired_outputs(world, minimal_cfg())
        self.assertTrue(out.relays["floodlights"])

    def test_relay_defaults_to_observed(self):
        world = WorldState(observed_relays={"floodlights": True})
        out = desired_outputs(world, minimal_cfg())
        self.assertTrue(out.relays["floodlights"])

    # ── Real pccs.conf smoke tests ────────────────────────────────────────

    def test_real_config_bedtime_scene(self):
        cfg = real_cfg()
        world = WorldState(
            reeds={name: False for name in cfg.reed_names},
            phase="Evening",
            active_scene="bedtime",
        )
        out = desired_outputs(world, cfg)
        self.assertEqual(out.lights["kitchen_panel"][0], 5)
        self.assertEqual(out.light_modes["kitchen_panel"], "white")
        self.assertEqual(out.lights["kitchen_bench"][0], 5)
        self.assertEqual(out.lights["storage_panel"][0], 5)
        self.assertEqual(out.lights["accent"][0], 5)
        self.assertEqual(out.lights["rooftop_tent"][0], 5)
        self.assertEqual(out.lights["ensuite"][0], 10)

    def test_real_config_ensuite_scene(self):
        cfg = real_cfg()
        world = WorldState(
            reeds={name: False for name in cfg.reed_names},
            phase="Evening",
            active_scene="ensuite",
        )
        out = desired_outputs(world, cfg)
        self.assertEqual(out.lights["ensuite"][0], 10)
        self.assertEqual(out.lights["rooftop_tent"][0], 2)
        self.assertEqual(out.lights["accent"][0], 5)

    def test_real_config_kitchen_screen_follows_panel(self):
        cfg = real_cfg()
        open_panel = WorldState(reeds={name: True for name in cfg.reed_names})
        open_panel.reeds["kitchen_panel"] = False
        closed_panel = WorldState(reeds={name: True for name in cfg.reed_names})
        out_open = desired_outputs(open_panel, cfg)
        out_closed = desired_outputs(closed_panel, cfg)
        self.assertTrue(out_open.screens["kitchen"])
        self.assertFalse(out_closed.screens["kitchen"])

    def test_bedtime_scene_leaves_undefined_lights_on_automation_source(self):
        world = WorldState(
            reeds=_default_reeds(open_names=["kitchen_panel", "rear_drawer"]),
            phase="Evening",
            active_scene="bedtime",
        )
        out = desired_outputs(world, minimal_cfg())
        self.assertEqual(out.light_sources["kitchen_panel"], "scene")
        self.assertEqual(out.light_sources["rear_drawer"], "automation_reed")


class SceneReconcileTests(unittest.TestCase):
    def test_scene_reconcile_only_commands_scene_lights(self):
        from engine.reconcile import Reconciler

        class TrackingArduino:
            def __init__(self):
                self.commanded = []

            def read_lights(self):
                return {"rear_drawer": 50, "kitchen_panel": 40}, {}

            def set_light(self, name, *args, **kwargs):
                self.commanded.append(name)

        class FakeRelays:
            def read_relays(self):
                return {}

            def set_relay(self, *args, **kwargs):
                pass

        cfg = minimal_cfg()
        world = WorldStore(cfg.reed_names, cfg.light_names, [])
        world.set_light_to_reed_map(cfg.light_to_reed)
        world.set_phase("Evening", invalidate=False)
        world.update_reeds(_default_reeds(open_names=list(cfg.reed_names)))
        world.update_observed_lights({"rear_drawer": 50, "kitchen_panel": 40, "accent": 0})

        arduino = TrackingArduino()
        rec = Reconciler(
            world=world,
            cfg=cfg,
            arduino_actuator=arduino,
            relay_actuator=FakeRelays(),
        )
        rec.reconcile(ramp_source="reed")
        arduino.commanded.clear()

        world.clear_all_light_intents()
        world.set_active_scene("bedtime")
        rec.reconcile(ramp_source="scene")

        self.assertIn("kitchen_panel", arduino.commanded)
        self.assertNotIn("rear_drawer", arduino.commanded)
        self.assertEqual(rec._last_desired.lights["rear_drawer"][0], 50)

    def test_all_off_scene_commands_every_light(self):
        from engine.reconcile import Reconciler

        class TrackingArduino:
            def __init__(self):
                self.commanded = []

            def read_lights(self):
                return {}, {}

            def set_light(self, name, *args, **kwargs):
                self.commanded.append(name)

        class FakeRelays:
            def read_relays(self):
                return {}

            def set_relay(self, *args, **kwargs):
                pass

        cfg = minimal_cfg()
        world = WorldStore(cfg.reed_names, cfg.light_names, [])
        world.set_light_to_reed_map(cfg.light_to_reed)
        world.set_phase("Evening", invalidate=False)
        world.update_reeds(_default_reeds(open_names=list(cfg.reed_names)))

        arduino = TrackingArduino()
        rec = Reconciler(
            world=world,
            cfg=cfg,
            arduino_actuator=arduino,
            relay_actuator=FakeRelays(),
        )
        world.set_active_scene("all_off")
        rec.reconcile(ramp_source="scene")

        self.assertEqual(set(arduino.commanded), set(cfg.light_names))

    def test_ui_reconcile_only_commands_intent_light(self):
        from engine.reconcile import Reconciler

        class TrackingArduino:
            def __init__(self):
                self.commanded = []

            def read_lights(self):
                return {"kitchen_panel": 5, "accent": 5}, {"kitchen_panel": "white"}

            def set_light(self, name, *args, **kwargs):
                self.commanded.append(name)

        class FakeRelays:
            def read_relays(self):
                return {}

            def set_relay(self, *args, **kwargs):
                pass

        cfg = minimal_cfg()
        world = WorldStore(cfg.reed_names, cfg.light_names, [])
        world.set_light_to_reed_map(cfg.light_to_reed)
        world.set_phase("Evening", invalidate=False)
        world.update_reeds(_default_reeds(open_names=list(cfg.reed_names)))
        world.update_observed_lights(
            {"kitchen_panel": 5, "accent": 5},
            {"kitchen_panel": "white"},
        )

        arduino = TrackingArduino()
        rec = Reconciler(
            world=world,
            cfg=cfg,
            arduino_actuator=arduino,
            relay_actuator=FakeRelays(),
        )

        world.set_active_scene("bedtime")
        rec.reconcile(ramp_source="scene")
        arduino.commanded.clear()

        world.set_light_intent("accent", 60)
        rec.reconcile(ramp_source="ui")

        self.assertEqual(arduino.commanded, ["accent"])
        self.assertEqual(rec._last_desired.lights["kitchen_panel"][0], 5)


if __name__ == "__main__":
    unittest.main()