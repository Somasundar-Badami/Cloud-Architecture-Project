"""
dataset_generator.py

Generates the synthetic drift dataset from the 20 approved scenarios in
scenario_definitions.py, using the REAL drift_engine.detect_drift() and
feature_extraction.extract_features() functions -- nothing here fabricates
a drift result or a feature value by hand.

For every (scenario, entity, variation) combination:
  1. Build a fresh desired_state via the scenario's baseline_fn (randomized
     secondary parameters -> meaningful variation across records)
  2. Build the actual_state via the scenario's mutate_fn (or an identical
     copy, for the E5 non-drift control)
  3. Run drift_engine.detect_drift(desired_state, actual_state)
  4. Run feature_extraction.extract_features(...) on that real drift result
  5. Attach the APPROVED risk_label from the scenario registry (ground
     truth, not derived here)

Reproducibility: a single random.Random(GLOBAL_SEED) instance is created
once and threaded through every baseline/mutation call in a fixed,
deterministic loop order. Re-running this script produces byte-identical
output every time.

Outputs (written to ../data/ relative to this file):
  - dataset.csv            flat ML feature table (Random-Forest-ready)
  - raw_records.json       full detail per record: desired_state,
                            actual_state, drift_result, features, risk_label
"""

import copy
import csv
import json
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import project_paths  # noqa: E402

from drift_engine import detect_drift  # noqa: E402
from feature_extraction import extract_features  # noqa: E402
from scenario_definitions import SCENARIO_REGISTRY  # noqa: E402

GLOBAL_SEED = 42

DATA_DIR = project_paths.PROCESSED_DATA_DIR
RAW_DIR = project_paths.RAW_DATA_DIR

# Synthetic, class-dependent drift_frequency ranges.
# Documented assumption (frozen spec Section 5): no real historical drift
# data exists, so this is a plausible-but-unverified placeholder --
# TO BE VERIFIED once real AWS Config history is available.
# Rationale for the ranges: severe misconfigurations (Critical) are modeled
# as rarer, one-off mistakes; routine/operational drift (Low) is modeled as
# more frequent.
DRIFT_FREQUENCY_RANGES = {
    "Critical": (0, 3),
    "High": (1, 5),
    "Medium": (2, 7),
    "Low": (3, 10),
}


def sample_drift_frequency(rng: random.Random, risk_label: str) -> int:
    low, high = DRIFT_FREQUENCY_RANGES[risk_label]
    return rng.randint(low, high)


def generate_records():
    """
    Returns a list of record dicts, each containing:
        record_id, scenario_id, group_id, resource_type,
        desired_state, actual_state, drift_result, features, risk_label
    """
    rng = random.Random(GLOBAL_SEED)
    records = []
    record_counter = 1

    for scenario in SCENARIO_REGISTRY:
        scenario_id = scenario["scenario_id"]
        resource_type = scenario["resource_type"]
        risk_label = scenario["risk_label"]
        n_entities = scenario["n_entities"]
        variations_per_entity = scenario["variations_per_entity"]
        baseline_fn = scenario["baseline_fn"]
        mutate_fn = scenario["mutate_fn"]

        for entity_id in range(1, n_entities + 1):
            for variation_idx in range(1, variations_per_entity + 1):
                # Fresh baseline draw per variation -> secondary parameters
                # (CIDR choices, retention days, KMS alias, etc.) differ
                # across variations even for the "same" entity, while the
                # entity's identity fields (bucket_name/instance_name/
                # entity_name, which are seeded by entity_id, not by rng)
                # stay stable -- this is what group_id relies on later.
                desired_state = baseline_fn(rng, entity_id)
                actual_state = mutate_fn(desired_state, rng)

                drift_result = detect_drift(desired_state, actual_state)
                drift_frequency = sample_drift_frequency(rng, risk_label)
                features = extract_features(resource_type, drift_result, drift_frequency)

                record_id = f"REC{record_counter:04d}"
                group_id = f"{scenario_id}::E{entity_id:03d}"

                records.append(
                    {
                        "record_id": record_id,
                        "scenario_id": scenario_id,
                        "group_id": group_id,
                        "resource_type": resource_type,
                        "desired_state": desired_state,
                        "actual_state": actual_state,
                        "drift_result": drift_result,
                        "features": features,
                        "risk_label": risk_label,
                    }
                )
                record_counter += 1

    return records


def write_raw_records_json(records, path):
    with open(path, "w") as f:
        json.dump(records, f, indent=2)


def write_dataset_csv(records, path):
    """
    Flat CSV suitable for Random Forest training in the next milestone.
    Only ML-relevant columns + identifiers -- no raw old_value/new_value,
    no nested desired_state/actual_state (those live in raw_records.json).
    """
    fieldnames = [
        "record_id",
        "scenario_id",
        "group_id",
        "resource_type",
        "changed_attribute",
        "security_sensitivity",
        "public_exposure",
        "encryption_change",
        "privilege_change",
        "port_exposure",
        "change_magnitude",
        "drift_frequency",
        "risk_label",
    ]
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in records:
            row = {
                "record_id": r["record_id"],
                "scenario_id": r["scenario_id"],
                "group_id": r["group_id"],
                "resource_type": r["features"]["resource_type"],
                "changed_attribute": r["features"]["changed_attribute"],
                "security_sensitivity": r["features"]["security_sensitivity"],
                "public_exposure": r["features"]["public_exposure"],
                "encryption_change": r["features"]["encryption_change"],
                "privilege_change": r["features"]["privilege_change"],
                "port_exposure": r["features"]["port_exposure"],
                "change_magnitude": r["features"]["change_magnitude"],
                "drift_frequency": r["features"]["drift_frequency"],
                "risk_label": r["risk_label"],
            }
            writer.writerow(row)


def main():
    os.makedirs(DATA_DIR, exist_ok=True)
    records = generate_records()

    csv_path = os.path.join(DATA_DIR, "dataset.csv")
    json_path = os.path.join(RAW_DIR, "raw_records.json")

    write_dataset_csv(records, csv_path)
    write_raw_records_json(records, json_path)

    print(f"Generated {len(records)} records")
    print(f"Wrote: {csv_path}")
    print(f"Wrote: {json_path}")

    return records


if __name__ == "__main__":
    main()
