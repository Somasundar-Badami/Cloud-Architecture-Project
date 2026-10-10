"""
app.py

Streamlit dashboard for the AI-Based Infrastructure Drift Detection
Framework. Local demonstration only.

Integrates, WITHOUT modifying or regenerating:
  - src/drift_engine.py            (detect_drift)
  - src/feature_extraction.py      (extract_features)
  - src/scenario_definitions.py    (SCENARIO_REGISTRY, baseline/mutate fns)
  - src/ml_pipeline.py             (FEATURE_COLUMNS, BOOLEAN_FEATURES, RISK_LABEL_ORDER)
  - src/shap_explainability.py     (build_explainer, compute_shap_values, check_additivity)
  - models/random_forest_model.joblib + models/preprocessor.joblib (already trained/fitted)
  - results/metrics.json + results/ml_evaluation_audit.json (already computed)

Design note for testability: every function that touches business logic
(JSON parsing, drift detection, feature extraction, prediction, SHAP) is a
plain Python function with NO Streamlit calls inside it. All st.* calls
live in the render_*()/main() functions at the bottom, which only execute
when this file is run via `streamlit run app.py` (guarded by
`if __name__ == "__main__"`). This lets tests `import app` and call the
pure functions directly without needing a running Streamlit server.
"""

import os
import sys
import json
import random

import joblib
import numpy as np
import pandas as pd
import streamlit as st
import shap
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import project_paths  # noqa: E402

from drift_engine import detect_drift  # noqa: E402
from feature_extraction import extract_features  # noqa: E402
from scenario_definitions import SCENARIO_REGISTRY  # noqa: E402
from ml_pipeline import FEATURE_COLUMNS, BOOLEAN_FEATURES, RISK_LABEL_ORDER  # noqa: E402
from shap_explainability import (  # noqa: E402
    build_explainer,
    compute_shap_values,
    check_additivity,
)

MODELS_DIR = project_paths.MODELS_DIR
RESULTS_DIR = project_paths.RESULTS_DIR

RESOURCE_TYPE_OPTIONS = ["s3_bucket", "security_group", "iam_policy"]


# ---------------------------------------------------------------------------
# Pure / testable logic (no Streamlit calls inside any function below)
# ---------------------------------------------------------------------------

def parse_json_input(text, field_label):
    """
    Parses a JSON text blob. Returns (parsed_dict, error_message).
    error_message is None on success. Handles: empty input, invalid JSON
    syntax, and JSON that parses but isn't an object (e.g. a bare list
    or number) -- all required-field/invalid-JSON cases funnel through
    here before anything else runs.
    """
    if text is None or not text.strip():
        return None, f"{field_label} is empty. Please provide JSON."
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as e:
        return None, f"{field_label} is not valid JSON: {e}"
    if not isinstance(parsed, dict):
        return None, f"{field_label} must be a JSON object (e.g. {{...}}), got {type(parsed).__name__}."
    return parsed, None


def load_model_artifacts():
    """
    Loads the PRIMARY Random Forest model + its fitted preprocessor +
    label mapping via joblib/json -- read-only, never retrains or refits
    anything. Raises FileNotFoundError with an actionable message if any
    artifact is missing (the caller decides how to surface this to the
    user, e.g. st.error + st.stop()).
    """
    rf_path = os.path.join(MODELS_DIR, "random_forest_model.joblib")
    preproc_path = os.path.join(MODELS_DIR, "preprocessor.joblib")
    mapping_path = os.path.join(MODELS_DIR, "label_mapping.json")

    for path in [rf_path, preproc_path, mapping_path]:
        if not os.path.exists(path):
            raise FileNotFoundError(
                f"Required model artifact not found: {path}. "
                f"Run 'python3 src/ml_pipeline.py' from the project root first "
                f"to generate the trained model and preprocessor."
            )

    model = joblib.load(rf_path)
    preprocessor = joblib.load(preproc_path)
    with open(mapping_path) as f:
        label_mapping = json.load(f)
    int_to_label = {int(k): v for k, v in label_mapping["int_to_label"].items()}
    return {"model": model, "preprocessor": preprocessor, "int_to_label": int_to_label}


