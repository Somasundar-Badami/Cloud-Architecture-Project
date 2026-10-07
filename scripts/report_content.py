"""
report_content.py -- all written content for the Phase-I documents.
Kept separate from the .docx formatting code (build_docs.py) so the text
can be edited without touching layout logic.

Fill in TEAM before submission.
"""

TEAM = {
    "project_title": "InfraDriftGuard: AI-Based Infrastructure Configuration Drift Detection and "
                     "Risk Classification on AWS using Explainable Machine Learning",
    "short_name": "InfraDriftGuard",
    "repo": "InfraDriftGuard_Cloud_Project_2026",
    "course": "BCSE355L – Cloud Architecture Design",
    "instructor": "Dr. Priya V",
    "students": [
        {"id": "Student 1", "name": "Keshav Khandelwal", "reg": "24BIT0461", "papers": (1, 8)},
        {"id": "Student 2", "name": "Somasundar Shivappa Badami", "reg": "24BIT0465", "papers": (9, 15)},
    ],
}

ABSTRACT = (
    "Infrastructure as Code (IaC) tools such as Terraform declare cloud infrastructure in "
    "version-controlled files, but the live environment rarely stays identical to that declaration. Manual "
    "console edits, emergency fixes and automation side-effects cause configuration drift, and drift in "
    "security-sensitive settings – a public S3 bucket, SSH opened to the internet, an IAM role escalated to "
    "wildcard permissions – is one of the leading causes of cloud data breaches. "
    "Existing tools have three shortcomings: static IaC scanners inspect only the code and never see the live "
    "account; native drift checks (terraform plan, AWS Config) report that something changed but not how "
    "dangerous the change is; and the few machine-learning approaches published so far are black boxes that "
    "operators cannot audit. "
    "This project proposes InfraDriftGuard, a serverless drift detection and risk classification system on AWS. "
    "Terraform renders the desired state of every monitored resource; an AWS Lambda function, triggered hourly "
    "by Amazon EventBridge, collects the live configuration of S3 buckets, EC2 security groups and IAM roles "
    "through read-only APIs, normalises it, computes an attribute-level diff, and converts each change into "
    "nine security features. A Random Forest classifier, trained on a 711-record dataset covering 20 drift "
    "scenarios and exported to a dependency-free JSON model, assigns a Low/Medium/High/Critical risk, while "
    "SHAP explains which features drove each prediction. Changes the model was never trained on are labelled "
    "“Review” instead of guessed. Findings are stored in Amazon DynamoDB, High/Critical drift triggers "
    "Amazon SNS e-mail alerts, two unambiguous Critical patterns can be auto-remediated, and results are served "
    "through Amazon API Gateway secured by Amazon Cognito to a Streamlit dashboard. Amazon CloudWatch provides "
    "logs, metrics, alarms and a dashboard, and AWS Budgets guards the free-tier cost. "
    "AWS services used: Lambda, EventBridge, S3, EC2, IAM, DynamoDB, SNS, API Gateway, "
    "Cognito, CloudWatch and Budgets."
)

