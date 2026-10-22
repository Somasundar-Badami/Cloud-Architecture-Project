# InfraDriftGuard on REAL data (no synthetic records)

## What the data is, in one line
**8,395 real AWS misconfigurations** found in the actual Terraform code (and its git history) of **76 public GitHub repositories**. These include real production infrastructure run by UK GOV.UK (alphagov), the UK Ministry of Justice, US CISA, US GSA/18F (cloud.gov), US CMS, NASA Cumulus, Canada's CDS, Wellcome Collection and UK Trade, plus popular open-source modules (terraform-aws-modules, cloudposse). Nothing is generated. Every row points to a real `repo + commit + file + line`, so anyone can open it on GitHub and check.

## Why not the other datasets
| Candidate | Verdict |
|---|---|
| HF `Snaseem2026/iac-drift-pairs` | Rejected. Every row has `observed_source = "simulated"`, and all ~3k rows come from 16 templates. It's synthetic. |
| Our old 711 / 1,238 sets | Synthetic, and the labels were our own judgement. |
| TerraDS (MSR 2025, Zenodo) | Real Terraform code but no labels, and Zenodo is blocked from my sandbox. Same idea as what we did. |
| Rahman K8s manifests (paper 5), GLITCH (paper 6) | Real, but Kubernetes/Ansible/Chef/Puppet smells, not AWS resources. Poor fit for our 9 features. |
| Kaggle "cloud security" sets | Mostly simulated logs or network traffic, not configs. |

## Where the labels come from (important for viva)
We **do not** decide Low/Medium/High/Critical any more.

1. **`risk_label`**: the severity that **tfsec (Aqua Security)** publishes for each check (LOW/MEDIUM/HIGH/CRITICAL). It's fixed by the vendor, the same for everyone, and documented at aquasecurity.github.io/tfsec. *Honest note: this is still expert judgement, but it's an industry vendor's published judgement, not ours.*
2. **`fixed_later`**: **measured from real behaviour**. We scanned up to 8 points in each repo's history. If a finding disappears later while the resource still exists, the real developers fixed it (1). If it's still there at the newest snapshot, it's 0. Nobody "decides" this; git shows it.

Neither label is computed from the 9 features by any formula we wrote, so the model can't just learn our rule back (that was the problem with the old `risk_rule_check.py`).

## How each of the 9 features is filled (what's real vs our mapping)
| Feature | Source | Real or our mapping? |
|---|---|---|
| resource_type | Terraform type in the real code (e.g. `aws_s3_bucket`) | Real |
| changed_attribute | Attribute on the flagged line (e.g. `cidr_blocks`), or `resource_block` when a setting is missing | Real |
| security_sensitivity | Fixed table by service: data/identity High, network/compute Medium, rest Low | Our mapping (depends on type only) |
| public_exposure | Keywords in the check text, plus `0.0.0.0/0`, `public-read`, `publicly_accessible = true` in the real block | Keyword mapping on real text |
| encryption_change | Keywords (encrypt, kms, tls, https...) | Keyword mapping |
| privilege_change | Keywords (iam, policy, wildcard, mfa, admin...) | Keyword mapping |
| port_exposure | Real block contains 0.0.0.0/0 or ::/0, or private ranges, or neither | Real |
| change_magnitude | `git blame`: share of the block written by its latest commit | Real (measured) |
| drift_frequency | `git blame`: number of different commits that wrote the block | Real (measured) |

Each record is a misconfiguration *introduced by a real code change*. It is not live-cloud drift captured from someone's AWS account, because nobody publishes that data. Say this if asked.

## Results (Random Forest, 300 trees, class_weight=balanced)
| Split | What it tests | Macro-F1 | Accuracy |
|---|---|---|---|
| A: random 5-fold | Leaky, for comparison only | 0.888 | 0.897 |
| **B: unseen repositories** (GroupKFold by repo) | Works on a new company's code? **Main number** | **0.878** (0.85 to 0.92 across folds) | 0.897 |
| B without the 2 deliberately-vulnerable repos (terragoat, cloudgoat) | Same as B, cleaner | 0.890 | 0.904 |
| C: unseen check types (GroupKFold by tfsec check) | Can it guess the severity of a kind of misconfig it has never seen? | 0.385 (0.19 to 0.53) | 0.492 |
| Random guessing baseline | | about 0.24 | |

Confusion matrices: `results/confusion_*.png`. SHAP: `results/shap_importance.png`, `results/shap_summary_critical.png`.

**SHAP order:** resource_type > changed_attribute > public_exposure > security_sensitivity > encryption_change > port_exposure > privilege_change >> drift_frequency, change_magnitude.

**Second model (`fixed_later`, measured label), unseen repos:** macro-F1 0.505, ROC-AUC 0.576, so only a little better than chance (0.5). Fix rate by tfsec severity: Critical 33%, High 37%, Medium 26%, Low 35%. In real repos, developers don't fix things in severity order.

### How to read these numbers honestly
- B is about 0.88 because the same *kinds* of misconfiguration (open SG, unencrypted bucket...) show up in every company. The model learns "this kind of change has this tfsec severity" and that carries over to new repos. It's a good result, but part of it is the model learning tfsec's severity table.
- C (about 0.39) is the hard, honest test. For a brand-new kind of misconfiguration, our 9 features only partly predict the severity. This matches the old project's "unseen scenarios" finding.
- drift_frequency and change_magnitude barely matter for *severity*. That makes sense: how often a block changes doesn't make it more dangerous.

## Files
- `real_iac_findings.csv`: the dataset (9 features + 2 labels + provenance columns: repo, commit, file, line, rule_id, check)
- `results/metrics.json`: every number above, with confusion matrices
- `raw/`: list of cloned repos with exact commits, snapshot index, and all raw tfsec JSON (re-checkable)
- `src/scan_history.py` → `src/build_dataset.py` → `src/train_real.py`

## Re-run on your laptop
Needs git, tfsec (`choco install tfsec`, or the binary from GitHub releases), and `pip install scikit-learn shap pandas matplotlib`.
1. Clone the repos listed in `raw/repos_cloned.txt` into one folder (e.g. `D:\Coding\real_repos`, folder names `owner_repo`)
2. `python src/scan_history.py D:\Coding\real_repos scans 8`
3. `python src/build_dataset.py D:\Coding\real_repos scans real_iac_findings.csv`
4. `python src/train_real.py real_iac_findings.csv results`

The repos keep changing, so a fresh run gives slightly different counts. The CSV here is the frozen version (scanned 2026-10-22, tfsec v1.28.11).