def build_feature_row(features_dict):
    """
    Converts an extract_features() output dict into a single-row
    DataFrame with exactly the FEATURE_COLUMNS the preprocessor expects,
    casting booleans to int -- the identical transformation
    ml_pipeline.separate_features_target_metadata() applies during
    training, reused here rather than reimplemented differently.
    """
    row = {col: features_dict[col] for col in FEATURE_COLUMNS}
    df_row = pd.DataFrame([row])
    for col in BOOLEAN_FEATURES:
        df_row[col] = df_row[col].astype(int)
    return df_row


def run_drift_and_risk_pipeline(desired_state, actual_state, resource_type_hint, drift_frequency, artifacts):
    """
    Full pipeline, pure Python (no Streamlit calls): drift detection ->
    feature extraction -> preprocessing -> prediction -> SHAP explanation.

    Every step calls the EXISTING, already-validated function from the
    corresponding module -- nothing here re-derives drift logic, feature
    rules, or SHAP math. Returns a plain dict; on a handled failure mode
    (currently: unknown changed attribute), returns a dict with
    error="unknown_attribute" and no prediction fields, rather than
    raising.
    """
    drift_result = detect_drift(desired_state, actual_state)

    try:
        features = extract_features(resource_type_hint, drift_result, drift_frequency)
    except KeyError as e:
        return {"error": "unknown_attribute", "message": str(e), "drift_result": drift_result}

    feature_row = build_feature_row(features)

    model = artifacts["model"]
    preprocessor = artifacts["preprocessor"]
    int_to_label = artifacts["int_to_label"]

    X_transformed = preprocessor.transform(feature_row)
    feature_names = list(preprocessor.get_feature_names_out())

    probabilities = model.predict_proba(X_transformed)[0]
    predicted_class_int = int(np.argmax(probabilities))
    predicted_label = int_to_label[predicted_class_int]

    explainer = build_explainer(model)
    shap_values, base_values = compute_shap_values(explainer, X_transformed)
    additivity = check_additivity(shap_values, base_values, model, X_transformed)
    predicted_class_shap = shap_values[0, :, predicted_class_int]

    ranked = sorted(zip(feature_names, predicted_class_shap.tolist()), key=lambda p: -p[1])
    top_positive = [(f, v) for f, v in ranked if v > 0][:5]
    top_negative = [(f, v) for f, v in ranked[::-1] if v < 0][:5]

    return {
        "error": None,
        "drift_result": drift_result,
        "features": features,
        "predicted_label": predicted_label,
        "probabilities": {int_to_label[i]: float(p) for i, p in enumerate(probabilities)},
        "top_positive_contributors": top_positive,
        "top_negative_contributors": top_negative,
        "additivity_check": additivity,
        "base_values": base_values,
        "shap_values_full": shap_values,
        "feature_names": feature_names,
        "X_transformed": X_transformed,
        "predicted_class_int": predicted_class_int,
    }


def get_predefined_scenario_options():
    """Reads the demonstration scenario list directly from the existing
    SCENARIO_REGISTRY -- not a separately maintained/duplicated list."""
    return [
        {
            "scenario_id": s["scenario_id"],
            "description": s["description"],
            "resource_type": s["resource_type"],
            "approved_risk_label": s["risk_label"],
        }
        for s in SCENARIO_REGISTRY
    ]


