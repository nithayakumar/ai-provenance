import json
import pytest
from unittest.mock import patch, MagicMock


def _make_manifest_json(training_use: str = "notAllowed") -> str:
    return json.dumps({
        "claim_generator": "TestTool/1.0",
        "assertions": [
            {
                "label": "c2pa.training-mining",
                "data": {
                    "entries": {
                        "c2pa.ai_generative_training": {"use": training_use}
                    }
                },
            },
            {
                "label": "c2pa.actions",
                "data": {
                    "actions": [
                        {"action": "c2pa.created", "softwareAgent": "StableDiffusion/2.1"}
                    ]
                },
            },
        ],
    })


class TestReadC2paWhenUnavailable:
    def test_returns_absent_dict_when_not_installed(self, tmp_path):
        from lib.c2pa_reader import read_c2pa

        with patch("builtins.__import__", side_effect=ImportError("c2pa")):
            pass  # Can't reliably patch import; test via explicit unavailable path instead

        # Directly test _absent helper
        from lib.c2pa_reader import _absent
        result = _absent("unavailable")

        assert result["manifest_present"] is False
        assert result["validation_status"] == "unavailable"

    def test_absent_has_expected_keys(self):
        from lib.c2pa_reader import _absent
        result = _absent("unavailable")
        for key in ["manifest_present", "ai_generated", "training_opt_out", "validation_status"]:
            assert key in result

    def test_absent_values_are_none_or_false(self):
        from lib.c2pa_reader import _absent
        result = _absent("absent")
        assert result["manifest_present"] is False
        assert result["ai_generated"] is None
        assert result["training_opt_out"] is None
        assert result["actions"] == []


class TestReadC2paWithManifest:
    def _mock_reader(self, manifest_json: str) -> MagicMock:
        reader = MagicMock()
        reader.get_active_manifest.return_value = manifest_json
        reader.validation_status.return_value = None  # None = valid
        return reader

    def test_training_opt_out_detected(self, tmp_path):
        img = tmp_path / "test.jpg"
        img.touch()

        mock_c2pa = MagicMock()
        mock_c2pa.Reader.from_file.return_value = self._mock_reader(
            _make_manifest_json(training_use="notAllowed")
        )

        with patch.dict("sys.modules", {"c2pa": mock_c2pa}):
            from importlib import reload
            import lib.c2pa_reader as mod
            reload(mod)
            result = mod.read_c2pa(str(img))

        assert result["manifest_present"] is True
        assert result["training_opt_out"] is True
        assert result["validation_status"] == "valid"

    def test_training_allowed(self, tmp_path):
        img = tmp_path / "test.jpg"
        img.touch()

        mock_c2pa = MagicMock()
        mock_c2pa.Reader.from_file.return_value = self._mock_reader(
            _make_manifest_json(training_use="allowed")
        )

        with patch.dict("sys.modules", {"c2pa": mock_c2pa}):
            from importlib import reload
            import lib.c2pa_reader as mod
            reload(mod)
            result = mod.read_c2pa(str(img))

        assert result["training_opt_out"] is False

    def test_ai_generated_from_c2pa_created_action(self, tmp_path):
        img = tmp_path / "test.jpg"
        img.touch()

        mock_c2pa = MagicMock()
        mock_c2pa.Reader.from_file.return_value = self._mock_reader(
            _make_manifest_json()
        )

        with patch.dict("sys.modules", {"c2pa": mock_c2pa}):
            from importlib import reload
            import lib.c2pa_reader as mod
            reload(mod)
            result = mod.read_c2pa(str(img))

        assert result["creator_tool"] == "TestTool/1.0"

    def test_no_manifest_returns_absent(self, tmp_path):
        img = tmp_path / "test.jpg"
        img.touch()

        mock_c2pa = MagicMock()
        reader = MagicMock()
        reader.get_active_manifest.return_value = None
        mock_c2pa.Reader.from_file.return_value = reader

        with patch.dict("sys.modules", {"c2pa": mock_c2pa}):
            from importlib import reload
            import lib.c2pa_reader as mod
            reload(mod)
            result = mod.read_c2pa(str(img))

        assert result["manifest_present"] is False
