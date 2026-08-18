import subprocess
import sys
from pathlib import Path

HELPER_PATH = Path(__file__).parent / "helpers" / "dynamic_config_watcher_process.py"


def run_watcher_scenario(tmp_path, scenario):
    config_path = tmp_path / "dynamic-config.json"
    config_path.write_text(
        '{"service_discovery": "static", "routing_logic": "roundrobin"}'
    )
    return subprocess.run(
        [sys.executable, HELPER_PATH, scenario, config_path],
        capture_output=True,
        text=True,
        timeout=3,
    )


def test_watcher_does_not_keep_process_alive_when_not_closed(tmp_path):
    completed = run_watcher_scenario(tmp_path, "unclosed-watcher")

    assert completed.returncode == 0


def test_invalid_app_does_not_start_watcher(tmp_path):
    completed = run_watcher_scenario(tmp_path, "invalid-app")

    assert completed.returncode == 0