def generate_scenario_json(scenario_id, seed=42, entity_id=1):
    """
    Regenerates desired/actual state JSON for a predefined scenario by
    calling the scenario's EXISTING baseline_fn/mutate_fn from
    scenario_definitions.py directly -- the exact same functions
    dataset_generator.py uses, not a reimplementation. Deterministic given
    a fixed seed, so the same scenario always shows the same example.
    """
    scenario = next((s for s in SCENARIO_REGISTRY if s["scenario_id"] == scenario_id), None)
    if scenario is None:
        raise ValueError(f"Unknown scenario_id: {scenario_id}")
    rng = random.Random(seed)
    desired = scenario["baseline_fn"](rng, entity_id)
    actual = scenario["mutate_fn"](desired, rng)
    return desired, actual, scenario["resource_type"], scenario["risk_label"]


def load_evaluation_limitation_summary():
    """
    Reads key numbers directly from the already-computed evaluation
    artifacts (results/metrics.json, results/ml_evaluation_audit.json) --
    nothing here is hardcoded; if those files don't exist, returns an
    empty dict and the caller shows a fallback message instead of a
    fabricated number.
    """
    summary = {}
    metrics_path = os.path.join(RESULTS_DIR, "metrics.json")
    audit_path = os.path.join(RESULTS_DIR, "ml_evaluation_audit.json")

    if os.path.exists(metrics_path):
        with open(metrics_path) as f:
            metrics = json.load(f)
        summary["split_a_accuracy"] = metrics["split_A_stratified_random"]["random_forest"]["accuracy"]
        summary["split_b_accuracy"] = metrics["split_B_scenario_group_aware"]["random_forest"]["accuracy"]

    if os.path.exists(audit_path):
        with open(audit_path) as f:
            audit = json.load(f)
        th = audit["e7_vs_i3_i6_feature_sufficiency"]["targeted_holdout_experiment"]
        summary["e7_holdout_rf_correct_rate"] = th["random_forest_correct_rate"]

    return summary


def _fmt_pct(value):
    return f"{value:.0%}" if isinstance(value, (int, float)) else "N/A"


# ---------------------------------------------------------------------------
# Streamlit UI -- only executes when run via `streamlit run app.py`
# ---------------------------------------------------------------------------

def render_sidebar():
    st.sidebar.title("InfraDriftGuard")
    st.sidebar.markdown("**AI-Based Infrastructure Drift Detection Framework using Explainable AI**")
    st.sidebar.markdown("---")

    st.sidebar.subheader("Model")
    st.sidebar.markdown(
        "- **Algorithm:** Random Forest (**primary** model)\n"
        "- **Trees:** 200 estimators\n"
        "- **Trained on:** Split A (stratified random split)\n"
        "- **Baseline for comparison:** Decision Tree\n"
        "- **Explainability:** SHAP `TreeExplainer`"
    )

    st.sidebar.subheader("Dataset")
    st.sidebar.markdown(
        "- 711 **synthetic** records\n"
        "- 20 approved drift scenarios (S3, EC2 Security Groups, IAM)\n"
        "- 4 risk levels: Low / Medium / High / Critical\n"
        "- No real AWS Config data — see literature survey milestone"
    )

    st.sidebar.subheader("⚠️ Important Evaluation Limitation")
    summary = load_evaluation_limitation_summary()
    if summary:
        st.sidebar.markdown(
            f"- Record-level split accuracy: **{_fmt_pct(summary.get('split_a_accuracy'))}** "
            f"— inflated by scenario leakage (near-duplicate records land on both "
            f"sides of the split)\n"
            f"- Scenario-**held-out** accuracy: **{_fmt_pct(summary.get('split_b_accuracy'))}** "
            f"— the more realistic generalization estimate\n"
            f"- On a targeted unseen-scenario test (E7), Random Forest predicted "
            f"correctly **{_fmt_pct(summary.get('e7_holdout_rf_correct_rate'))}** of the time"
        )
    else:
        st.sidebar.markdown(
            "_Evaluation artifacts not found — run `src/ml_pipeline.py` and "
            "`src/ml_evaluation_audit.py` first._"
        )
    st.sidebar.caption("Full analysis: `results/ml_evaluation_audit.json` and `README.md`.")