# ---------------------------------------------------------------------------
# Literature survey -- 15 papers, 2023-2026. Every entry was checked against
# the publisher / conference listing. Columns follow the course template:
# Paper | Method | Dataset | Advantages | Limitations | Research Gap
# ---------------------------------------------------------------------------
PAPERS = [
    {
        "ref": "G. Thiyagarajan, V. Bist and P. Nayak, “AI-Driven Configuration Drift Detection in Cloud "
               "Environments,” International Journal of Communication Networks and Information Security "
               "(IJCNIS), vol. 16, no. 5, pp. 721–743, 2024. (Scopus indexed)",
        "short": "Thiyagarajan et al., IJCNIS 2024",
        "method": "ML models trained on historical and real-time configuration data from AWS Config logs and "
                  "Terraform state to flag drift; integrates with existing IaC pipelines.",
        "dataset": "AWS Config configuration-item history and Terraform state from cloud deployments.",
        "advantages": "Directly targets drift in AWS; uses live configuration, not only code; shows ML can "
                      "learn which configuration changes matter.",
        "limitations": "Relies on AWS Config (a paid service per recorded item); model decisions are not "
                       "explained to the operator; no per-change risk severity or automated response.",
        "gap": "Drift is detected but not ranked by security impact, and predictions are not explainable.",
        "improvement": "Classify each drift into a severity level and attach SHAP explanations; collect state "
                       "directly with read-only APIs to avoid AWS Config cost.",
    },
    {
        "ref": "M. M. Hassan, J. Salvador, S. K. Karmaker Santu and A. Rahman, “State Reconciliation Defects "
               "in Infrastructure as Code,” Proceedings of the ACM on Software Engineering (FSE), vol. 1, "
               "2024.",
        "short": "Hassan et al., ACM FSE 2024",
        "method": "Empirical study of defects in how IaC tools reconcile declared state with real state; "
                  "builds a taxonomy and a testing approach for state-reconciliation bugs.",
        "dataset": "Defect reports and code changes from Ansible, Terraform-style IaC projects and tools.",
        "advantages": "First systematic look at the gap between declared and actual state; explains why drift "
                      "arises even without human error.",
        "limitations": "Focuses on finding bugs in the IaC tools themselves, not on monitoring production "
                       "accounts or rating the risk of a given drift.",
        "gap": "No runtime component that continuously checks real cloud resources against the declared state.",
        "improvement": "Run a scheduled detector in the cloud that compares Terraform-rendered desired state "
                       "with live configuration.",
    },
    {
        "ref": "S. Abuzakuk, L. Crijns, A.-M. Kermarrec, R. Pires and M. de Vos, “RIVA: Leveraging LLM Agents "
               "for Reliable Configuration Drift Detection,” ACM, 2026 (arXiv:2603.02345).",
        "short": "Abuzakuk et al. (RIVA), ACM 2026",
        "method": "Multi-agent LLM system (verifier agent + tool-generation agent) that cross-validates tool "
                  "outputs to verify that deployed systems match their IaC specification.",
        "dataset": "IaC verification tasks with injected unreliable/incorrect tool responses.",
        "advantages": "Robust to misleading tool output; raises task success from 27.3% to 50.0% over a ReAct "
                      "baseline when tools are unreliable.",
        "limitations": "Even the best configuration solves only about half of the tasks; LLM inference is "
                       "costly and non-deterministic; no severity rating of detected drift.",
        "gap": "Accurate, cheap and deterministic drift checking with a quantified risk is still missing.",
        "improvement": "Use a deterministic diff engine for detection and a lightweight, explainable "
                       "classifier only for risk scoring.",
    },
    {
        "ref": "J. Wen, Z. Chen, Z. Zhu, F. Sarro, Y. Liu, H. Ping and S. Wang, “LLM-Based Misconfiguration "
               "Detection for AWS Serverless Computing,” ACM Transactions on Software Engineering and "
               "Methodology (TOSEM), vol. 35, no. 4, art. 110, 2026.",
        "short": "Wen et al. (SlsDetector), ACM TOSEM 2026",
        "method": "SlsDetector: zero-shot prompt-engineered LLM that inspects AWS SAM templates for "
                  "misconfigurations.",
        "dataset": "Real-world AWS SAM serverless application configurations.",
        "advantages": "No training data needed; precision 72.88%, recall 88.18%, F1 79.75%, beating data-driven "
                      "baselines.",
        "limitations": "Analyses templates before deployment only; about one in four alarms is a false "
                       "positive; requires an external LLM API.",
        "gap": "Misconfigurations introduced after deployment (outside the template) are invisible to it.",
        "improvement": "Monitor the live account after deployment and compare it to the template's intent.",
    },
    {
        "ref": "A. Rahman, S. I. Shamim, D. B. Bose and R. Pandita, “Security Misconfigurations in Open Source "
               "Kubernetes Manifests: An Empirical Study,” ACM Transactions on Software Engineering and "
               "Methodology (TOSEM), vol. 32, no. 4, 2023.",
        "short": "Rahman et al., ACM TOSEM 2023",
        "method": "Qualitative analysis of 2,039 Kubernetes manifests from 92 repositories; builds the SLI-KUBE "
                  "static linter for 11 misconfiguration categories; logistic regression on code metrics.",
        "dataset": "2,039 manifests (GitHub 1,590 + GitLab 449) from 92 open-source repositories.",
        "advantages": "Large real-world dataset; identified 1,051 misconfigurations; practitioners agreed to fix "
                      "60% of reported issues. (This is the base paper replicated by our team.)",
        "limitations": "Static analysis of manifests only; binary present/absent output with no severity; "
                       "Kubernetes-specific.",
        "gap": "Severity of each misconfiguration and its appearance at runtime are not addressed.",
        "improvement": "Extend from static manifests to live AWS resources and grade each finding by risk.",
    },
    {
        "ref": "N. Saavedra, J. Gonçalves, M. Henriques, J. F. Ferreira and A. Mendes, “Polyglot Code Smell "
               "Detection for Infrastructure as Code with GLITCH,” Proc. 38th IEEE/ACM Int. Conf. on "
               "Automated Software Engineering (ASE), Tool Demonstrations, 2023.",
        "short": "Saavedra et al. (GLITCH), IEEE/ACM ASE 2023",
        "method": "Technology-agnostic intermediate representation of IaC scripts with rule-based detectors for "
                  "9 security smells and 9 design smells.",
        "dataset": "IaC scripts in Ansible, Chef, Docker, Puppet and Terraform.",
        "advantages": "One analyser for five IaC languages; consistent rules across technologies.",
        "limitations": "Rule-based and static; cannot see changes made outside the code; no learned "
                       "prioritisation.",
        "gap": "No link between code-level smells and the state actually running in the cloud.",
        "improvement": "Use a common normalised schema for live resources, analogous to GLITCH's IR for code.",
    },
    {
        "ref": "R. Opdebeeck, A. Zerouali and C. De Roover, “Control and Data Flow in Security Smell Detection "
               "for Infrastructure as Code: Is It Worth the Effort?,” Proc. 20th IEEE/ACM Int. Conf. on Mining "
               "Software Repositories (MSR), 2023.",
        "short": "Opdebeeck et al. (GASEL), IEEE/ACM MSR 2023",
        "method": "GASEL: graph queries over program dependence graphs of Ansible code to detect 7 security "
                  "smells with control- and data-flow awareness.",
        "dataset": "More than 15,000 Ansible scripts; oracle of 243 real security smells.",
        "advantages": "Substantially better precision and recall than earlier detectors; shows that 55% of "
                      "smells involve data-flow indirection.",
        "limitations": "Ansible-only; static; high analysis cost (32% of smells need whole-project analysis).",
        "gap": "Effort is spent on deeper static analysis while runtime drift remains undetected.",
        "improvement": "Complement static analysis with cheap runtime state comparison.",
    },
    {
        "ref": "A. Verdet, M. Hamdaqa, L. M. P. Da Silva and F. Khomh, “Assessing the adoption of security "
               "policies by developers in Terraform across different cloud providers,” Empirical Software "
               "Engineering (Springer), vol. 30, no. 3, 2025.",
        "short": "Verdet et al., Springer EMSE 2025",
        "method": "Mined 812 open-source Terraform projects and checked them against security policies for AWS, "
                  "Azure and Google Cloud.",
        "dataset": "812 GitHub Terraform projects.",
        "advantages": "Cross-provider evidence of which security practices developers adopt or neglect "
                      "(e.g. encryption, access control, logging).",
        "limitations": "Measures what is written in code, not what is deployed; no remediation.",
        "gap": "Even code that follows the policies can drift once deployed; this is not measured.",
        "improvement": "Use the same policy areas (public access, encryption, IAM) as the features of a "
                       "runtime drift classifier.",
    },
    {
        "ref": "N. Saavedra, J. F. Ferreira and A. Mendes, “InfraFix: Technology-Agnostic Repair of "
               "Infrastructure as Code,” Proc. 34th ACM SIGSOFT Int. Symposium on Software Testing and "
               "Analysis (ISSTA), Tool Demonstrations, 2025.",
        "short": "Saavedra et al. (InfraFix), ACM ISSTA 2025",
        "method": "SMT-based repair module plus system-call-based state inference to repair IaC scripts.",
        "dataset": "254,288 generated repair scenarios.",
        "advantages": "95.7% repair success; technology-agnostic; considers the observed system state.",
        "limitations": "Repairs the script, not the running resource; evaluated on synthetic scenarios.",
        "gap": "No safe, policy-limited remediation of the live cloud resource itself.",
        "improvement": "Offer opt-in, narrowly scoped auto-remediation only for unambiguous Critical drift.",
    },
    {
        "ref": "E. Low, B. Chen et al., “Repairing Infrastructure-as-Code using Large Language Models,” Proc. "
               "IEEE Secure Development Conference (SecDev), 2024.",
        "short": "Low, Chen et al., IEEE SecDev 2024",
        "method": "Feeds scanner findings, IaC code and human context to GPT-4 in a two-pass prompt to generate "
                  "repaired IaC.",
        "dataset": "Vulnerable open-source IaC repositories scanned with existing misconfiguration scanners.",
        "advantages": "Removes up to 84.7% of scanner alarms; two-pass prompting clearly beats one-pass.",
        "limitations": "20.4% of suggested fixes were hallucinated; needs a human in the loop; no risk ranking.",
        "gap": "Fixes are not prioritised and are not verified against the deployed state.",
        "improvement": "Rank findings by predicted risk first and only automate fixes that are deterministic.",
    },
    {
        "ref": "M. Begoug, M. Chouchen, A. Ouni, E. A. AlOmar and M. W. Mkaouer, “Fine-Grained Just-In-Time "
               "Defect Prediction at the Block Level in Infrastructure-as-Code (IaC),” Proc. 21st IEEE/ACM "
               "Int. Conf. on Mining Software Repositories (MSR), pp. 100–112, 2024.",
        "short": "Begoug et al., IEEE/ACM MSR 2024",
        "method": "Six ML algorithms (LightGBM best) predict defective Terraform blocks from code, process and "
                  "change metrics.",
        "dataset": "19 open-source Terraform projects.",
        "advantages": "Block-level granularity; shows ML can prioritise risky IaC changes (AUC 0.71).",
        "limitations": "Low MCC (0.21); predicts defects in commits, not security impact of live changes; "
                       "limited explainability.",
        "gap": "No ML model that predicts the security severity of a configuration change in the live cloud.",
        "improvement": "Train a classifier on security-oriented features of each drift and explain it.",
    },
    {
        "ref": "M. Begoug, M. Chouchen and A. Ouni, “TerraMetrics: An Open Source Tool for Infrastructure-as-Code "
               "(IaC) Quality Metrics in Terraform,” Proc. 32nd IEEE/ACM Int. Conf. on Program Comprehension "
               "(ICPC), Tool Demonstrations, 2024.",
        "short": "Begoug et al. (TerraMetrics), IEEE/ACM ICPC 2024",
        "method": "Parses Terraform HCL into an AST and extracts a catalogue of 40 quality metrics as JSON.",
        "dataset": "Terraform projects (tool paper; metrics catalogue).",
        "advantages": "Reusable, open-source feature extractor for Terraform; well-defined metrics.",
        "limitations": "Quality metrics of code only; nothing about security impact or runtime state.",
        "gap": "No equivalent feature catalogue for drift between Terraform and live AWS resources.",
        "improvement": "Define a fixed, documented feature schema for drift (our nine features).",
    },
    {
        "ref": "G. Rjoub et al., "
               "“A Survey on Explainable Artificial Intelligence for Cybersecurity,” IEEE Transactions on "
               "Network and Service Management, vol. 20, no. 4, pp. 5115–5140, 2023.",
        "short": "Rjoub et al., IEEE TNSM 2023",
        "method": "Survey of XAI techniques (SHAP, LIME, rule extraction, attention) applied to intrusion, "
                  "malware and fraud detection.",
        "dataset": "Survey of published XAI-for-security studies.",
        "advantages": "Argues that security analysts need explanations to trust and act on ML alerts; maps "
                      "techniques to use cases.",
        "limitations": "Cloud configuration management is not covered; no implementation.",
        "gap": "XAI has not been applied to configuration drift risk on cloud platforms.",
        "improvement": "Attach SHAP explanations to every drift risk prediction.",
    },
    {
        "ref": "V. Z. Mohale and I. C. Obagbuwa, “A systematic review on the integration of explainable "
               "artificial intelligence in intrusion detection systems to enhancing transparency and "
               "interpretability in cybersecurity,” Frontiers in Artificial Intelligence, vol. 8, 2025, "
               "doi:10.3389/frai.2025.1526221.",
        "short": "Mohale & Obagbuwa, Frontiers in AI 2025",
        "method": "Systematic literature review of XAI methods in intrusion detection systems.",
        "dataset": "Peer-reviewed IDS + XAI studies (systematic review).",
        "advantages": "Finds tree-based and rule-based models with SHAP preferred for interpretability; "
                      "identifies need for real-time explainability.",
        "limitations": "Network IDS focus; notes trade-off between accuracy and interpretability but proposes "
                       "no system.",
        "gap": "Real-time, explainable tree-based classification in a cloud operations pipeline.",
        "improvement": "Use a Random Forest + TreeSHAP and run inference inside the detection Lambda.",
    },
    {
        "ref": "S. M. Saleh, I. M. Sayem, N. Madhavji and J. Steinbacher, “Advancing Software Security and "
               "Reliability in Cloud Platforms through AI-based Anomaly Detection,” Proc. ACM Cloud Computing "
               "Security Workshop (CCSW), 2024.",
        "short": "Saleh et al., ACM CCSW 2024",
        "method": "CNN + LSTM model detects anomalous network traffic in CI/CD pipelines and cloud platforms.",
        "dataset": "Network traffic data from pipeline and cloud environments.",
        "advantages": "High accuracy (98.69% and 98.30%) for traffic anomalies in DevOps pipelines.",
        "limitations": "Deep models are opaque; looks at traffic, not configuration; heavy to deploy "
                       "serverlessly.",
        "gap": "Configuration-level security changes are not monitored; model is not explainable.",
        "improvement": "Watch configuration rather than traffic, with a light, explainable model.",
    },
]

