"""Pruebas sin hardware: no se importa Bleak real ni se ejecuta launchctl."""
import argparse
import asyncio
from datetime import datetime
import json
import os
from pathlib import Path
import plistlib
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
import uuid

import hue
from hue_config import load_config, schedule_date, validate
import manage


class ProjectTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="hue tests with spaces ")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        # UUID sintético nuevo en cada prueba, nunca un dispositivo real.
        self.config = validate({"address": str(uuid.uuid4())})

    def installation(self, config):
        app, runtime, _ = manage.locations(self.root)
        (app / "Contents/MacOS").mkdir(parents=True)
        (app / "Contents/MacOS/HueHorario").touch()
        (runtime / ".venv/bin").mkdir(parents=True)
        (runtime / ".venv/bin/python").touch()
        (runtime / "config.json").write_text(json.dumps(config))
        return runtime

    def test_example_and_incomplete_configs_block_activation(self):
        examples = [json.loads(Path("config.example.json").read_text()), {},
                    {"address": ""}, {"address": "not-a-corebluetooth-uuid"},
                    dict(self.config, hour=24), dict(self.config, minute=True),
                    dict(self.config, timezone="UTC")]
        runtime = self.installation(examples[0])
        for config in examples:
            with self.subTest(config=config):
                (runtime / "config.json").write_text(json.dumps(config))
                with patch.object(manage, "loaded", return_value=False), patch.object(manage.subprocess, "run") as run:
                    with self.assertRaises(ValueError):
                        manage.enable(self.root)
                    run.assert_not_called()
                self.assertFalse(manage.locations(self.root)[2].exists())

    def test_schedule_boundaries_and_midnight(self):
        for value, expected in [("18:59:59", False), ("19:00:00", True),
                                ("19:14:59", True), ("19:15:00", False)]:
            self.assertEqual(bool(schedule_date(datetime.fromisoformat("2030-01-02T" + value), self.config)), expected)
        config = dict(self.config, hour=23, minute=55)
        self.assertEqual(schedule_date(datetime(2030, 1, 3, 0, 5), config), "2030-01-02")
        self.assertIsNone(schedule_date(datetime(2030, 1, 3, 0, 10), config))

    def test_system_timezone_is_used(self):
        original = os.environ.get("TZ")
        try:
            for zone in ["UTC", "America/Argentina/Buenos_Aires", "Asia/Tokyo"]:
                os.environ["TZ"] = zone
                time.tzset()
                now = datetime(2030, 1, 2, 19, 5).astimezone()
                self.assertEqual(schedule_date(now, self.config), "2030-01-02")
        finally:
            if original is None:
                os.environ.pop("TZ", None)
            else:
                os.environ["TZ"] = original
            time.tzset()

    def test_generated_paths_and_custom_time(self):
        self.installation(dict(self.config, hour=20, minute=30))
        data = plistlib.loads(manage.generate(self.root).read_bytes())
        app, runtime, _ = manage.locations(self.root)
        self.assertEqual(data["ProgramArguments"], ["/usr/bin/open", "-n", "-g", "-W", str(app), "--args", "scheduled"])
        self.assertEqual(data["StartCalendarInterval"], {"Hour": 20, "Minute": 30})
        self.assertEqual(data["StandardOutPath"], str(runtime / "launchd.log"))
        self.assertNotIn("RunAtLoad", data)
        self.assertNotIn("KeepAlive", data)

    def test_existing_installation_is_not_overwritten(self):
        runtime = self.installation(self.config)
        before = (runtime / "config.json").read_bytes()
        with patch.object(manage.subprocess, "run") as run:
            with self.assertRaises(ValueError):
                manage.prepare(self.root)
            run.assert_not_called()
        self.assertEqual(before, (runtime / "config.json").read_bytes())

    def test_loaded_installation_cannot_be_replaced(self):
        with patch.object(manage, "loaded", return_value=True), patch.object(manage.subprocess, "run") as run:
            with self.assertRaises(ValueError):
                manage.prepare(Path.home().resolve(), replace=True)
            run.assert_not_called()

    def test_alternative_root_cannot_activate(self):
        with patch("sys.argv", ["manage.py", "enable", "--root", str(self.root)]), patch.object(manage, "enable") as enable:
            with self.assertRaises(SystemExit):
                manage.main()
            enable.assert_not_called()

    def test_unrelated_agent_is_rejected(self):
        _, _, agent = manage.locations(self.root)
        agent.parent.mkdir(parents=True)
        agent.write_bytes(plistlib.dumps({"Label": "another-project"}))
        with patch.object(manage.subprocess, "run") as run:
            with self.assertRaises(ValueError):
                manage.disable(self.root)
            run.assert_not_called()

    def run_scheduled(self, state, control, now):
        with patch.object(hue, "datetime") as clock, patch.object(hue, "control", control), patch.object(hue.asyncio, "sleep", new_callable=AsyncMock):
            clock.now.return_value.astimezone.return_value = now
            asyncio.run(hue.run_control(self.config["address"], self.config, True, state, "scheduled"))

    def test_confirmation_prevents_duplicate_and_late_runs(self):
        state = self.root / "last-success.json"
        control = AsyncMock(return_value={"power": "01"})
        self.run_scheduled(state, control, datetime(2030, 1, 2, 19, 0))
        self.run_scheduled(state, control, datetime(2030, 1, 2, 19, 1))
        self.run_scheduled(state, control, datetime(2030, 1, 3, 20, 0))
        self.assertEqual(control.await_count, 1)
        self.assertEqual(json.loads(state.read_text()), {"date": "2030-01-02"})

    def test_failures_are_bounded_and_do_not_record_success(self):
        state = self.root / "last-success.json"
        control = AsyncMock(side_effect=RuntimeError("Simulated connection failure"))
        with self.assertRaises(RuntimeError):
            self.run_scheduled(state, control, datetime(2030, 1, 2, 19, 0))
        self.assertEqual(control.await_count, 3)
        self.assertFalse(state.exists())

    def test_lock_prevents_concurrent_commands(self):
        import fcntl
        config = self.root / "config.json"
        config.write_text(json.dumps(self.config))
        with (self.root / "last-success.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with patch.object(hue, "__file__", str(self.root / "hue.py")), patch.object(hue, "run_control", new_callable=AsyncMock) as run:
                asyncio.run(hue.main(argparse.Namespace(command="scheduled", config=str(config), address=None)))
                run.assert_not_called()

    def fake_client(self, model=b"LCT026", after=b"\x01"):
        client = AsyncMock()
        client.read_gatt_char.side_effect = [model, b"\x00", after, b"\x72"]
        context = AsyncMock()
        context.__aenter__.return_value = client
        return client, SimpleNamespace(BleakClient=MagicMock(return_value=context))

    def test_only_power_is_written_and_read_back(self):
        client, module = self.fake_client()
        with patch.dict("sys.modules", bleak=module):
            result = asyncio.run(hue.control(self.config["address"], turn_on=True))
        client.write_gatt_char.assert_awaited_once_with(hue.POWER, b"\x01", response=True)
        self.assertEqual(result["power"], "01")
        self.assertEqual(result["brightness_raw"], "72")

    def test_wrong_model_never_writes(self):
        client, module = self.fake_client(model=b"unsupported")
        with patch.dict("sys.modules", bleak=module), self.assertRaises(RuntimeError):
            asyncio.run(hue.control(self.config["address"], turn_on=True))
        client.write_gatt_char.assert_not_called()

    def test_status_never_writes(self):
        client, module = self.fake_client()
        with patch.dict("sys.modules", bleak=module):
            asyncio.run(hue.control(self.config["address"]))
        client.write_gatt_char.assert_not_called()

    def test_failed_confirmation_is_an_error(self):
        _, module = self.fake_client(after=b"\x00")
        with patch.dict("sys.modules", bleak=module), self.assertRaises(RuntimeError):
            asyncio.run(hue.control(self.config["address"], turn_on=True))

    def test_window_is_rechecked_before_write(self):
        client, module = self.fake_client()
        with patch.dict("sys.modules", bleak=module), patch.object(hue, "schedule_date", return_value=None), self.assertRaises(RuntimeError):
            asyncio.run(hue.control(self.config["address"], turn_on=True, config=self.config))
        client.write_gatt_char.assert_not_called()


if __name__ == "__main__":
    unittest.main()
