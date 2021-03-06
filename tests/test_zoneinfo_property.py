import contextlib
import datetime
import os
import pickle
import unittest

import hypothesis
import pytest

from backports import zoneinfo

from . import _support as test_support
from ._support import ZoneInfoTestBase

try:
    from importlib import resources
except ImportError:
    import importlib_resources as resources


py_zoneinfo, c_zoneinfo = test_support.get_modules()

UTC = datetime.timezone.utc
MIN_UTC = datetime.datetime.min.replace(tzinfo=UTC)
MAX_UTC = datetime.datetime.max.replace(tzinfo=UTC)
ZERO = datetime.timedelta(0)


def _valid_keys():
    """Get available time zones, including posix/ and right/ directories."""
    available_zones = sorted(zoneinfo.available_timezones())
    TZPATH = zoneinfo.TZPATH

    def valid_key(key):
        for root in TZPATH:
            key_file = os.path.join(root, key)
            if os.path.exists(key_file):
                return True

        components = key.split("/")
        package_name = ".".join(["tzdata.zoneinfo"] + components[:-1])
        resource_name = components[-1]

        try:
            return resources.is_resource(package_name, resource_name)
        except ModuleNotFoundError:
            return False

    # This relies on the fact that dictionaries maintain insertion order — for
    # shrinking purposes, it is preferable to start with the standard version,
    # then move to the posix/ version, then to the right/ version.
    out_zones = {"": available_zones}
    for prefix in ["posix", "right"]:
        prefix_out = []
        for key in available_zones:
            prefix_key = f"{prefix}/{key}"
            if valid_key(prefix_key):
                prefix_out.append(prefix_key)

        out_zones[prefix] = prefix_out

    output = []
    for keys in out_zones.values():
        output.extend(keys)

    return output


VALID_KEYS = _valid_keys()
if not VALID_KEYS:
    pytest.skip("No time zone data available", allow_module_level=True)


def valid_keys():
    return hypothesis.strategies.sampled_from(VALID_KEYS)


class ZoneInfoTest(ZoneInfoTestBase):
    module = py_zoneinfo

    @hypothesis.given(key=valid_keys())
    def test_str(self, key):
        zi = self.klass(key)
        self.assertEqual(str(zi), key)

    @hypothesis.given(key=valid_keys())
    def test_key(self, key):
        zi = self.klass(key)

        self.assertEqual(zi.key, key)

    @hypothesis.given(
        dt=hypothesis.strategies.one_of(
            hypothesis.strategies.datetimes(), hypothesis.strategies.times()
        )
    )
    def test_utc(self, dt):
        zi = self.klass("UTC")
        dt_zi = dt.replace(tzinfo=zi)

        self.assertEqual(dt_zi.utcoffset(), ZERO)
        self.assertEqual(dt_zi.dst(), ZERO)
        self.assertEqual(dt_zi.tzname(), "UTC")


class CZoneInfoTest(ZoneInfoTest):
    module = c_zoneinfo