def render_header():
    st.title("InfraDriftGuard — AI-Based Infrastructure Drift Detection")
    st.caption(
        "**Drift analyzer** runs the trained model locally on any desired/actual JSON. "
        "**Live AWS findings** shows what the deployed Lambda detector found in your AWS account."
    )
    st.info(
        "The risk model is trained on 711 synthetic records from 20 hand-authored scenarios. "
        "Its record-level accuracy does not measure real-world generalization — see the "
        "Evaluation Limitation note in the sidebar."
    )


def render_input_section():
    st.header("1. Provide Desired vs. Actual State")
    mode = st.radio("Input method", ["Predefined demonstration scenario", "Custom JSON"], horizontal=True)

    desired_text, actual_text = "", ""
    resource_type_hint = RESOURCE_TYPE_OPTIONS[0]
    scenario_ground_truth = None

    if mode == "Predefined demonstration scenario":
        options = get_predefined_scenario_options()
        labels = [f"{o['scenario_id']} — {o['description']} ({o['approved_risk_label']})" for o in options]
        choice_idx = st.selectbox("Scenario", range(len(options)), format_func=lambda i: labels[i])
        chosen = options[choice_idx]
        desired, actual, resource_type_hint, ground_truth_label = generate_scenario_json(chosen["scenario_id"])
        desired_text = json.dumps(desired, indent=2)
        actual_text = json.dumps(actual, indent=2)
        scenario_ground_truth = ground_truth_label
        st.caption(
            f"Approved ground-truth risk label for this scenario: **{ground_truth_label}** "
            f"(from `scenario_definitions.py` — shown for comparison, never fed to the model)."
        )
    else:
        resource_type_hint = st.selectbox("Resource type (required by extract_features)", RESOURCE_TYPE_OPTIONS)
        st.caption(
            "Custom JSON is not validated against a specific AWS schema — any two "
            "JSON objects can be compared. If a changed attribute isn't one of the "
            "20 approved attribute names, prediction will report 'unknown attribute' "
            "rather than guess."
        )

    col1, col2 = st.columns(2)
    with col1:
        desired_input = st.text_area("Desired state (JSON)", value=desired_text, height=280, key="desired_input")
    with col2:
        actual_input = st.text_area("Actual state (JSON)", value=actual_text, height=280, key="actual_input")

    drift_frequency = st.number_input(
        "drift_frequency — historical drift count for this resource "
        "(not derivable from a single state comparison; supply your own estimate)",
        min_value=0, max_value=50, value=0, step=1,
    )

    return desired_input, actual_input, resource_type_hint, drift_frequency, scenario_ground_truth


def render_shap_waterfall_figure(result, int_to_label):
    predicted_class_int = result["predicted_class_int"]
    explanation = shap.Explanation(
        values=result["shap_values_full"][0, :, predicted_class_int],
        base_values=result["base_values"][predicted_class_int],
        data=result["X_transformed"][0],
        feature_names=result["feature_names"],
    )
    fig = plt.figure()
    shap.plots.waterfall(explanation, show=False, max_display=12)
    plt.title(f"SHAP explanation — predicted: {int_to_label[predicted_class_int]}", fontsize=10)
    plt.tight_layout()
    return fig