SURVEY_SUMMARY = (
    "The fifteen papers fall into four groups. (1) Static IaC analysis – GLITCH, GASEL, SLI-KUBE, "
    "TerraMetrics, Verdet et al. and SlsDetector – finds misconfigurations in code before deployment, but "
    "cannot see changes made afterwards. (2) Drift and state reconciliation – Thiyagarajan et al., Hassan et "
    "al. and RIVA – confirm that drift is real and common, but either do not rate how dangerous a drift is or "
    "rely on costly, non-deterministic LLM agents. (3) Automated repair – InfraFix and LLM-based repair – fix "
    "scripts, sometimes with hallucinated changes, and do not act on the live resource. (4) ML and "
    "explainability for security – Begoug et al., Saleh et al., Rjoub et al. and Mohale & Obagbuwa – show that "
    "ML can prioritise risk and that analysts need explanations, yet none of them combines these with live "
    "cloud configuration. InfraDriftGuard sits at the intersection: runtime drift detection on real AWS "
    "resources, a per-change risk level from an explainable model, and a serverless, low-cost response path."
)

COMBINED_GAP = [
    "Static scanners never observe the deployed account, so post-deployment drift goes unnoticed.",
    "Drift detectors report that something changed, but not how severe it is, so every alert looks equally "
    "urgent.",
    "ML-based approaches are opaque; none explains which property of the change made it risky.",
    "LLM-based approaches are expensive, non-deterministic and hallucinate a measurable share of their output.",
    "Automated responses either do not exist or rewrite code; safe, scoped remediation of the live resource "
    "is missing.",
    "No published system is designed to run within free-tier/serverless cost limits for small teams and "
    "students.",
]

