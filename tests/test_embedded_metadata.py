import json
import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path


class TestExtractAiTrainingSignals:
    def test_empty_input_returns_dict(self):
        from lib.embedded_metadata import extract_ai_training_signals
        result = extract_ai_training_signals({})
        assert isinstance(result, dict)

    def test_dc_creator_mapped_to_author(self):
        from lib.embedded_metadata import extract_ai_training_signals
        # XMP keys use underscored names (dc_creator not dc:creator)
        embedded = {"xmp": {"dc_creator": "Jane Doe"}}
        result = extract_ai_training_signals(embedded)
        assert result.get("author") == "Jane Doe"

    def test_iptc_by_line_fallback_for_author(self):
        from lib.embedded_metadata import extract_ai_training_signals
        embedded = {"iptc": {"iptc_by_line": "John Smith"}}
        result = extract_ai_training_signals(embedded)
        assert result.get("author") == "John Smith"

    def test_xmp_rights_web_stmt_is_license_url(self):
        from lib.embedded_metadata import extract_ai_training_signals
        url = "https://creativecommons.org/licenses/by/4.0/"
        embedded = {"xmp": {"xmp_rights_web_stmt": url}}
        result = extract_ai_training_signals(embedded)
        assert result.get("license_url") == url

    def test_plus_data_mining_opt_out(self):
        from lib.embedded_metadata import extract_ai_training_signals
        embedded = {"xmp": {"plus_data_mining": "DMI-PROHIBITED"}}
        result = extract_ai_training_signals(embedded)
        assert result.get("iptc_opt_out") is True

    def test_plus_data_mining_allowed(self):
        from lib.embedded_metadata import extract_ai_training_signals
        embedded = {"xmp": {"plus_data_mining": "DMI-ALLOWED"}}
        result = extract_ai_training_signals(embedded)
        assert result.get("iptc_opt_out") is False

    def test_digital_source_type_ai_marks_generated(self):
        from lib.embedded_metadata import extract_ai_training_signals
        embedded = {"xmp": {"iptc_digital_source_type": "trainedAlgorithmicMedia"}}
        result = extract_ai_training_signals(embedded)
        assert result.get("is_ai_generated") is True

    def test_digital_source_type_photo_marks_not_generated(self):
        from lib.embedded_metadata import extract_ai_training_signals
        embedded = {"xmp": {"iptc_digital_source_type": "digitally_captured"}}
        result = extract_ai_training_signals(embedded)
        assert result.get("is_ai_generated") is False

    def test_result_has_all_expected_keys(self):
        from lib.embedded_metadata import extract_ai_training_signals
        result = extract_ai_training_signals({})
        for key in ["author", "copyright", "license_url", "iptc_opt_out", "is_ai_generated"]:
            assert key in result


class TestReadXmpFallback:
    def test_falls_back_to_exiftool_when_libxmp_missing(self, tmp_path):
        img = tmp_path / "test.jpg"
        img.touch()

        exiftool_output = json.dumps([{
            "Creator": "Test Author",
            "WebStatement": "https://creativecommons.org/licenses/by/4.0/",
        }])
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = exiftool_output

        # Simulate libxmp not installed by making _read_xmp_via_toolkit raise ImportError
        import lib.embedded_metadata as mod
        with (
            patch.object(mod, "_read_xmp_via_toolkit", side_effect=ImportError("no libxmp")),
            patch("subprocess.run", return_value=mock_proc),
        ):
            result = mod.read_xmp(str(img))

        assert isinstance(result, dict)
        assert result.get("dc_creator") == "Test Author"

    def test_read_xmp_returns_empty_on_all_failures(self, tmp_path):
        img = tmp_path / "test.jpg"
        img.touch()

        import lib.embedded_metadata as mod
        with (
            patch.object(mod, "_read_xmp_via_toolkit", side_effect=ImportError("no libxmp")),
            patch("subprocess.run", side_effect=Exception("exiftool not found")),
        ):
            result = mod.read_xmp(str(img))

        assert result == {}