def render_results(result, scenario_ground_truth, int_to_label):
    st.header("2. Drift Detection Result")
    drift_result = result["drift_result"]

    col1, col2 = st.columns(2)
    col1.metric("Drift detected", "Yes" if drift_result["has_drift"] else "No")
    col2.metric("Number of changes", drift_result["num_changes"])

    if drift_result["has_drift"]:
        st.markdown(f"**Changed attributes:** {', '.join(drift_result['changed_attributes'])}")
        st.subheader("Old vs. new values")
        change_table = pd.DataFrame(drift_result["changes"])
        st.dataframe(change_table, use_container_width=True)
    else:
        st.info("No drift detected — desired state and actual state are identical.")

    if result["error"] == "unknown_attribute":
        st.error(
            "⚠️ One or more changed attributes are not in the model's known "
            "feature schema (`ATTRIBUTE_KNOWLEDGE_BASE` in `feature_extraction.py`), "
            "so a risk prediction cannot be generated for this input.\n\n"
            f"Details: {result['message']}"
        )
        return

    st.header("3. Extracted ML Features")
    st.caption(
        "Computed live by `feature_extraction.extract_features()` from the drift "
        "result above — not hand-entered."
    )
    st.json(result["features"])

    st.header("4. Risk Prediction — Primary Random Forest Model")
    st.caption(
        "Generated live by the saved **primary Random Forest model** "
        "(`models/random_forest_model.joblib`) via `preprocessor.transform()` + "
        "`model.predict_proba()` on the features above."
    )
    predicted_label = result["predicted_label"]
    if scenario_ground_truth:
        match = "✓ matches" if predicted_label == scenario_ground_truth else "✗ does NOT match"
        st.markdown(f"### Predicted risk: **{predicted_label}**")
        st.markdown(f"Approved ground-truth label for this scenario: **{scenario_ground_truth}** ({match})")
    else:
        st.markdown(f"### Predicted risk: **{predicted_label}**")

    prob_df = pd.DataFrame([{"risk_level": k, "probability": v} for k, v in result["probabilities"].items()])
    prob_df["risk_level"] = pd.Categorical(prob_df["risk_level"], categories=RISK_LABEL_ORDER, ordered=True)
    prob_df = prob_df.sort_values("risk_level")
    render_probability_chart(result["probabilities"])
    st.dataframe(prob_df, use_container_width=True)

    st.header("5. SHAP Local Explanation")
    additivity = result["additivity_check"]
    st.caption(
        f"SHAP `TreeExplainer` values for the **predicted** class ({predicted_label}), "
        f"computed live — not fabricated. Additivity check (base_value + Σ SHAP values "
        f"vs. model output): max deviation = {additivity['max_abs_diff_from_predict_proba']:.2e} "
        f"({'holds' if additivity['additivity_holds'] else 'FAILED'})."
    )

    colp, coln = st.columns(2)
    with colp:
        st.subheader("Top positive contributors")
        st.table(pd.DataFrame(result["top_positive_contributors"], columns=["feature", "shap_value"]))
    with coln:
        st.subheader("Top negative contributors")
        st.table(pd.DataFrame(result["top_negative_contributors"], columns=["feature", "shap_value"]))

    fig = render_shap_waterfall_figure(result, int_to_label)
    st.pyplot(fig)
    plt.close(fig)


RISK_COLORS = {"Critical": "#c0392b", "High": "#e67e22", "Medium": "#f1c40f", "Low": "#27ae60", "Review": "#8e44ad"}


def render_probability_chart(probabilities):
    """Compact horizontal bar chart in severity order (Low -> Critical)."""
    import altair as alt

    df = pd.DataFrame({"risk_level": RISK_LABEL_ORDER,
                       "probability": [float(probabilities.get(k, 0.0)) for k in RISK_LABEL_ORDER]})
    chart = (
        alt.Chart(df)
        .mark_bar()
        .encode(
            x=alt.X("probability:Q", scale=alt.Scale(domain=[0, 1]), axis=alt.Axis(format="%"), title="Probability"),
            y=alt.Y("risk_level:N", sort=RISK_LABEL_ORDER, title=None),
            color=alt.Color("risk_level:N", scale=alt.Scale(domain=list(RISK_COLORS), range=list(RISK_COLORS.values())),
                            legend=None),
            tooltip=["risk_level", alt.Tooltip("probability:Q", format=".1%")],
        )
        .properties(height=150)
    )
    st.altair_chart(chart, use_container_width=True)