OBJECTIVES = [
    ("Detect drift continuously",
     "Compare the Terraform-declared desired state with the live configuration of S3 buckets, EC2 security "
     "groups and IAM roles every hour (and on demand), detecting 100% of the 21 supported attribute changes in "
     "the automated test suite."),
    ("Classify risk accurately",
     "Assign each drift a Low/Medium/High/Critical risk with a Random Forest classifier, reaching at least 95% "
     "macro-F1 on held-out records, and report the harder scenario-held-out score honestly alongside it."),
    ("Explain every prediction",
     "Provide SHAP global and local explanations whose values add up exactly to the model output "
     "(additivity error below 1e-6) so an operator can see why a change was rated Critical."),
    ("Respond automatically and safely",
     "Send an SNS e-mail for every High/Critical drift within one scan cycle, store every finding in DynamoDB, "
     "and optionally auto-revert the two Critical patterns that have a single safe fix."),
    ("Secure access and observability",
     "Expose findings only through an API Gateway endpoint protected by Cognito JWT authentication, and monitor "
     "the pipeline with CloudWatch logs, metrics, alarms and a dashboard."),
    ("Stay inside the AWS free tier",
     "Keep the full deployment under US$1 per month (enforced by an AWS Budgets alarm) by running inference in "
     "a dependency-free Lambda package of under 1 MB."),
]

