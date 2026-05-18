import pytest
from lib.license_spdx import to_spdx


class TestToSpdxFromUrl:
    def test_cc0_url(self):
        assert to_spdx(license_url="https://creativecommons.org/publicdomain/zero/1.0/") == "CC0-1.0"

    def test_cc_by_url(self):
        assert to_spdx(license_url="https://creativecommons.org/licenses/by/4.0/") == "CC-BY-4.0"

    def test_cc_by_sa_url(self):
        assert to_spdx(license_url="https://creativecommons.org/licenses/by-sa/4.0/") == "CC-BY-SA-4.0"

    def test_cc_by_nc_url(self):
        assert to_spdx(license_url="https://creativecommons.org/licenses/by-nc/4.0/") == "CC-BY-NC-4.0"

    def test_cc_by_nc_sa_url(self):
        assert to_spdx(license_url="https://creativecommons.org/licenses/by-nc-sa/4.0/") == "CC-BY-NC-SA-4.0"

    def test_cc_by_nc_nd_url(self):
        assert to_spdx(license_url="https://creativecommons.org/licenses/by-nc-nd/4.0/") == "CC-BY-NC-ND-4.0"

    def test_cc_by_nd_url(self):
        assert to_spdx(license_url="https://creativecommons.org/licenses/by-nd/4.0/") == "CC-BY-ND-4.0"

    def test_unsplash_url(self):
        assert to_spdx(license_url="https://unsplash.com/license") == "LicenseRef-Unsplash"

    def test_pexels_url(self):
        assert to_spdx(license_url="https://www.pexels.com/license/") == "LicenseRef-Pexels"

    def test_version_downgrade_3_0(self):
        result = to_spdx(license_url="https://creativecommons.org/licenses/by/3.0/")
        assert result == "CC-BY-3.0"

    def test_version_downgrade_2_0(self):
        result = to_spdx(license_url="https://creativecommons.org/licenses/by-sa/2.0/")
        assert result == "CC-BY-SA-2.0"


class TestToSpdxFromText:
    def test_cc0_text(self):
        assert to_spdx(license_text="CC0 1.0 Universal") == "CC0-1.0"

    def test_public_domain_text(self):
        assert to_spdx(license_text="Public Domain") == "CC0-1.0"

    def test_cc_by_text(self):
        assert to_spdx(license_text="CC BY 4.0") == "CC-BY-4.0"

    def test_creative_commons_attribution(self):
        assert to_spdx(license_text="Creative Commons Attribution 4.0") == "CC-BY-4.0"

    def test_cc_by_nc_nd_text(self):
        assert to_spdx(license_text="CC BY-NC-ND") == "CC-BY-NC-ND-4.0"

    def test_all_rights_reserved(self):
        assert to_spdx(license_text="All Rights Reserved") == "LicenseRef-AllRightsReserved"

    def test_unsplash_license_text(self):
        assert to_spdx(license_text="Unsplash License") == "LicenseRef-Unsplash"

    def test_pexels_license_text(self):
        assert to_spdx(license_text="Pexels License") == "LicenseRef-Pexels"


class TestToSpdxPriority:
    def test_url_takes_priority_over_text(self):
        # URL says CC0, text says CC-BY — URL wins
        result = to_spdx(
            license_text="CC BY 4.0",
            license_url="https://creativecommons.org/publicdomain/zero/1.0/",
        )
        assert result == "CC0-1.0"


class TestToSpdxNoMatch:
    def test_none_inputs(self):
        assert to_spdx() is None

    def test_unrecognised_text(self):
        assert to_spdx(license_text="Proprietary XYZ License v9") is None

    def test_unrecognised_url(self):
        assert to_spdx(license_url="https://example.com/some-custom-license") is None

    def test_empty_strings(self):
        assert to_spdx(license_text="", license_url="") is None