class ZoneInfoPickleTest(ZoneInfoTestBase):
    module = py_zoneinfo

    def setUp(self):
        with contextlib.ExitStack() as stack:
            stack.enter_context(test_support.set_zoneinfo_module(self.module))
            self.addCleanup(stack.pop_all().close)

        super().setUp()

    @hypothesis.given(key=valid_keys())
    def test_pickle_unpickle_cache(self, key):
        zi = self.klass(key)
        pkl_str = pickle.dumps(zi)
        zi_rt = pickle.loads(pkl_str)

        self.assertIs(zi, zi_rt)

    @hypothesis.given(key=valid_keys())
    def test_pickle_unpickle_no_cache(self, key):
        zi = self.klass.no_cache(key)
        pkl_str = pickle.dumps(zi)
        zi_rt = pickle.loads(pkl_str)

        self.assertIsNot(zi, zi_rt)
        self.assertEqual(str(zi), str(zi_rt))

    @hypothesis.given(key=valid_keys())
    def test_pickle_unpickle_cache_multiple_rounds(self, key):
        """Test that pickle/unpickle is idempotent."""
        zi_0 = self.klass(key)
        pkl_str_0 = pickle.dumps(zi_0)
        zi_1 = pickle.loads(pkl_str_0)
        pkl_str_1 = pickle.dumps(zi_1)
        zi_2 = pickle.loads(pkl_str_1)
        pkl_str_2 = pickle.dumps(zi_2)

        self.assertEqual(pkl_str_0, pkl_str_1)
        self.assertEqual(pkl_str_1, pkl_str_2)

        self.assertIs(zi_0, zi_1)
        self.assertIs(zi_0, zi_2)
        self.assertIs(zi_1, zi_2)

    @hypothesis.given(key=valid_keys())
    def test_pickle_unpickle_no_cache_multiple_rounds(self, key):
        """Test that pickle/unpickle is idempotent."""
        zi_cache = self.klass(key)

        zi_0 = self.klass.no_cache(key)
        pkl_str_0 = pickle.dumps(zi_0)
        zi_1 = pickle.loads(pkl_str_0)
        pkl_str_1 = pickle.dumps(zi_1)
        zi_2 = pickle.loads(pkl_str_1)
        pkl_str_2 = pickle.dumps(zi_2)

        self.assertEqual(pkl_str_0, pkl_str_1)
        self.assertEqual(pkl_str_1, pkl_str_2)

        self.assertIsNot(zi_0, zi_1)
        self.assertIsNot(zi_0, zi_2)
        self.assertIsNot(zi_1, zi_2)

        self.assertIsNot(zi_0, zi_cache)
        self.assertIsNot(zi_1, zi_cache)
        self.assertIsNot(zi_2, zi_cache)


class CZoneInfoPickleTest(ZoneInfoPickleTest):
    module = c_zoneinfo


class ZoneInfoCacheTest(ZoneInfoTestBase):
    module = py_zoneinfo

    @hypothesis.given(key=valid_keys())
    def test_cache(self, key):
        zi_0 = self.klass(key)
        zi_1 = self.klass(key)

        self.assertIs(zi_0, zi_1)

    @hypothesis.given(key=valid_keys())
    def test_no_cache(self, key):
        zi_0 = self.klass.no_cache(key)
        zi_1 = self.klass.no_cache(key)

        self.assertIsNot(zi_0, zi_1)


class CZoneInfoCacheTest(ZoneInfoCacheTest):
    klass = c_zoneinfo.ZoneInfo


