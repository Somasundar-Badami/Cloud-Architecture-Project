# AI-Based Infrastructure Drift Detection Framework — Dataset Generation Milestone

Synthetic dataset generator + drift detection engine + feature extraction
pipeline for the drift-risk classification project, built per the frozen
implementation specification.

## Project Structure

```
drift-detection-framework/
├── README.md
├── requirements.txt
├── validate_dataset.py          # standalone validation script (run after generation)
├── src/
│   ├── drift_engine.py          # generic desired-vs-actual JSON diff engine
│   ├── feature_extraction.py    # converts drift_engine output -> approved ML features
│   ├── scenario_definitions.py  # 20 approved scenarios: baselines + mutations
│   └── dataset_generator.py     # orchestrates generation, writes CSV + JSON
├── data/
│   ├── dataset.csv                     # flat ML feature table (711 records)
│   ├── raw_records.json                # full detail per record (states + drift + features)
│   └── dataset_validation_report.json  # validation results
└── tests/
    ├── test_drift_engine.py         # 11 tests
    ├── test_feature_extraction.py   # 13 tests
    └── test_dataset_generator.py    # 21 tests
```

## File-by-file explanation

- **`src/drift_engine.py`** — Generic recursive diff between a `desired`
  and `actual` dict. Recurses into nested dicts, compares lists/scalars by
  equality, reports each change as `{attribute, old_value, new_value}`.
  Knows nothing about AWS, scenarios, or risk — fully reusable.

- **`src/feature_extraction.py`** — Converts `drift_engine` output into the
  9 approved ML features. Uses a per-attribute "knowledge base" of rule
  functions that inspect `old_value`/`new_value` internally (to decide
  direction, e.g. did a CIDR *become* `0.0.0.0/0`?) but never store those
  raw values in the returned feature dict.

- **`src/scenario_definitions.py`** — The 20 approved drift scenarios (7
  S3, 7 EC2 Security Group including the E5 non-drift control, 6 IAM),
  each as a baseline-state generator + a mutation function, tagged with
  its approved ground-truth `risk_label`.

- **`src/risk_rule_check.py`** — An independent, simplified re-implementation
  of the Section 3 severity rules, used **only** to cross-check the approved
  labels during validation — not the source of truth for `risk_label`.

- **`src/dataset_generator.py`** — Runs every (scenario × entity × variation)
  combination through the *real* `detect_drift()` and `extract_features()`
  functions, and writes `data/dataset.csv` + `data/raw_records.json`.

- **`validate_dataset.py`** — Reads the generated data back and runs all
  required validation checks, writing `data/dataset_validation_report.json`
  and printing a summary.

- **`tests/`** — 45 pytest tests total across all three modules.

## How to run (Ubuntu or Windows)

```bash
# 1. Create and activate a virtual environment (recommended)
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Generate the dataset
cd src
python3 dataset_generator.py
cd ..

# 4. Validate the generated dataset
python3 validate_dataset.py

# 5. Run all tests
python3 -m pytest tests/ -v
```

On Windows, replace `python3` with `python` if `python3` isn't on your PATH.

## Expected output files

| File | Description |
|---|---|
| `data/dataset.csv` | 711 rows, 13 columns: identifiers (`record_id`, `scenario_id`, `group_id`) + the 9 approved ML features + `risk_label` |
| `data/raw_records.json` | Same 711 records with full `desired_state`, `actual_state`, `drift_result`, and `features` for every record |
| `data/dataset_validation_report.json` | Full validation results (counts, distributions, consistency checks) |

## Reproducibility

`dataset_generator.py` uses a single `random.Random(42)` instance, threaded
through every baseline/mutation call in a fixed loop order (scenario →
entity → variation). Re-running the script produces byte-identical output —
verified by `test_generation_is_deterministic_given_fixed_seed`.

## Avoiding train/test leakage (for the next milestone)

Every record carries a **`group_id`** column (`"{scenario_id}::E{entity_id}"`).
Records sharing a `group_id` are variations of the *same underlying entity*
(same bucket name / instance name / IAM entity name — only secondary
parameters like CIDR choice, retention days, or the drifted value itself
differ). When the next milestone splits data into train/validation/test,
the split **must** be done by `group_id` (e.g. `sklearn.model_selection
.GroupShuffleSplit`), not by individual row — otherwise two near-identical
variations of the same entity could end up on both sides of the split,
inflating test accuracy. This dataset generator does not perform that split
itself (out of scope for this milestone); it only guarantees the `group_id`
column needed to do it correctly later.

## Known, documented dataset characteristics (not defects)

1. **Feature-only duplicates (610 of 711 rows).** Verified by direct
   inspection (see `dataset_validation_report.json → duplicates`): 100%
   occur *within* a single scenario, because all engineered features except
   `drift_frequency` are deterministic per scenario, and `drift_frequency`
   is drawn from a narrow integer range (e.g. 0–3 for Critical). No two
   *different* scenarios collapse onto the same feature signature. The
   underlying `desired_state`/`actual_state` JSON remains distinct per
   record regardless.
