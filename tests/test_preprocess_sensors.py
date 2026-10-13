"""센서 전처리 산출물의 불변 조건 검사 (산출물이 있다는 전제: 먼저 imaks_kg.preprocess.sensors 실행)."""
import csv
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW_CSV = ROOT / "imaks_data" / "sensors" / "timeseries_raw.csv"
LEGACY_OUT = ROOT / "preprocessed" / "sensors"
FINAL_OUT = ROOT / "preprocessed" / "final_v1"
OUT = LEGACY_OUT if (LEGACY_OUT / "input" / "ts_input.csv").exists() else FINAL_OUT
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
        if OUT == LEGACY_OUT:
            cls.input_path = OUT / "input" / "ts_input.csv"
            cls.time_path = OUT / "metadata" / "original_time_labels.csv"
            cls.threshold_path = OUT / "rules" / "sensor_thresholds.csv"
            cls.label_path = ROOT / "evaluation" / "row_labels.csv"
            cls.profile_path = OUT / "profile.json"
        else:
            cls.input_path = OUT / "inputs" / "sensors" / "timeseries_ml_input.csv"
            cls.time_path = OUT / "metadata" / "sensor_time_metadata.csv"
            cls.threshold_path = OUT / "inputs" / "sensors" / "timeseries_rule_input.csv"
            cls.label_path = OUT / "evaluation" / "row_labels.csv"
            cls.profile_path = OUT / "summary.json"
        cls.hdr, cls.data = rows(cls.input_path)
        cls.has_raw = RAW_CSV.exists()
        cls.raw_hdr, cls.raw = rows(RAW_CSV) if cls.has_raw else (cls.hdr, cls.data)

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
        if not self.has_raw:
            self.skipTest("raw dataset is not present in this checkout")
        ri = {c: self.raw_hdr.index(c) for c in self.raw_hdr}
        src = {(r[ri["sensor_id"]], r[ri["timestamp"]]): r[ri["value"]] for r in self.raw}
        i_s, i_t, i_v = (self.hdr.index(c) for c in ("sensor_id", "timestamp", "value"))
        self.assertTrue(all(src[(r[i_s], r[i_t])] == r[i_v] for r in self.data))

    def test_output_is_utf8_lf(self):
        b = self.input_path.read_bytes()
        if OUT == LEGACY_OUT:
            self.assertNotIn(b"\r", b)
        b.decode("utf-8")
        self.assertFalse(b.startswith(b"\xef\xbb\xbf"))

    def test_original_time_labels(self):
        h, d = rows(self.time_path)
        self.assertEqual(h[:5], ["sensor_id", "timestamp", "original_day", "original_shift", "original_batch_id"]
                         if OUT == LEGACY_OUT else ["sensor_id", "timestamp", "source_day", "source_shift", "source_batch_id"])
        self.assertEqual(len(d), 211_200)

    def test_thresholds_22_rows(self):
        h, d = rows(self.threshold_path)
        self.assertIn("sensor_id", h)
        self.assertIn("unit", h)
        sensor_idx = h.index("sensor_id")
        self.assertEqual(len({r[sensor_idx] for r in d}), 22)
        if OUT == LEGACY_OUT:
            self.assertEqual(h, ["sensor_id", "unit", "nominalValue", "warnLo", "warnHi", "critLo", "critHi"])
            self.assertEqual(len(d), 22)
        self.assertEqual(len({r[sensor_idx] for r in d}), 22)

    def test_label_file_is_in_evaluation_only(self):
        h, d = rows(self.label_path)
        self.assertEqual(len(d), 211_200)
        self.assertEqual(h[:2], ["sensor_id", "timestamp"])
        self.assertFalse(set(h[2:]) & set(ALLOW))
        label_cols = set(h[2:-1])  # 마지막은 원본 품질 컬럼
        for p in (ROOT / "preprocessed").rglob("*.csv"):
            if "evaluation" in p.parts or "audit" in p.parts:
                continue
            ph, _ = rows(p)
            self.assertFalse(label_cols & set(ph), p)

    def test_profile(self):
        p = json.loads(self.profile_path.read_text(encoding="utf-8"))
        if OUT == LEGACY_OUT:
            self.assertEqual((p["rows"], p["sensors"], p["timestamps"]), (211_200, 22, 9_600))
            self.assertEqual(p["duplicate_sensor_timestamp_keys"], 0)
            self.assertTrue(all(len(v) == 64 for v in p["output_sha256"].values()))
        else:
            s = p["sensor_summary"]
            self.assertEqual((s["rows"], s["sensors"], s["timestamp_count"]), (211_200, 22, 9_600))
            self.assertEqual(s["sampling_gaps"], 0)

    def test_write_into_raw_data_is_refused(self):
        sys.path.insert(0, str(ROOT / "src"))
        from imaks_kg.common.io_utils import write_text
        target = ROOT / "imaks_data" / "should_not_exist.txt"
        with self.assertRaises(PermissionError):
            write_text(target, "x")
        self.assertFalse(target.exists())


if __name__ == "__main__":
    unittest.main()