class PythonCConsistencyTest(unittest.TestCase):
    """Tests that the C and Python versions do the same thing."""

    def _is_ambiguous(self, dt):
        return dt.replace(fold=not dt.fold).utcoffset() == dt.utcoffset()

    @hypothesis.given(dt=hypothesis.strategies.datetimes(), key=valid_keys())
    def test_same_str(self, dt, key):
        py_dt = dt.replace(tzinfo=py_zoneinfo.ZoneInfo(key))
        c_dt = dt.replace(tzinfo=c_zoneinfo.ZoneInfo(key))

        self.assertEqual(str(py_dt), str(c_dt))

    @hypothesis.given(dt=hypothesis.strategies.datetimes(), key=valid_keys())
    def test_same_offsets_and_names(self, dt, key):
        py_dt = dt.replace(tzinfo=py_zoneinfo.ZoneInfo(key))
        c_dt = dt.replace(tzinfo=c_zoneinfo.ZoneInfo(key))

        self.assertEqual(py_dt.tzname(), c_dt.tzname())
        self.assertEqual(py_dt.utcoffset(), c_dt.utcoffset())
        self.assertEqual(py_dt.dst(), c_dt.dst())

    @hypothesis.given(
        dt=hypothesis.strategies.datetimes(
            timezones=hypothesis.strategies.just(UTC)
        ),
        key=valid_keys(),
    )
    @hypothesis.example(dt=MIN_UTC, key="Asia/Tokyo")
    @hypothesis.example(dt=MAX_UTC, key="Asia/Tokyo")
    @hypothesis.example(dt=MIN_UTC, key="America/New_York")
    @hypothesis.example(dt=MAX_UTC, key="America/New_York")
    @hypothesis.example(
        dt=datetime.datetime(2006, 10, 29, 5, 15, tzinfo=UTC),
        key="America/New_York",
    )
    def test_same_from_utc(self, dt, key):
        py_zi = py_zoneinfo.ZoneInfo(key)
        c_zi = c_zoneinfo.ZoneInfo(key)

        # Convert to UTC: This can overflow, but we just care about consistency
        py_overflow_exc = None
        c_overflow_exc = None
        try:
            py_dt = dt.astimezone(py_zi)
        except OverflowError as e:
            py_overflow_exc = e

        try:
            c_dt = dt.astimezone(c_zi)
        except OverflowError as e:
            c_overflow_exc = e

        if (py_overflow_exc is not None) != (c_overflow_exc is not None):
            raise py_overflow_exc or c_overflow_exc  # pragma: nocover

        if py_overflow_exc is not None:
            return  # Consistently raises the same exception

        # PEP 495 says that an inter-zone comparison between ambiguous
        # datetimes is always False.
        if py_dt != c_dt:
            self.assertEqual(
                self._is_ambiguous(py_dt),
                self._is_ambiguous(c_dt),
                (py_dt, c_dt),
            )

        self.assertEqual(py_dt.tzname(), c_dt.tzname())
        self.assertEqual(py_dt.utcoffset(), c_dt.utcoffset())
        self.assertEqual(py_dt.dst(), c_dt.dst())

    @hypothesis.given(dt=hypothesis.strategies.datetimes(), key=valid_keys())
    @hypothesis.example(dt=datetime.datetime.max, key="America/New_York")
    @hypothesis.example(dt=datetime.datetime.min, key="America/New_York")
    @hypothesis.example(dt=datetime.datetime.min, key="Asia/Tokyo")
    @hypothesis.example(dt=datetime.datetime.max, key="Asia/Tokyo")
    def test_same_to_utc(self, dt, key):
        py_dt = dt.replace(tzinfo=py_zoneinfo.ZoneInfo(key))
        c_dt = dt.replace(tzinfo=c_zoneinfo.ZoneInfo(key))

        # Convert from UTC: Overflow OK if it happens in both implementations
        py_overflow_exc = None
        c_overflow_exc = None
        try:
            py_utc = py_dt.astimezone(UTC)
        except OverflowError as e:
            py_overflow_exc = e

        try:
            c_utc = c_dt.astimezone(UTC)
        except OverflowError as e:
            c_overflow_exc = e

        if (py_overflow_exc is not None) != (c_overflow_exc is not None):
            raise py_overflow_exc or c_overflow_exc  # pragma: nocover

        if py_overflow_exc is not None:
            return  # Consistently raises the same exception

        self.assertEqual(py_utc, c_utc)

    @hypothesis.given(key=valid_keys())
    def test_cross_module_pickle(self, key):
        py_zi = py_zoneinfo.ZoneInfo(key)
        c_zi = c_zoneinfo.ZoneInfo(key)

        with test_support.set_zoneinfo_module(py_zoneinfo):
            py_pkl = pickle.dumps(py_zi)

        with test_support.set_zoneinfo_module(c_zoneinfo):
            c_pkl = pickle.dumps(c_zi)

        with test_support.set_zoneinfo_module(c_zoneinfo):
            # Python → C
            py_to_c_zi = pickle.loads(py_pkl)
            self.assertIs(py_to_c_zi, c_zi)

        with test_support.set_zoneinfo_module(py_zoneinfo):
            # C → Python
            c_to_py_zi = pickle.loads(c_pkl)
            self.assertIs(c_to_py_zi, py_zi)
