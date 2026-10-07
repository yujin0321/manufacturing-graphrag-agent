"""센서 전처리 산출물의 불변 조건 검사 (산출물이 있다는 전제: 먼저 imaks_kg.preprocess.sensors 실행)."""
import csv
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW_CSV = ROOT / "imaks_data" / "sensors" / "timeseries_raw.csv"
OUT = ROOT / "preprocessed" / "sensors"
ALLOW = ["timestamp", "zone", "station_id", "sensor_id", "sensor_type", "value", "unit"]


def rows(path):
    with Path(path).open(encoding="utf-8-sig", newline="") as f:
        r = csv.reader(f)
        header = next(r)
        return header, list(r)


def words(path):
    return [l.strip().lower() for l in Path(path).read_text(encoding="utf-8").splitlines()
            if l.strip() and not l.startswith("#")]


class SensorOutputs(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.hdr, cls.data = rows(OUT / "input" / "ts_input.csv")
        cls.raw_hdr, cls.raw = rows(RAW_CSV)

    def test_header_exactly_allowlist(self):
        self.assertEqual(self.hdr, ALLOW)

    def test_header_has_no_forbidden_words(self):
        banned = set(words(ROOT / "harness" / "forbidden_columns.txt")) | \
            set(words(ROOT / "harness" / "forbidden_columns_header_only.txt"))
        self.assertFalse({h.lower() for h in self.hdr} & banned)

    def test_counts(self):
        i = {c: self.hdr.index(c) for c in ALLOW}
        self.assertEqual(len(self.data), 211_200)
        self.assertEqual(len({r[i["sensor_id"]] for r in self.data}), 22)
        self.assertEqual(len({r[i["timestamp"]] for r in self.data}), 9_600)

    def test_no_duplicate_keys_and_sorted(self):
        i_s, i_t = self.hdr.index("sensor_id"), self.hdr.index("timestamp")
        keys = [(r[i_s], r[i_t]) for r in self.data]
        self.assertEqual(len(set(keys)), len(keys))
        self.assertEqual(keys, sorted(keys))

    def test_value_strings_identical_to_source(self):
        ri = {c: self.raw_hdr.index(c) for c in self.raw_hdr}
        src = {(r[ri["sensor_id"]], r[ri["timestamp"]]): r[ri["value"]] for r in self.raw}
        i_s, i_t, i_v = (self.hdr.index(c) for c in ("sensor_id", "timestamp", "value"))
        self.assertTrue(all(src[(r[i_s], r[i_t])] == r[i_v] for r in self.data))

    def test_output_is_utf8_lf(self):
        b = (OUT / "input" / "ts_input.csv").read_bytes()
        self.assertNotIn(b"\r", b)
        b.decode("utf-8")
        self.assertFalse(b.startswith(b"\xef\xbb\xbf"))

    def test_original_time_labels(self):
        h, d = rows(OUT / "metadata" / "original_time_labels.csv")
        self.assertEqual(h, ["sensor_id", "timestamp", "original_day", "original_shift", "original_batch_id"])
        self.assertEqual(len(d), 211_200)

    def test_thresholds_22_rows(self):
        h, d = rows(OUT / "rules" / "sensor_thresholds.csv")
        self.assertEqual(h, ["sensor_id", "unit", "nominalValue", "warnLo", "warnHi", "critLo", "critHi"])
        self.assertEqual(len(d), 22)
        self.assertEqual(len({r[0] for r in d}), 22)

    def test_label_file_is_in_evaluation_only(self):
        h, d = rows(ROOT / "evaluation" / "row_labels.csv")
        self.assertEqual(len(d), 211_200)
        self.assertEqual(h[:2], ["sensor_id", "timestamp"])
        self.assertFalse(set(h[2:]) & set(ALLOW))
        label_cols = set(h[2:-1])  # 마지막은 원본 품질 컬럼
        for p in (ROOT / "preprocessed").rglob("*.csv"):
            ph, _ = rows(p)
            self.assertFalse(label_cols & set(ph), p)

    def test_profile(self):
        p = json.loads((OUT / "profile.json").read_text(encoding="utf-8"))
        self.assertEqual((p["rows"], p["sensors"], p["timestamps"]), (211_200, 22, 9_600))
        self.assertEqual(p["duplicate_sensor_timestamp_keys"], 0)
        self.assertTrue(all(len(v) == 64 for v in p["output_sha256"].values()))

    def test_write_into_raw_data_is_refused(self):
        sys.path.insert(0, str(ROOT / "src"))
        from imaks_kg.common.io_utils import write_text
        target = ROOT / "imaks_data" / "should_not_exist.txt"
        with self.assertRaises(PermissionError):
            write_text(target, "x")
        self.assertFalse(target.exists())


if __name__ == "__main__":
    unittest.main()