2. **One risk-label / rule-of-thumb disagreement: scenario E7.** An
   independent 5-feature rule-of-thumb (`risk_rule_check.py`) agrees with
   the approved label on 19/20 scenarios (93.8% of records). It disagrees
   on E7 (unplanned peer-security-group reference): the rule predicts High,
   the approved label is Medium, because E7 and I6/I3 share an identical
   coarse feature signature (`privilege_change=True`,
   `change_magnitude=Medium`) despite E7's exposure being internal-lateral-
   movement-only versus I3/I6's removal of a global control. This is
   retained as designed and flagged explicitly for the ML milestone: the
   classifier will need `resource_type`/`changed_attribute` (not just the
   5 severity-driving features) to separate this case correctly.

## ML Training Milestone

### Additional files

```
├── src/
│   ├── ml_pipeline.py              # load → preprocess → split → train → evaluate → save
│   └── plot_confusion_matrices.py  # renders results/confusion_matrices.json as PNGs
├── models/
│   ├── random_forest_model.joblib               # PRIMARY (Split A: stratified random)
│   ├── decision_tree_model.joblib                # PRIMARY (Split A)
│   ├── preprocessor.joblib                       # PRIMARY, fitted on Split A's train set
│   ├── label_mapping.json                        # {"Low":0,"Medium":1,"High":2,"Critical":3}
│   ├── random_forest_model_scenario_split.joblib # SECONDARY (Split B: scenario-group-aware)
│   ├── decision_tree_model_scenario_split.joblib # SECONDARY
│   └── preprocessor_scenario_split.joblib        # SECONDARY
├── results/
│   ├── metrics.json                # full metrics for both splits × both models
│   ├── confusion_matrices.json
│   ├── confusion_matrix_*.png      # 4 rendered confusion matrices
│   └── feature_importance.json
```

### How to run

```bash
cd src
python3 ml_pipeline.py              # trains, evaluates, saves all artifacts
python3 plot_confusion_matrices.py  # renders PNG confusion matrices
cd ..
python3 -m pytest tests/test_ml_pipeline.py -v
```

### Feature / target / metadata separation

- **Target:** `risk_label`, encoded with a fixed severity order (Low=0,
  Medium=1, High=2, Critical=3) rather than sklearn's default alphabetical
  `LabelEncoder`.
- **Features (9):** `resource_type`, `changed_attribute` (one-hot);
  `security_sensitivity`, `change_magnitude`, `port_exposure` (ordinal,
  explicit severity order); `public_exposure`, `encryption_change`,
  `privilege_change` (boolean→int); `drift_frequency` (numeric).
- **Metadata (kept out of the feature matrix):** `record_id`,
  `scenario_id`, `group_id`.