def render_offline_analyzer():
    desired_input, actual_input, resource_type_hint, drift_frequency, scenario_ground_truth = render_input_section()

    if st.button("Analyze Drift", type="primary"):
        desired_state, err_d = parse_json_input(desired_input, "Desired state")
        if err_d:
            st.error(f"⚠️ {err_d}")
            st.stop()
        actual_state, err_a = parse_json_input(actual_input, "Actual state")
        if err_a:
            st.error(f"⚠️ {err_a}")
            st.stop()

        try:
            artifacts = load_model_artifacts()
        except FileNotFoundError as e:
            st.error(f"⚠️ Model loading error: {e}")
            st.stop()

        result = run_drift_and_risk_pipeline(
            desired_state, actual_state, resource_type_hint, drift_frequency, artifacts
        )
        render_results(result, scenario_ground_truth, artifacts["int_to_label"])


def render_live_aws():
    import cloud_client

    cfg = cloud_client.load_config()
    st.subheader("Live findings from the deployed AWS stack")
    if not cfg["api_url"] or not cfg["client_id"]:
        st.info(
            "No deployed stack configured. After `terraform apply`, run "
            "`terraform output -json > outputs.json` inside `src/aws/terraform/`, "
            "or set IDG_API_URL and IDG_COGNITO_CLIENT_ID."
        )
        return
    st.caption(f"API: `{cfg['api_url']}` · region `{cfg['region']}`")

    if "id_token" not in st.session_state:
        with st.form("login"):
            username = st.text_input("Email")
            password = st.text_input("Password", type="password")
            new_password = st.text_input("New password (first sign-in only)", type="password")
            if st.form_submit_button("Sign in with Cognito"):
                try:
                    res = cloud_client.sign_in(cfg["region"], cfg["client_id"], username, password, new_password or None)
                except cloud_client.CloudError as e:
                    st.error(str(e))
                    return
                if res.get("challenge"):
                    st.warning("First sign-in: enter a new password in the third box and sign in again.")
                    return
                st.session_state["id_token"] = res["id_token"]
                st.rerun()
        return

    col1, col2, col3 = st.columns([1, 1, 4])
    if col1.button("Scan now"):
        try:
            cloud_client.call_api(cfg["api_url"], st.session_state["id_token"], "POST", "/scan")
            st.success("Scan started -- refresh in a few seconds.")
        except cloud_client.CloudError as e:
            st.error(str(e))
    col2.button("Refresh")
    if col3.button("Sign out"):
        del st.session_state["id_token"]
        st.rerun()

    try:
        findings = cloud_client.call_api(cfg["api_url"], st.session_state["id_token"], "GET", "/findings")["findings"]
    except cloud_client.CloudError as e:
        st.error(str(e))
        if "expired" in str(e):
            del st.session_state["id_token"]
        return

    if not findings:
        st.info("No scans recorded yet. Click **Scan now**.")
        return

    for f in sorted(findings, key=lambda x: x["resource_id"]):
        label = f["risk_label"] if f["has_drift"] else "No drift"
        color = RISK_COLORS.get(label, "#7f8c8d")
        with st.container(border=True):
            st.markdown(
                f"**{f['resource_type']}** · `{f['resource_id']}` &nbsp; "
                f"<span style='background:{color};color:white;padding:2px 8px;border-radius:4px'>{label}</span> "
                f"&nbsp; <small>scanned {f['detected_at']}</small>",
                unsafe_allow_html=True,
            )
            if f["has_drift"]:
                st.table(pd.DataFrame(f["changes"]).astype(str))
                if f.get("probabilities"):
                    render_probability_chart(f["probabilities"])
                if f.get("unmodelled_attributes"):
                    st.warning("Needs manual review: " + ", ".join(f["unmodelled_attributes"]))
                if f.get("remediation"):
                    st.success("Auto-remediated: " + "; ".join(f["remediation"]))


def main():
    st.set_page_config(page_title="InfraDriftGuard", layout="wide")
    render_sidebar()
    render_header()

    offline_tab, live_tab = st.tabs(["Drift analyzer (offline model)", "Live AWS findings"])
    with offline_tab:
        render_offline_analyzer()
    with live_tab:
        render_live_aws()


if __name__ == "__main__":
    main()