NOVELTY = [
    ("Better architecture – runtime, not just code",
     "Unlike static scanners (GLITCH, GASEL, SLI-KUBE, SlsDetector), InfraDriftGuard checks the live AWS account "
     "against the Terraform-rendered desired state, catching console edits and emergency changes made after "
     "deployment."),
    ("New feature – risk level for every drift",
     "Instead of a binary “drift / no drift” (terraform plan, AWS Config, Thiyagarajan et al.), each "
     "change is converted into nine security features (public exposure, encryption change, privilege change, "
     "port exposure, sensitivity, magnitude, frequency, resource type, attribute) and classified into four risk "
     "levels."),
    ("Better explainability",
     "SHAP TreeExplainer gives exact (additivity error ≈ 1e-16) global and per-finding explanations, "
     "answering the gap raised by the XAI surveys of Rjoub et al. and Mohale & Obagbuwa."),
    ("Better reliability – no guessing",
     "Changes outside the model's knowledge base are labelled “Review” and escalated, rather than "
     "forced into a class – a direct response to the hallucination and false-positive problems of LLM-based "
     "approaches."),
    ("Better AWS integration and automation",
     "A fully serverless pipeline – EventBridge → Lambda → DynamoDB / SNS / CloudWatch, with API "
     "Gateway + Cognito for access – deployed by one Terraform command, with opt-in auto-remediation limited to "
     "two deterministic fixes (re-enable S3 public-access block; revoke 0.0.0.0/0 on SSH/RDP)."),
    ("Better cost and scalability",
     "The 200-tree Random Forest is exported to a 210 KB JSON file and evaluated in pure Python, giving "
     "bit-identical predictions to scikit-learn on all 711 records with no ML libraries in Lambda. The whole "
     "stack runs within the free tier and scales by simply adding resources to the desired-state list."),
    ("Better security of the tool itself",
     "Each Lambda has its own least-privilege IAM role; collection is read-only; write permissions for "
     "remediation exist only when the feature is switched on and are scoped to the specific resources."),
]