- **`scenario_id` / `group_id` exclusion, justified:** every record's
  `risk_label` is a deterministic property of its `scenario_id` (see
  `SCENARIO_REGISTRY`). Feeding `scenario_id` in would let the model
  memorize a lookup table instead of learning from security attributes —
  and no real AWS resource carries a `scenario_id` field. `group_id` is
  excluded for the same reason (it's `scenario_id`-prefixed).

### A real data-loading pitfall found and fixed (not a dataset bug)

`change_magnitude` legitimately contains the literal string `"None"` for
the 90 non-drift control records. Verified by inspecting the raw CSV bytes
(`grep ",None," data/dataset.csv`) that the file itself is correct —
`pandas.read_csv`'s **default** NA-value list happens to include the bare
word `"None"`, which would silently turn those 90 rows into missing values
on load. Fixed with `keep_default_na=False, na_values=[""]` in
`load_dataset()`. The dataset file was **not** modified; this was purely a
read-time issue, and a regression test (`test_load_dataset_change_
magnitude_none_string_not_corrupted_to_nan`) guards against it recurring.

### Two splits, reported side by side

| | Split A: stratified random (record-level) | Split B: scenario-group-aware (`GroupShuffleSplit`, groups=`scenario_id`) |
|---|---|---|
| Train / test size | 568 / 143 | 592 / 119 |
| Scenarios leaked across train/test | **20 of 20** (every scenario appears on both sides) | **0** (verified empirically via `describe_split_leakage`) |
| Random Forest accuracy | **1.0000** | **0.3697** |
| Decision Tree accuracy | **1.0000** | **0.7059** |

**Split A leaks by design**, and the numbers show it: both models hit
perfect accuracy, precision, recall, and F1 (see `results/metrics.json`).
This is the expected, previously-documented consequence of the dataset's
construction (records within a scenario are near-duplicates differing
mainly in `drift_frequency`) — it demonstrates memorization, not
generalization, and is reported as such rather than presented as a
genuine 100%-accurate model.

**Split B is the honest test**, and both models perform far worse than
Split A once no scenario can be memorized. Investigated (not just
reported): with `scenario_id`-level holdout, this particular split
happened to hold out **both** Critical-labeled security-group scenarios
(E1, E2) together, and the only High-labeled S3 scenario (S3id) — verified
directly:

```
Training set: resource_type × risk_label crosstab (Split B)
risk_label      Critical  High  Low  Medium
resource_type
iam_policy            80    70    0       0
s3_bucket             60     0   90      44
security_group         0    70   90      88
```

Zero `security_group + Critical` and zero `s3_bucket + High` examples ever
appeared in training. Both models were forced to extrapolate to
(resource_type, risk_label) combinations they had never seen — Random
Forest mapped **all** held-out Critical security-group records to "High"
and split held-out High S3 records between "Medium" and "Critical" with
**zero** correct High predictions; Decision Tree also missed every held-out
High record (all routed to "Critical") but, unlike Random Forest, correctly
classified all 40 held-out Critical records. This RF/DT difference on
Split B is reported as observed, without a fully verified mechanistic
explanation — a plausible account is that RF's cross-tree vote-averaging
pulled predictions toward the numerically larger Critical class it had
seen more of overall, while a single tree's greedy split path happened to
route these specific inputs to Critical directly, but this has not been
further isolated.

### Random Forest vs. Decision Tree — not ranked as universally superior

- **On Split A (record-level, leaked):** identical, perfect performance —
  uninformative for model comparison, since the task is memorization.
- **On Split B (scenario-held-out):** Decision Tree (70.6% accuracy)
  outperformed Random Forest (37.0%) on *this specific* held-out scenario
  combination. This does **not** establish Decision Tree as the better
  model in general — with only 20 scenario groups, which 4 land in the
  test set is highly sensitive to the random seed, and a different holdout
  could easily favor the ensemble instead. It does show that Random
  Forest's usual stability advantage is not guaranteed when entire
  categories of training data are absent, and that a single tree's
  behavior in that regime is not automatically worse.
- **Structural trade-offs unaffected by this run:** Random Forest remains
  the more stable choice across resamples in general (averaging over 200
  trees), while a single Decision Tree remains more directly interpretable
  (one traceable path per prediction) — both properties independent of
  which model happened to score higher on this particular held-out split.

### Known limitation flagged for the next (XAI) milestone

`changed_attribute` one-hot-encodes to a near-unique fingerprint per
scenario (20 distinct values for 20 scenarios). This is *why* Split A hits
100% — the model doesn't need the 5 severity-driving features at all when
it can key off which exact attribute changed. For entirely unseen
scenarios (Split B), `handle_unknown="ignore"` zeroes out that fingerprint,
and performance depends entirely on the 5 coarser features
(`public_exposure`, `security_sensitivity`, `privilege_change`,
`encryption_change`, `change_magnitude`) plus `resource_type` — which, as
shown above, is not always sufficient to separate High from Critical for
a genuinely novel scenario. This is exactly the kind of case-level
disagreement (cf. the E7 rule-mismatch documented in the dataset
milestone) that SHAP explanations should surface clearly in the next
milestone — not paper over.

## Status

Dataset generation, validation, and ML training/evaluation are complete
(see `results/metrics.json` and `data/dataset_validation_report.json`).
**SHAP has not been implemented** — that is the next milestone.

---

## Final ML Evaluation Audit

Performed before starting SHAP, to pressure-test the Split B findings
rather than take the earlier 37%/71% accuracy numbers at face value.
**Does not modify the dataset or `ml_pipeline.py`** — `src/ml_evaluation_
audit.py` is a read-only analysis layer on top of already-completed work.

### How to run

```bash
cd src
python3 ml_evaluation_audit.py
cd ..
python3 -m pytest tests/test_ml_evaluation_audit.py -v
```

Output: `results/ml_evaluation_audit.json`.

### 1-2. Exact train/test scenario groups (scenario-group-aware split, seed=42)

```
TRAIN (16 scenarios): E3, E4, E5, E6, E7, I1, I2, I3, I4, I5, I6, S1, S2, S4, S6, S7
TEST  (4 scenarios):  E1, E2, S3id, S5
Scenarios leaked across train/test: 0 (verified)
```

### 3. Class distribution

| | Low | Medium | High | Critical |
|---|---|---|---|---|
| Train | 180 | 132 | 140 | 140 |
| Test | **0** | 44 | 35 | 40 |

**Low is entirely absent from the test set** for this split (neither S7
nor E5, the only two Low-labeled scenarios, happened to be selected for
holdout) — a direct, visible consequence of having only 2 scenario
templates for the Low class.

### 4. resource_type × risk_label combinations in test but absent from train

```
security_group + Critical   (from E1, E2)
s3_bucket + High             (from S3id)
```

### 5. Per-scenario impact on each model (measured directly, not inferred)

| Scenario | True label | n | RF accuracy | RF predictions | DT accuracy | DT predictions |
|---|---|---|---|---|---|---|
| E1 | Critical | 20 | **0.00** | all → High | **1.00** | all → Critical |
| E2 | Critical | 20 | **0.00** | all → High | **1.00** | all → Critical |
| S3id | High | 35 | **0.00** | 11→Medium, 24→Critical | **0.00** | all → Critical |
| S5 | Medium | 44 | 1.00 | all → Medium | 1.00 | all → Medium |

S5 (a *seen* resource_type+risk_label combination, just an unseen
`changed_attribute` value) is classified perfectly by both models — the
failure is specific to the two combinations that were entirely absent
from training, not a general property of held-out scenarios.

### 6. Is the feature set sufficient to distinguish E7 from I3/I6? — No, confirmed empirically

E7, I3, and I6 share an **identical** signature across all 5 core severity
features (`security_sensitivity=Medium`, `public_exposure=False`,
`encryption_change=False`, `privilege_change=True`,
`change_magnitude=Medium`). They differ only in `resource_type`,
`port_exposure`, and `changed_attribute`.

A targeted experiment — hold out **only** E7 (its `changed_attribute`
value `peer_sg_reference` never seen in training) and predict on its 44
records alone:

```
True label: Medium
Random Forest predicted: {'High': 44}   (0% correct)
Decision Tree predicted: {'High': 44}   (0% correct)
```

Both models collapse E7 entirely into the I3/I6 "High" pattern. The
`resource_type`/`port_exposure` differences that theoretically distinguish
E7 turned out **not** to be enough in practice: E7 is the only
`security_group` scenario with `privilege_change=True`, so holding it out
removes every training example of that (resource_type, privilege_change)
pairing — the model has nothing to learn "internal SG privilege change →
Medium" from, and defaults to the IAM-sourced "High" association for
`privilege_change=True + change_magnitude=Medium`.

### 7. changed_attribute encoding — confirmed correct

- Encoded via `OneHotEncoder` (20 columns, one per approved scenario's attribute name) — confirmed by inspecting the fitted `ColumnTransformer`.
- **Retained during prediction** for any seen value — confirmed by transforming two otherwise-identical rows differing only in `changed_attribute` and observing different output vectors.
- For an **unseen** value, `handle_unknown="ignore"` zeroes out only the 20 `changed_attribute` columns — confirmed the other feature columns (`resource_type`, `security_sensitivity`, etc.) remain populated and non-degenerate.

### 8. Methodological limitations (full text in `results/ml_evaluation_audit.json`)

- **Synthetic data:** all 711 records come from 20 hand-authored templates with human-assigned ground-truth labels, not observed real AWS drift — metrics measure rule-reproduction, not real-world performance.
- **Scenario-group split sensitivity:** only 20 groups total; which 4 land in test (as shown above) materially changes reported accuracy. A single split is a point estimate, not a stable measurement — repeated `GroupKFold`/multi-seed evaluation would be needed for a defensible number.
- **Unseen resource-type/risk combinations:** a structural consequence of 20 templates spread unevenly across 3 resource types × 4 risk levels, not an artifact of one unlucky random draw.
- **Balanced class distribution:** ~25% per class by design, which does not reflect a real AWS environment's presumably heavy skew toward Low/benign states — precision/recall here should not be assumed to transfer to an imbalanced production stream.
- **Limited number of scenario groups:** 20 groups is a small population for any group-aware evaluation; both Split B and the E7-holdout experiment are illustrative case studies of a real failure mode, not statistically powered generalization estimates.

### Test coverage

23 new tests in `tests/test_ml_evaluation_audit.py`, all passing, including
reproducibility checks and a JSON-serializability check on the full report.
**Total project test suite: 90/90 passing** across drift_engine,
feature_extraction, dataset_generator, ml_pipeline, and this audit.

**SHAP still not implemented** — next milestone.

---

## SHAP Explainability Milestone

Built on top of the already-trained, already-saved models — **no dataset
changes, no retraining** except one explicitly justified case (below).

### How to run

```bash
cd src
python3 shap_explainability.py
cd ..
python3 -m pytest tests/test_shap_explainability.py -v
```

Output: `results/shap/` (4 global/local PNGs × 2 + 2 JSON files = 10 files, all required).

### 1. SHAP dependency installed and verified
`shap==0.52.0`, confirmed importable and functional against both saved models.

### 2-4. Models, preprocessors, TreeExplainer

Loaded via `joblib` — **not retrained**: `random_forest_model.joblib` (primary, used for the main demonstration), `decision_tree_model.joblib`, and both preprocessors. `shap.TreeExplainer` confirmed to work on both model types, with **exact additivity** verified (max deviation from `predict_proba` on the order of `1e-16`, i.e. floating-point noise) — not assumed, computed.

### A documented, deliberate exception to "primary model only"

The primary (Split A) model has **zero misclassifications across the entire 711-record dataset** — confirmed by running it on every record, not assumed from the earlier 100%-test-accuracy finding. This means there is no genuine incorrectly-classified example available from it. The "incorrectly classified" local explanation therefore uses the **already-saved secondary model** (`random_forest_model_scenario_split.joblib`, from the scenario-group-aware split, which has 75 real misclassifications) — no retraining performed, and this substitution is labeled explicitly in `local_explanations.json` (`"model_used": "random_forest_secondary_scenario_split"`) and in the plot title itself.

### A documented SHAP API compatibility issue (shap==0.52.0)

`explainer.shap_values(X)` for these 4-class models returns a single `(n_samples, n_features, n_classes)` ndarray, not the older list-of-per-class-arrays format. Passing that 3D array to the **legacy** `shap.summary_plot(...)` with its **default** plot type silently misinterprets it as a SHAP-*interaction*-values array and produces an incorrect plot — confirmed by direct visual inspection during development (it collapsed 30 features down to 4 mislabeled rows). Two working paths were found and used instead:
- `plot_type="bar"` **does** handle the 3D array correctly (confirmed) → used for `global_bar.png`.
- The modern object API — wrap in `shap.Explanation`, index one class explicitly (`explanation[:, :, class_index]`), call `shap.plots.beeswarm()` — confirmed correct → used for `global_summary.png` and all local waterfall plots.

### 5-6. Preprocessing pipeline preserved; feature-name alignment verified

Every transform uses `preprocessor.transform()` on the already-fitted, loaded preprocessor — `.fit()`/`.fit_transform()` is never called in this module. `verify_feature_name_alignment()` confirms `X_transformed.shape[1] == len(feature_names) == 30` before any SHAP computation proceeds (asserted, not assumed).

### A. Global explanations

- `global_summary.png` — beeswarm for the **Critical** class (chosen as the operationally most important class; per-class breakdown for all 4 classes is in the JSON, not lost).
- `global_bar.png` — mean |SHAP| per feature, stacked by class.
- `global_feature_importance.json` — mean |SHAP| overall (averaged across samples and classes) and broken down per class, plus the additivity check and feature-alignment check.

Top overall feature by mean |SHAP|: `security_sensitivity`, followed by `change_magnitude` — consistent with these being the two features most scenarios' risk labels were designed around.

### B. Local explanations (6 required cases, all in `local_explanations.json`)

| Case | Row | Scenario | Actual | Predicted | Correct | Model |
|---|---|---|---|---|---|---|
| Critical SG public exposure | 273 | E1 | Critical | Critical | ✓ | primary |
| High IAM privilege change | 601 | I3 | High | High | ✓ | primary |
| Medium E7 case † | 517 | E7 | Medium | Medium | ✓ | primary |
| Low E5 no-drift control | 383 | E5 | Low | Low | ✓ | primary |
| Correctly classified | 22 | S2 | Critical | Critical | ✓ | primary (Split A test set) |
| Incorrectly classified | 40 | S3id | High | **Critical** | ✗ | secondary (Split B) |

† See "Reconciling the E7 SHAP example with the audit's E7 generalization test" below — this result and the audit's 44/44-wrong result are both correct, from two different evaluation contexts.

Each entry reports actual label, predicted label, full prediction probabilities, top positive/negative SHAP contributors, the complete SHAP vector for the predicted class (30 features), and the original 9 raw feature values — all read directly from computed SHAP output, no hand-written text in the numeric fields.

**Model explanation vs. domain interpretation, kept separate:** every JSON field (`top_positive_contributors`, `shap_values`, `prediction_probabilities`) is raw SHAP/model output. The only human-written text is in this README's narrative description of what a plot shows — the JSON itself contains no invented commentary.

### Reconciling the E7 SHAP example with the audit's E7 generalization test

These are **two different experiments, using two different training sets**,
and both results are correct within their own context:

**1. The SHAP milestone's `medium_e7_case` (this section, row 517):**
- Model: **primary** Random Forest (`random_forest_model.joblib`)
- Trained on: **Split A** (stratified random split, record-level) — verified
  directly: row 517 itself is one of the 711 dataset rows, and of E7's 44
  records, **33 were in Split A's training set** (row 517 among them — it
  was literally a training example, not held out at all).
- Result: actual = Medium, predicted = Medium, **correct**.
- What this demonstrates: SHAP explaining a typical prediction from the
  project's main, reportable model — nothing here tests generalization to
  an unseen scenario, and it was never intended to (requirement 3 of this
  milestone specifically asked for the primary model on ordinary records).

**2. The ML evaluation audit's targeted E7 holdout experiment (previous
milestone, `ml_evaluation_audit.json` → `e7_vs_i3_i6_feature_sufficiency`):**
- Models: **freshly trained** Random Forest and Decision Tree, trained on
  all 19 *other* scenarios with **all 44 E7 records excluded from
  training entirely** — a different, temporary model built specifically
  for that audit, not the saved primary/secondary models used elsewhere.
