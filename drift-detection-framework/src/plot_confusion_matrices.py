"""
plot_confusion_matrices.py

Renders the confusion matrices saved in results/confusion_matrices.json as
PNG images for the report. Purely a visualization step -- reads already-
computed results, does not retrain or re-evaluate anything.

Run after ml_pipeline.py has been run at least once.
"""

import json
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

_THIS_DIR = os.path.dirname(__file__)
RESULTS_DIR = os.path.join(_THIS_DIR, "..", "results")
CM_JSON_PATH = os.path.join(RESULTS_DIR, "confusion_matrices.json")


def plot_confusion_matrix(cm, labels, title, out_path):
    cm = np.array(cm)
    fig, ax = plt.subplots(figsize=(5, 4.5))
    im = ax.imshow(cm, cmap="Blues")

    ax.set_xticks(range(len(labels)))
    ax.set_yticks(range(len(labels)))
    ax.set_xticklabels(labels)
    ax.set_yticklabels(labels)
    ax.set_xlabel("Predicted label")
    ax.set_ylabel("True label")
    ax.set_title(title, fontsize=10)

    for i in range(len(labels)):
        for j in range(len(labels)):
            value = cm[i, j]
            color = "white" if value > cm.max() / 2 else "black"
            ax.text(j, i, str(value), ha="center", va="center", color=color)

    fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)


def main():
    with open(CM_JSON_PATH) as f:
        data = json.load(f)

    plots = [
        ("split_A_stratified_random", "random_forest", "Random Forest — Split A (Stratified Random)"),
        ("split_A_stratified_random", "decision_tree", "Decision Tree — Split A (Stratified Random)"),
        ("split_B_scenario_group_aware", "random_forest", "Random Forest — Split B (Scenario-Group-Aware)"),
        ("split_B_scenario_group_aware", "decision_tree", "Decision Tree — Split B (Scenario-Group-Aware)"),
    ]

    for split_key, model_key, title in plots:
        cm = data[split_key][model_key]
        labels = data[split_key]["labels"]
        out_path = os.path.join(RESULTS_DIR, f"confusion_matrix_{split_key}_{model_key}.png")
        plot_confusion_matrix(cm, labels, title, out_path)
        print(f"Wrote: {out_path}")


if __name__ == "__main__":
    main()