DATASET = {
    "name": "InfraDriftGuard Synthetic Cloud Configuration Drift Dataset (v1.0)",
    "source": "Generated by this project (src/backend/dataset_generator.py) from 20 expert-defined drift "
              "scenarios modelled on AWS security best practices and CIS AWS Foundations Benchmark controls.",
    "url": "GitHub repository: dataset/processed/dataset.csv and dataset/raw/raw_records.json "
           "(InfraDriftGuard_Cloud_Project_2026)",
    "size": "dataset.csv ≈ 68 KB; raw_records.json ≈ 1.3 MB",
    "records": "711 records (Low 180, Medium 176, High 175, Critical 180)",
    "features": "9 input features + 1 label (plus 3 metadata columns: record_id, scenario_id, group_id)",
    "types": "Categorical (resource_type, changed_attribute, security_sensitivity, change_magnitude, "
             "port_exposure), Boolean (public_exposure, encryption_change, privilege_change), Integer "
             "(drift_frequency); label: ordinal categorical (Low < Medium < High < Critical). Raw file: nested "
             "JSON desired/actual states.",
    "license": "MIT License (same as the repository); contains no personal or customer data.",
    "purpose": "Train and evaluate the drift risk classifier and SHAP explanations. Public datasets of labelled "
               "configuration drift do not exist (real drift data is private to each organisation), so a "
               "controlled synthetic dataset with documented ground-truth rules is used, and the live AWS "
               "pipeline is validated separately.",
    "preprocessing": [
        "Read with keep_default_na=False so the literal category “None” (no-drift control) is not "
        "turned into a missing value.",
        "Drop metadata columns (record_id, scenario_id, group_id) to prevent the model memorising scenarios.",
        "Ordinal-encode security_sensitivity, change_magnitude and port_exposure in severity order.",
        "One-hot encode resource_type and changed_attribute (unknown categories ignored at inference).",
        "Cast Booleans to 0/1; pass drift_frequency through unchanged.",
        "Encode the label with a fixed severity order (Low=0 … Critical=3).",
        "Two splits: stratified random 80/20 (568/143) and scenario-group-aware (592/119) to measure leakage.",
    ],
    "scenarios": [
        ("S1", "S3", "Public access block disabled", "Critical"),
        ("S2", "S3", "Bucket ACL changed to public-read", "Critical"),
        ("S3id", "S3", "Server-side encryption disabled", "High"),
        ("S4", "S3", "Bucket policy principal widened to *", "Critical"),
        ("S5", "S3", "Versioning disabled", "Medium"),
        ("S6", "S3", "Access logging disabled", "Medium"),
        ("S7", "S3", "Lifecycle/retention rule removed", "Low"),
        ("E1", "Security group", "SSH (22) opened to 0.0.0.0/0", "Critical"),
        ("E2", "Security group", "RDP (3389) opened to 0.0.0.0/0", "Critical"),
        ("E3", "Security group", "New port opened publicly", "High"),
        ("E4", "Security group", "Outbound widened to allow-all", "High"),
        ("E5", "Security group", "No change (control)", "Low"),
        ("E6", "Security group", "Internal port widened to a range", "Medium"),
        ("E7", "Security group", "Cross-SG reference added", "Medium"),
        ("I1", "IAM", "Policy escalated to Action:* Resource:*", "Critical"),
        ("I2", "IAM", "Cross-account trust added", "Critical"),
        ("I3", "IAM", "MFA condition removed", "High"),
        ("I4", "IAM", "Explicit Deny flipped to Allow", "Critical"),
        ("I5", "IAM", "Group membership escalated to admin", "Critical"),
        ("I6", "IAM", "Permissions boundary removed", "High"),
    ],
}

