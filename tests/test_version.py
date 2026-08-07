import pytest

from gorget.util.version import meets_minimum, rpm_version


@pytest.mark.parametrize(
    "npm_version, expected",
    [
        ("1.2.3", "1.2.3"),                       # plain release, unchanged
        ("4.17.21", "4.17.21"),
        ("1.2.3-rc.1", "1.2.3~rc.1"),             # semver prerelease -> ~
        ("14.0.0-alpha", "14.0.0~alpha"),
        ("2.0.0-beta.2.3", "2.0.0~beta.2.3"),
        ("1.0.0--beta", "1.0.0~beta"),            # leading junk in prerelease stripped
        ("1.2.3+build.5", "1.2.3"),               # build metadata dropped
        ("1.2.3-rc.1+build.5", "1.2.3~rc.1"),
        ("1..2.3", "1.2.3"),                      # collapsed repeated separators
    ],
)
def test_rpm_version(npm_version, expected):
    assert rpm_version(npm_version) == expected


def test_meets_minimum_equal():
    assert meets_minimum("2.17.5", "2.17.5") is True


def test_meets_minimum_greater():
    assert meets_minimum("2.17.6", "2.17.5") is True
    assert meets_minimum("2.18.0", "2.17.5") is True
    assert meets_minimum("3.0.0", "2.17.5") is True


def test_meets_minimum_less():
    assert meets_minimum("2.17.4", "2.17.5") is False
    assert meets_minimum("2.16.9", "2.17.5") is False
    assert meets_minimum("1.99.99", "2.17.5") is False


def test_meets_minimum_go_v_prefix():
    assert meets_minimum("v0.31.0", "0.31.0") is True
    assert meets_minimum("v0.30.9", "0.31.0") is False


def test_meets_minimum_different_component_counts():
    assert meets_minimum("2.17", "2.17.0") is True
    assert meets_minimum("2.17.0.1", "2.17.0") is True


def test_meets_minimum_strips_prerelease_suffix():
    # Pre-release ordering isn't modeled -- the base release is compared.
    assert meets_minimum("2.17.5-beta.1", "2.17.5") is True
    assert meets_minimum("2.17.4-beta.1", "2.17.5") is False


def test_meets_minimum_strips_build_metadata():
    assert meets_minimum("2.17.5+build123", "2.17.5") is True
