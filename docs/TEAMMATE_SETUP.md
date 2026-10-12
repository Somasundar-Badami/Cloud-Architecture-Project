# Running InfraDriftGuard on your own laptop

This guide takes a Windows laptop from nothing to running and testing the whole project. Run each command in **PowerShell**, one at a time.

---

## 1. Install the tools (one time)

| Tool | Download | Notes |
|---|---|---|
| Git | https://git-scm.com/download/win | Default options are fine |
| Python 3.12+ | https://www.python.org/downloads/ | **Tick "Add python.exe to PATH"** on the first screen |
| VS Code (optional) | https://code.visualstudio.com/ | For reading and editing the code |

Close and reopen PowerShell, then check:

```bash
git --version
python --version
```

## 2. Get the project

```bash
cd C:\
git clone https://github.com/Somasundar-Badami/Cloud-Architecture-Project.git
cd Cloud-Architecture-Project
```

If you already had an older copy of this repo, delete it and clone fresh, because the branch history was rewritten.

## 3. Create a virtual environment and install packages

The virtual environment keeps this project's packages separate from anything else on the laptop.

```bash
python -m venv venv
venv\Scripts\activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

`(venv)` now appears at the start of the prompt. **Run `venv\Scripts\activate` again every time you open a new PowerShell window.**

If activation fails with "running scripts is disabled", run this once, then activate again:

```bash
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

## 4. Run all the tests

```bash
python -m pytest tests -q
```

Expected: **218 passed, 1 skipped** in about a minute. The skipped test needs a real AWS account; everything else, including the full cloud pipeline, runs against a simulated AWS (moto) with no account needed.

## 5. Open the dashboard

```bash
python -m streamlit run src/frontend/app.py
```

The browser opens at http://localhost:8501. Stop it with **Ctrl + C**.

- **Drift analyzer** tab: works immediately. Pick a scenario (e.g. *S1 – Public access block disabled*), then click **Analyze Drift** to see the drift, the 9 features, the predicted risk and the SHAP explanation.
- **Live AWS findings** tab: see section 8.

Always start it with `python -m streamlit`, not just `streamlit`, so it uses the Python that has the packages.

## 6. Rebuild everything from scratch (optional)

Each step regenerates its outputs. Results are identical every time (fixed random seed), so `git status` should show no real changes afterwards.

```bash
python src/backend/dataset_generator.py        # dataset/ (711 records)
python src/backend/validate_dataset.py          # checks the dataset
python src/ml_model/ml_pipeline.py              # trains Random Forest + Decision Tree -> results/metrics.json
python src/ml_model/plot_confusion_matrices.py  # results/*.png
python src/ml_model/ml_evaluation_audit.py      # unseen-scenario audit
python src/ml_model/shap_explainability.py      # results/shap/
python src/ml_model/export_model.py             # model JSON used by AWS Lambda
python scripts/draw_architecture.py             # architecture/*.png
python scripts/build_docs.py                    # docs/*.docx
python scripts/build_presentation.py            # presentation/*.pptx
```

To change report text, edit `scripts/report_content.py` and run `build_docs.py`. **Don't hand-edit the .docx files**, because they get overwritten.

## 7. Where things are

| Folder | Contents |
|---|---|
| `src/backend/` | Drift engine (`drift_engine.py`), 9-feature extraction, scenarios, dataset generator |
| `src/ml_model/` | Training, evaluation audit, SHAP, model export, saved models |
| `src/aws/lambda/` | Code that runs in AWS Lambda (detector + API) |
| `src/aws/collectors/` | Reads S3 / security group / IAM settings from AWS |
| `src/aws/terraform/` | Builds the whole AWS stack |
| `src/frontend/` | Streamlit dashboard |
| `tests/` | 218 automated tests |
| `docs/` | Report and all Phase-I documents |

## 8. Live AWS findings (the deployed stack)

The AWS stack runs in **Somasundar's** AWS account. You don't need an AWS account to view it.

1. Ask Somasundar for the file **`outputs.json`** and put it in `src\aws\terraform\` (it has no secrets, only addresses).
2. Ask him to create your dashboard login; he'll send you an email and password.
3. Start the dashboard, open **Live AWS findings**, and sign in.
4. **Scan now** → wait 10 seconds → **Refresh**.

**Never run `terraform apply` or `terraform destroy` against his account.** Only one person should manage that stack. Terraform's state file exists only on his laptop, and a second copy would create duplicates or break things.

### Optional: deploy your own copy in your own AWS account

To test the full deployment yourself, you can create your own free AWS account (or use your own existing one) and deploy a separate copy. It's completely independent of his.

1. Install Terraform and the AWS CLI:
   ```bash
   winget install Hashicorp.Terraform
   winget install Amazon.AWSCLI
   ```
2. Create an IAM user with an access key, then run `aws configure`.
3. Check which region your account allows. Free-plan accounts can be locked to one region; the console URL shows it (e.g. `region=ap-southeast-2`).
4. Deploy:
   ```bash
   cd src\aws\terraform
   terraform init
   terraform apply -var="alert_email=you@example.com" -var="aws_region=YOUR_REGION"
   terraform output -json > outputs.json
   ```
5. Confirm the SNS email, then set a dashboard password:
   ```bash
   aws cognito-idp admin-set-user-password --region YOUR_REGION --user-pool-id <cognito_user_pool_id from outputs> --username you@example.com --permanent --password "YourPassw0rd!x"
   ```
6. **When finished:** `terraform destroy -var="alert_email=you@example.com" -var="aws_region=YOUR_REGION"`

## 9. Demo the drift detection (on whichever stack you use)

1. AWS Console → **EC2** → **Security Groups** → `drift-demo-sandbox-web-sg` → **Edit inbound rules** → **Add rule**: SSH, Anywhere-IPv4 → **Save rules**.
2. Dashboard → **Scan now** → wait 10 s → **Refresh**. The security group shows **Critical** and an alert email arrives.
3. Delete that rule, then scan again. It shows **No drift**.

Don't run `terraform apply` during the demo, because it removes the rule (Terraform fixes drift).

## 10. Contributing (Git workflow)

```bash
git checkout feature/student1          # your branch
git pull
# ...make changes...
python -m pytest tests -q              # make sure nothing broke
git add -A
git commit -m "short description of the change"
git push origin feature/student1
```

Then open a **Pull Request** on GitHub: `feature/student1` → `develop`. Somasundar reviews and merges it.

## Common problems

| Problem | Fix |
|---|---|
| `ModuleNotFoundError` | Activate the venv (`venv\Scripts\activate`) and use `python -m streamlit` |
| `python` opens the Microsoft Store | Reinstall Python with "Add to PATH" ticked, or turn off *App execution aliases* in Windows settings |
| Live tab says "No deployed stack configured" | `outputs.json` is missing from `src\aws\terraform\` |
| "Incorrect username or password" | Ask for a new password, which can be reset with `admin-set-user-password` |
| Terraform `explicit deny in a service control policy` | Your AWS account is region-locked; use `-var="aws_region=..."` with the allowed region |
