"""
build_expanded_dataset.py -- generates the EXPANDED dataset (original 20 + 17
proposed scenarios) into dataset_v2/. The approved dataset/ folder is not touched.

    python src/backend/build_expanded_dataset.py
"""
import os, sys, csv
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import project_paths  # noqa: F401,E402

import expansion_scenarios  # noqa: E402
expansion_scenarios.install()

import dataset_generator as dg  # noqa: E402
import validate_dataset as vd  # noqa: E402

OUT = os.path.join(project_paths.ROOT_DIR, "dataset_v2")


def main():
    os.makedirs(os.path.join(OUT, "raw"), exist_ok=True)
    os.makedirs(os.path.join(OUT, "processed"), exist_ok=True)
    records = dg.generate_records()
    dg.write_dataset_csv(records, os.path.join(OUT, "processed", "dataset.csv"))
    dg.write_raw_records_json(records, os.path.join(OUT, "raw", "raw_records.json"))
    print(f"Generated {len(records)} records -> {OUT}")
    return records


if __name__ == "__main__":
    main()