- Result: actual = Medium for all 44 records; **Random Forest predicted
  High for 44/44, Decision Tree predicted High for 44/44** — 0% correct,
  both models.
- What this demonstrates: whether the 9-feature schema lets a model
  *infer* E7's correct severity when it has never seen E7's pattern at
  all — a genuine generalization stress-test.

**Why both are true at once:** the primary model correctly classifies row
517 because it memorized this row (and 32 of its 43 siblings) during
training — record-level stratified splitting leaks scenario patterns, a
limitation documented extensively elsewhere in this README (see "Two
splits, reported side by side" and the audit's "scenario_group_split_
sensitivity" limitation). The audit's holdout model gets *every* E7 record
wrong specifically *because* it was deprived of exactly that memorization
opportunity. The SHAP example shows what the model does when it has seen
similar examples; the audit shows what it does when it hasn't. Neither
number is more "correct" than the other — they answer different questions
about the same underlying model architecture and feature set.

### Verification requirements — all checked programmatically, not asserted by claim

- **SHAP values correspond to predicted class:** `shap_values_for_predicted_class()` explicitly indexes each sample's own predicted-class slice; tested directly (`test_shap_values_for_predicted_class_selects_correct_slice`).
- **Multiclass output handled correctly:** shape `(n, 30, 4)` confirmed for both models; additivity confirmed per-class.
- **Additivity:** checked via `base_value[c] + sum(shap_values[:,:,c]) ≈ predict_proba[:,c]`, max deviation ~1e-16 for both models.

### Test coverage

39 new tests in `tests/test_shap_explainability.py` — model/preprocessor loading, feature-name alignment (including on the secondary preprocessor), SHAP output shape for both models, additivity, predicted-class slicing, representative-record selection (each verified against its own stated filter criteria, including confirming the "incorrect" example is genuinely misclassified and the "correct" one genuinely isn't), and existence/structure checks on all 10 saved output files.

**Total project test suite: 129/129 passing** across drift_engine, feature_extraction, dataset_generator, ml_pipeline, ml_evaluation_audit, and shap_explainability.

Dashboard and AWS deployment **not implemented** — next milestones.

---

## Streamlit Dashboard Milestone

A local, working demonstration UI built on top of every prior milestone's
artifacts. **Does not modify or regenerate** `data/dataset.csv`,
`data/raw_records.json`, any trained model, any preprocessor, or any SHAP
output — `app.py` only *reads* these via the same functions already used
elsewhere in the project.

### Launch it

```bash
pip install -r requirements.txt
streamlit run app.py
```

Then open the URL Streamlit prints (typically `http://localhost:8501`).

Verified during development: launched headlessly (`streamlit run app.py
--server.headless true`), returned **HTTP 200** with a clean startup log
and no runtime errors — not just import-tested.

### What it does

1. **Two input methods**, chosen via a radio button:
   - **Predefined demonstration scenario** — a dropdown listing all 20
     approved scenarios read directly from `SCENARIO_REGISTRY`
     (`scenario_definitions.py`). Selecting one calls that scenario's
     *actual* `baseline_fn`/`mutate_fn` (seed=42, entity_id=1) to
     regenerate real desired/actual JSON — the same functions
     `dataset_generator.py` uses, not a reimplementation — and
     pre-fills both text areas. The scenario's approved ground-truth
     label is shown for comparison, never fed to the model.
   - **Custom JSON** — free-form desired/actual state text areas plus a
     resource-type selector (required by `extract_features`).
2. **"Analyze Drift"** button runs the full pipeline: `parse_json_input`
   → `detect_drift()` → `extract_features()` → `preprocessor.transform()`
   → `model.predict_proba()` → SHAP `TreeExplainer` — each step calling
   the real, already-tested function from its module.
3. Displays, in order: whether drift exists, number of changes, the list
   of changed attributes, an old-vs-new-value table, the extracted
   9-feature dict, the predicted risk label (explicitly labeled "Primary
   Random Forest Model"), a probability bar chart across all 4 classes,
   top positive/negative SHAP contributors, an additivity check readout,
   and a SHAP waterfall plot for the predicted class.

### Error handling (all verified by test, not just implemented)

| Case | Handling |
|---|---|
| Invalid JSON syntax | Caught in `parse_json_input`, shown via `st.error`, pipeline never runs |
| Empty / whitespace-only input | Same path, distinct message |
| JSON that isn't an object (e.g. a bare list) | Rejected with an explicit "must be a JSON object" message |
| No drift (identical states) | Not an error — shown as an info message, full pipeline still runs (matches the E5 control case, predicts Low) |
| Unknown changed attribute | `extract_features()`'s `KeyError` is caught and surfaced as a clear, specific error — prediction is not attempted with a guessed value |
| Missing model/preprocessor files | `load_model_artifacts()` raises `FileNotFoundError` with an actionable message ("run ml_pipeline.py first"), caught and shown via `st.error` |

### No fabricated output

Every number shown — drift detection result, extracted features,
prediction probabilities, SHAP values — is computed live in
`run_drift_and_risk_pipeline()` by calling the real `detect_drift`,
`extract_features`, `model.predict_proba`, and `shap.TreeExplainer`. The
sidebar's "Important Evaluation Limitation" figures are read directly
from `results/metrics.json` and `results/ml_evaluation_audit.json` at
render time (`load_evaluation_limitation_summary()`) — not retyped as
static text — so they can never drift out of sync with the actual saved
evaluation results, and the sidebar shows "artifacts not found" rather
than a fabricated number if those files are ever absent.

### Testable-by-design structure

Every business-logic function (`parse_json_input`, `load_model_artifacts`,
`build_feature_row`, `run_drift_and_risk_pipeline`,
`generate_scenario_json`, `load_evaluation_limitation_summary`) contains
**zero** Streamlit calls. All `st.*` calls live inside `render_*()`/`main()`,
executed only under `if __name__ == "__main__"` — so `import app` in tests
never touches the Streamlit runtime, and `streamlit run app.py` still
works identically.

### Test coverage (`tests/test_app.py`)

25 tests: app import safety (confirms no `st.*` call fires on import),
module reuse (`app.detect_drift is` the real `drift_engine.detect_drift`,
not a copy), JSON parsing (valid/invalid/empty/non-object/None), model
loading (real artifacts + a simulated missing-artifacts case), no-drift
input (hand-written + the real E5 scenario), drift input (hand-written
S1-equivalent + the real S1 scenario, both correctly predicting Critical),
unknown-attribute handling, **all 20 predefined scenarios run end-to-end
without error**, deterministic scenario generation, feature-row
construction, and the sidebar's live-loaded evaluation summary.

**Total project test suite: 154/154 passing** across drift_engine,
feature_extraction, dataset_generator, ml_pipeline, ml_evaluation_audit,
shap_explainability, and app.

AWS deployment, Cognito, Lambda, SNS, and automated remediation **not
implemented** — next milestones.

---

## AWS Integration Milestone (Phase 1: S3)

Real Terraform + boto3 integration layer on top of every prior milestone.
**Does not modify** `data/dataset.csv`, `data/raw_records.json`, any
trained model, any preprocessor, or any SHAP output (confirmed via
checksum before and after this milestone) — and does not modify
`drift_engine.py` or `feature_extraction.py` either; both are reused
completely unchanged.

### New files

```
terraform/
├── versions.tf     # provider requirements, no hardcoded credentials
├── variables.tf    # aws_region, project_prefix, environment (safe defaults)
├── main.tf         # ONE demo S3 bucket: public access blocked, SSE-AES256, ACL private, versioning explicit
├── outputs.tf      # bucket_name, bucket_arn, aws_region
└── .gitignore      # excludes *.tfstate, .terraform/, *.tfvars
src/aws_state.py         # boto3 I/O only — credential checks, raw API calls, categorized errors
src/aws_normalizer.py    # AWS-shape <-> project's normalized schema (both directions)
demo_aws_integration.py  # end-to-end: credential check -> real-or-simulated drift -> existing ML pipeline
tests/test_aws_state.py  # 48 tests (47 unit + 1 real-AWS, skipped by default)
```

### Design: AWS-specific code kept separate from the generic drift engine

`drift_engine.py` and `feature_extraction.py` are **untouched** — they
already work on the normalized schema (`resource_type`,
`block_public_access`, `acl`, `encryption.enabled`, `versioning`,
`logging`, `lifecycle_rule`, `bucket_policy_principal`) because that's
the exact same schema the synthetic dataset already uses. All AWS-shape
knowledge (how a `get_bucket_acl()` response maps to `"private"` vs
`"public-read"`, etc.) lives in `aws_normalizer.py` only; all boto3
network I/O lives in `aws_state.py` only.

### Terraform configuration (Phase 1: S3 only)

`main.tf` provisions one bucket, safe by default for a student account:
public access fully blocked (all 4 sub-settings), SSE-S3/AES256 encryption
(no KMS key/permissions needed), ACL explicitly `private`, versioning
explicitly `Disabled` (not left ambiguous), no bucket policy, no
lifecycle rule, no logging bucket (avoids provisioning a second bucket).
Clear naming: `${project_prefix}-${environment}-${random_id}`.

### Desired state: parsed from the real `.tf` files, not hand-duplicated

`aws_normalizer.derive_s3_desired_state_from_terraform()` uses
`python-hcl2` to parse `terraform/main.tf` directly and derive the
desired-state dict — verified against the actual file, not a parallel
hand-maintained copy that could silently drift out of sync (a dedicated
regression test pins this: `test_derive_desired_state_matches_actual_
main_tf_declarations`, which fails loudly if `main.tf` is edited without
the mapping logic being updated to match).

### Genuine drift demonstrated end-to-end (Steps 8–10)

`demo_aws_integration.py` demonstrates one supported configuration
changed outside Terraform — `block_public_access` disabled — and runs it
through `detect_drift()` → `extract_features()` → the **existing saved
primary Random Forest model** (no retraining):

```
STEP 3 [SIMULATED]: has_drift=True, num_changes=1, changed_attributes=['block_public_access']
STEP 4 [SIMULATED]: predicted risk = Critical (Critical probability = 1.0000)
```

This exactly reproduces scenario S1's pattern, confirming the AWS-shaped
input is fully compatible with the unmodified, already-trained pipeline.

### AWS connectivity classification — strict evidence-based grading

Three possible classifications were defined for this check, and only one
applies here:
- **A. REAL AWS ACCESS** — boto3 authenticated, an actual API call
  succeeded, real S3 state was retrieved.
- **B. REAL AWS REACHABILITY BUT NO ACCESS** — evidence indicates the
  request reached AWS; auth/authorization blocked the operation.
- **C. NO VERIFIED AWS ACCESS** — credentials/network/environment
  prevented verification; real AWS integration cannot be claimed.

**Result: C. NO VERIFIED AWS ACCESS** — for both checks below, on two
independent grounds (either one alone would be sufficient).

**Check 1 — no credentials configured:**
```
NoCredentialsError: Unable to locate credentials
```
Fails at local credential resolution, before any network call is even
attempted. No ambiguity here.

**Check 2 — syntactically-valid-but-fake credentials**, to isolate
whether a network path to AWS exists independently of credential
validity. A generic `403 Forbidden` alone would NOT be enough to rule out
B (AWS itself returns 403 for bad credentials too) — so the full raw
response was inspected instead of stopping at the status code:
```json
{
  "Error": {"Code": "403", "Message": "Forbidden"},
  "ResponseMetadata": {
    "RequestId": "", "HostId": "",
    "HTTPStatusCode": 403,
    "HTTPHeaders": {
      "x-deny-reason": "host_not_allowed",
      "content-type": "text/plain"
    }
  }
}
```
Four independent signals, together, positively prove this response did
**not** originate from AWS (this is not "absence of proof of A" — it is
**positive proof against B**):
1. `RequestId` and `HostId` are **empty strings** — real AWS populates
   both on every response, error or not.
2. `content-type: text/plain` — a real AWS S3/STS error response is
   always XML (`application/xml`).
3. `x-deny-reason: host_not_allowed` is this sandbox's own egress-proxy
   header (documented in this environment's own network configuration),
   not an AWS response header.
4. The message body is exactly the proxy's own denial text, not AWS's
   standard error XML schema.

This is this sandbox's network egress proxy intercepting and rejecting
the request before it ever left the sandbox — not AWS rejecting bad
credentials. **Per instruction, a generic 403 is never inferred as proof
of reaching AWS, and it is not treated that way here.**

Both checks were re-run fresh immediately before finalizing this
milestone (not reused from an earlier session) and produced byte-identical
results.

**Terraform CLI:** not installed, and not installable here — confirmed
by checking (`apt-cache show terraform` → "No packages found"; the
HashiCorp release/registry domains are outside this sandbox's network
allowlist, so `terraform init` could never download the CLI or the AWS
provider plugin here even if the binary existed). As a substitute, real
**structural validation** was run using `terraform-config-inspect`
(installable via the Ubuntu archive, genuinely real output, not
fabricated) — confirmed all 7 resources, 3 variables, and 3 outputs
parse correctly with **zero diagnostics**:
```
managed_resources: aws_s3_bucket.demo, aws_s3_bucket_acl.demo,
  aws_s3_bucket_ownership_controls.demo,
  aws_s3_bucket_public_access_block.demo,
  aws_s3_bucket_server_side_encryption_configuration.demo,
  aws_s3_bucket_versioning.demo, random_id.bucket_suffix
diagnostics: None
```
This is a genuine structural check but is **not equivalent to**
`terraform validate` (no provider-schema or type checking) — stated
plainly, not glossed over. `terraform fmt` was not run for the same
reason (no binary available).

**`terraform apply` was not run** — no credentials are configured, and
no explicit approval to create a real AWS resource was requested for this
turn, per the milestone's own instruction.

### Exact commands to run this locally (with real AWS credentials)

```bash
# 1. Provision the demo bucket
cd terraform
terraform fmt -check -recursive
terraform init
terraform validate
terraform plan
terraform apply                      # review the plan, then approve
BUCKET_NAME=$(terraform output -raw bucket_name)
cd ..

# 2. Run the full pipeline against the REAL bucket
python3 demo_aws_integration.py --bucket "$BUCKET_NAME"
# -> STEP 1 shows real credentials; STEP 2 is labeled [REAL AWS], not [SIMULATED]

# 3. Inject genuine drift OUTSIDE Terraform (one supported change)
aws s3api put-public-access-block --bucket "$BUCKET_NAME" \
  --public-access-block-configuration \
  BlockPublicAcls=false,IgnorePublicAcls=false,BlockPublicPolicy=false,RestrictPublicBuckets=false

# 4. Re-run the collector -- now shows real detected drift + a live
#    Critical prediction from the unmodified primary model
python3 demo_aws_integration.py --bucket "$BUCKET_NAME"

# 5. Clean up (avoid any ongoing cost/exposure)
aws s3api put-public-access-block --bucket "$BUCKET_NAME" \
  --public-access-block-configuration \
  BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true
cd terraform && terraform destroy
```

To run the one real-AWS pytest case (skipped by default):
```bash
RUN_REAL_AWS_TESTS=1 AWS_TEST_BUCKET="$BUCKET_NAME" pytest tests/test_aws_state.py -k real -v
```

### Test coverage (`tests/test_aws_state.py`) — mocked vs. real, clearly separated

**47 unit tests**, all mocked/hand-crafted, zero AWS credentials or network needed:
- AWS response normalization (public access block, ACL, encryption, versioning, logging, lifecycle, policy-principal) — matching + edge cases
- Terraform desired-state parsing, pinned against the real `main.tf`
- The adapter combined with `detect_drift()` (no-drift + genuine-drift cases), and confirmed compatible with unmodified `feature_extraction.py`
- `fetch_s3_bucket_raw_config()` via `botocore.stub.Stubber` (the officially-supported way to test boto3-calling code without a network call): success, all-not-configured, bucket-not-found, access-denied, unexpected-ClientError
- `check_aws_credentials()`: no-credentials, valid (stubbed STS), ClientError
- **Malformed AWS responses**: missing required top-level keys (fails loudly with `KeyError`, matching this project's existing fail-loud philosophy for unknown attributes) vs. missing optional sub-keys (handled gracefully with defaults) — both behaviors verified, not just one assumed

**1 real-AWS integration test**, skipped by default (`TestRealAWSIntegration`), clearly documented as requiring `RUN_REAL_AWS_TESTS=1` + `AWS_TEST_BUCKET` — never runs unless a real, working AWS account is explicitly provided.

**Total project test suite: 202 tests (201 passed, 1 skipped)** across drift_engine, feature_extraction, dataset_generator, ml_pipeline, ml_evaluation_audit, shap_explainability, app, and aws_state.

Lambda, Cognito, DynamoDB, SNS, and automated remediation **not
implemented** — next milestones.