AWS_SERVICES = [
    ("AWS Lambda", "Runs the drift detector (collect, diff, features, Random Forest, alert, remediate) and the "
     "REST API handler.", "1M requests + 400,000 GB-s / month (always free)"),
    ("Amazon EventBridge", "Hourly schedule that triggers the detector.", "Scheduled rules free"),
    ("Amazon S3", "Monitored demo bucket (public-access block, encryption, ACL, versioning).", "Empty bucket ≈ $0"),
    ("Amazon EC2 (Security Groups)", "Monitored firewall rules (SSH/RDP/HTTPS/PostgreSQL).",
     "Security groups are free"),
    ("AWS IAM", "Monitored application role; least-privilege roles for both Lambdas; permissions boundary.",
     "Free"),
    ("Amazon DynamoDB", "Stores every finding; history gives the drift_frequency feature.",
     "25 GB + 25 RCU/WCU (always free); table uses 1/1"),
    ("Amazon SNS", "E-mail alerts for High/Critical/Review drift and CloudWatch alarms.",
     "1,000 e-mails / month free"),
    ("Amazon API Gateway (HTTP API)", "Authenticated REST endpoints: GET /findings, GET /findings/{id}, "
     "POST /scan; throttled.", "≈ $1 per million requests; demo usage ≈ $0"),
    ("Amazon Cognito", "User pool and JWT tokens for dashboard sign-in; admin-created users only.",
     "10,000 MAU free (Lite tier)"),
    ("Amazon CloudWatch", "Lambda logs (7-day retention), custom DriftDetected metric, 2 alarms, dashboard.",
     "10 alarms, 3 dashboards, 5 GB logs free"),
    ("AWS Budgets", "US$1 monthly budget with e-mail alerts at 50% actual / 100% forecast.",
     "First 2 budgets free"),
    ("Terraform (IaC, not an AWS service)", "Provisions all of the above and renders the desired state.",
     "Free, open source"),
]

CONTRIBUTIONS = [
    ("Literature survey", "Papers 1–8", "Papers 9–15"),
    ("Research gap analysis", "Papers 1–8", "Papers 9–15"),
    ("Dataset generation & validation", "✓", ""),
    ("ML model training & evaluation audit", "", "✓"),
    ("SHAP explainability", "", "✓"),
    ("Drift engine & feature extraction (backend)", "✓", ""),
    ("AWS collectors & Lambda handlers", "✓", "✓"),
    ("Terraform infrastructure", "✓", ""),
    ("Streamlit frontend & Cognito/API client", "", "✓"),
    ("Testing", "✓", "✓"),
    ("Documentation & architecture diagrams", "✓", "✓"),
    ("Presentation", "✓", "✓"),
]
