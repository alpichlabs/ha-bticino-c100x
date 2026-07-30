"""Native helper safety-contract tests without loading Liblinphone."""

import base64
import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest


def load_helper():
    sys.modules.setdefault("linphone", MagicMock())
    path = Path(__file__).parents[1] / "runtime" / "helper.py"
    spec = importlib.util.spec_from_file_location("c100x_runtime_helper", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_monitoring_parameters_are_rejected_on_any_drift(tmp_path) -> None:
    helper = load_helper()
    request = {
        "target": "c100x",
        "video_direction": "recv_only",
        "audio_direction": "send_recv",
        "media_encryption": "srtp",
        "media_encryption_mandatory": True,
        "microphone_enabled": False,
        "setup_timeout": 15,
        "no_media_timeout": 10,
        "device_address": "eu-uuid",
    }
    helper.Runtime._validate_monitoring(request)
    request["video_direction"] = "send_recv"
    with pytest.raises(ValueError, match="invalid monitoring"):
        helper.Runtime._validate_monitoring(request)


def test_pcm_is_accepted_only_when_enabled_and_queue_is_bounded(tmp_path) -> None:
    helper = load_helper()
    runtime = helper.Runtime(tmp_path / "runtime.sock")
    frame = base64.b64encode(bytes(1920)).decode()
    with pytest.raises(RuntimeError, match="disabled"):
        runtime.command_microphone_frame({"pcm": frame})

    runtime.microphone_enabled = True
    runtime.media_started = True
    for _ in range(20):
        runtime.command_microphone_frame({"pcm": frame})
    assert len(runtime.microphone_queue) == 10
    assert len(runtime._wav_header()) == 44
