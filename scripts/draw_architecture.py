"""\ndraw_architecture.py -- renders the three diagrams in architecture/:

  AWS_Architecture.png      Diagram 1: how the AWS services interact
  System_Architecture.png   Diagram 2: complete system (offline ML + online detection)
  Workflow.png              One drift scan, step by step

Run:  python scripts/draw_architecture.py
"""

import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "architecture")

# AWS architecture-icon category colours
C = {
    "compute": "#ED7100", "storage": "#7AA116", "database": "#C925D1", "integration": "#E7157B",
    "security": "#DD344C", "network": "#8C4FFF", "mgmt": "#E7157B", "external": "#232F3E",
    "ml": "#01A88D", "neutral": "#5A6B86",
}
INK = "#16191F"


def setup(w, h, xmax, ymax, title):
    fig, ax = plt.subplots(figsize=(w, h), dpi=200)
    ax.set_xlim(0, xmax)
    ax.set_ylim(0, ymax)
    ax.axis("off")
    fig.patch.set_facecolor("white")
    ax.text(xmax / 2, ymax - 1.2, title, ha="center", va="top", fontsize=17, fontweight="bold", color=INK)
    return fig, ax


def box(ax, x, y, w, h, title, sub="", color=C["neutral"], fs=10.5, sfs=8.2, fill=None):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.25,rounding_size=0.8",
                                linewidth=1.6, edgecolor=color, facecolor=fill or "white", zorder=3))
    ax.add_patch(FancyBboxPatch((x, y + h - 1.0), w, 1.0, boxstyle="round,pad=0.25,rounding_size=0.8",
                                linewidth=0, facecolor=color, zorder=3.5))
    cy = y + h / 2 + (0.6 if sub else 0) - 0.35
    ax.text(x + w / 2, cy, title, ha="center", va="center", fontsize=fs, fontweight="bold", color=INK, zorder=4)
    if sub:
        ax.text(x + w / 2, cy - 1.0, sub, ha="center", va="top", fontsize=sfs, color="#3A4250", zorder=4,
                linespacing=1.25)
    return (x, y, w, h)


def group(ax, x, y, w, h, label, color, ls="--", fill="none", fs=10):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.3,rounding_size=1.2", linewidth=1.5,
                                edgecolor=color, facecolor=fill, linestyle=ls, zorder=1))
    ax.text(x + 0.8, y + h - 0.5, label, ha="left", va="top", fontsize=fs, fontweight="bold", color=color, zorder=2)


def anchor(b, side):
    x, y, w, h = b
    return {"l": (x - 0.25, y + h / 2), "r": (x + w + 0.25, y + h / 2),
            "t": (x + w / 2, y + h + 0.25), "b": (x + w / 2, y - 0.25)}[side]


def arrow(ax, p, q, label="", color=INK, ls="-", rad=0.0, lpos=0.5, loff=(0, 0.6), fs=8, num=None):
    ax.add_patch(FancyArrowPatch(p, q, arrowstyle="-|>", mutation_scale=13, linewidth=1.4, color=color,
                                 linestyle=ls, connectionstyle=f"arc3,rad={rad}", zorder=2.5))
    if label:
        mx = p[0] + (q[0] - p[0]) * lpos + loff[0]
        my = p[1] + (q[1] - p[1]) * lpos + loff[1]
        text = f"{num}  {label}" if num else label
        ax.text(mx, my, text, ha="center", va="center", fontsize=fs, color=color, zorder=5,
                bbox=dict(boxstyle="round,pad=0.2", facecolor="white", edgecolor="none", alpha=0.9))


# ---------------------------------------------------------------------------
# Diagram 1 -- AWS Cloud Architecture
# ---------------------------------------------------------------------------

def aws_architecture():
    fig, ax = setup(17, 10.8, 100, 64, "InfraDriftGuard — AWS Cloud Architecture")
    ax.set_ylim(-0.5, 64)

    # outside AWS
    group(ax, 0.6, 2, 15.5, 56, "Outside AWS", C["neutral"], ls=":")
    dash = box(ax, 1.6, 42, 13.5, 9, "Streamlit Dashboard", "Admin / Cloud engineer\n(laptop, localhost:8501)", C["external"])
    tf = box(ax, 1.6, 24, 13.5, 9, "Terraform (IaC)", "terraform apply\n= desired state", C["network"])
    mail = box(ax, 1.6, 5, 13.5, 8, "Email inbox", "drift alerts +\nbudget warnings", C["external"])

    group(ax, 18, 2, 81, 56, "AWS Cloud  (ap-southeast-2 Sydney, free tier)", "#232F3E", ls="-", fs=11)

    cog = box(ax, 21, 44, 14, 9, "Amazon Cognito", "User pool · JWT\n(no self sign-up)", C["security"])
    apigw = box(ax, 40, 44, 14, 9, "API Gateway", "HTTP API · JWT authorizer\nthrottled 5 req/s", C["network"])
    apil = box(ax, 59, 44, 14, 9, "AWS Lambda", "API handler\nGET /findings · POST /scan", C["compute"])
    ddb = box(ax, 80, 44, 16, 9, "Amazon DynamoDB", "drift-findings table\n(PK resource, SK time)", C["database"])

    eb = box(ax, 21, 28, 14, 9, "Amazon EventBridge", "schedule\nrate(1 hour)", C["integration"])
    det = box(ax, 40, 24.5, 22, 12, "AWS Lambda — Drift Detector",
              "collect → normalize → detect_drift\n→ extract features → Random Forest\n(pure-Python, 200 trees)\n→ store · alert · remediate",
              C["compute"], sfs=8.2)
    cw = box(ax, 80, 26, 16, 9, "Amazon CloudWatch", "Logs · custom metrics\nalarms · dashboard", C["mgmt"])

    group(ax, 38, 2.6, 37, 17, "", C["storage"])
    ax.text(56.5, 3.2, "Monitored resources (managed by Terraform)", ha="center", va="bottom", fontsize=9.5,
            fontweight="bold", color=C["storage"])
    s3 = box(ax, 40, 6, 10.5, 9, "Amazon S3", "demo bucket\nBPA · SSE · ACL", C["storage"], sfs=7.8)
    sg = box(ax, 52, 6, 10.5, 9, "EC2 Security\nGroup", "SSH/RDP internal\nHTTPS public", C["network"], fs=9.5, sfs=7.8)
    iam = box(ax, 64, 6, 10, 9, "AWS IAM role", "MFA trust · boundary\nleast privilege", C["security"], sfs=7.8)

    bud = box(ax, 21, 6, 14, 9, "AWS Budgets", "$1 / month alarm\n(cost guard-rail)", C["mgmt"])
    sns = box(ax, 80, 6, 16, 9, "Amazon SNS", "drift-alerts topic\nemail subscription", C["integration"])

    # user path
    arrow(ax, anchor(dash, "r"), anchor(cog, "l"), "sign in", num="①", lpos=0.5, loff=(0, 0.9))
    arrow(ax, anchor(cog, "r"), anchor(apigw, "l"), "JWT", num="②", loff=(0, 0.9))
    arrow(ax, (anchor(dash, "r")[0], 44.5), (39.75, 45.2), "HTTPS + Bearer token", num="③", rad=0.12,
          lpos=0.62, loff=(0, -1.6), color="#3949AB")
    arrow(ax, anchor(apigw, "r"), anchor(apil, "l"), "invoke", num="④", loff=(0, 0.9))
    arrow(ax, anchor(apil, "r"), anchor(ddb, "l"), "query", num="⑤", loff=(0, 0.9))
    arrow(ax, (62, 43.75), (55, 36.75), "POST /scan (async)", lpos=0.5, loff=(-6.5, 0), color=C["compute"])

    # detection path
    arrow(ax, (35.25, 32.5), (39.75, 32.5), "", )
    ax.text(37.5, 38.2, "A  hourly\ntrigger", ha="center", fontsize=8, color=INK)
    for b in (s3, sg, iam):
        arrow(ax, (b[0] + b[2] / 2, 24.25), anchor(b, "t"), "", color=C["storage"])
    ax.text(68.5, 21.4, "B  read-only Get/Describe", ha="center", fontsize=8, color=C["storage"],
            bbox=dict(boxstyle="round,pad=0.2", facecolor="white", edgecolor="none"), zorder=5)
    arrow(ax, (62.25, 35.5), (86, 43.75), "C  put finding + read history", rad=0.2, lpos=0.72, loff=(1, 0.2),
          color=C["database"])
    arrow(ax, (62.25, 30.5), anchor(cw, "l"), "D  metrics + logs", loff=(0, 0.9), color=C["mgmt"])
    arrow(ax, (62.25, 26), (79.75, 13), "E  alert if risk ≥ High", lpos=0.62, loff=(2.5, 1.2), color=C["integration"])
    arrow(ax, anchor(cw, "b"), anchor(sns, "t"), "F  alarms", loff=(3.5, 0), color=C["mgmt"])
    # SNS -> email, routed under the AWS frame
    ax.plot([88, 88, 8.35], [5.75, 0.6, 0.6], color=C["integration"], lw=1.4, zorder=2)
    arrow(ax, (8.35, 0.6), (8.35, 4.75), "", color=C["integration"])
    ax.text(50, 0.95, "email alerts", ha="center", fontsize=8, color=C["integration"])
    arrow(ax, anchor(bud, "l"), anchor(mail, "r"), "budget email", loff=(0, 0.9), color=C["mgmt"], ls=":")

    # remediation
    arrow(ax, (42.5, 24.25), (42.5, 15.25), "", color=C["security"], ls="--")
    ax.text(41.9, 21.4, "G  auto-remediate\n(opt-in)", fontsize=7.5, color=C["security"], ha="right", zorder=5,
            bbox=dict(boxstyle="round,pad=0.15", facecolor="white", edgecolor="none"))

    # terraform (routed under EventBridge)
    arrow(ax, (15.35, 25.5), (39.75, 25.5), "provision + DESIRED_STATE_JSON", lpos=0.5,
          loff=(0, -1.3), color=C["network"], ls="--")

    ax.text(99, -0.4, "IAM: each Lambda has its own least-privilege role · all data encrypted at rest",
            ha="right", fontsize=8, color="#5A6B86", style="italic")
    fig.savefig(os.path.join(OUT, "AWS_Architecture.png"), bbox_inches="tight", facecolor="white")
    plt.close(fig)


# ---------------------------------------------------------------------------
# Diagram 2 -- Complete System Architecture
# ---------------------------------------------------------------------------

def system_architecture():
    fig, ax = setup(17, 11, 100, 66, "InfraDriftGuard — Complete System Architecture")

    # Layer bands
    bands = [
        (46, 15, "① OFFLINE: Dataset & Model Development  (local, Python / scikit-learn)", "#EAF4FF", C["network"]),
        (24, 19, "② ONLINE: Cloud Drift Detection  (AWS Lambda, every hour)", "#FFF4E8", C["compute"]),
        (3, 18, "③ RESPONSE & PRESENTATION", "#F3FFF0", C["storage"]),
    ]
    for y, h, label, fill, col in bands:
        group(ax, 1, y, 98, h, label, col, ls="-", fill=fill, fs=11)

    y1 = 48
    s = box(ax, 3, y1, 13, 9, "Scenario library", "20 drift scenarios\nS3 · SG · IAM", C["neutral"])
    g = box(ax, 19.5, y1, 13, 9, "Dataset generator", "711 records\n9 features + label", C["storage"])
    v = box(ax, 36, y1, 13, 9, "Validation", "label rules · dupes\nleakage audit", C["neutral"])
    t = box(ax, 52.5, y1, 13, 9, "Model training", "Random Forest (200)\nDecision Tree baseline", C["ml"])
    x = box(ax, 69, y1, 13, 9, "Explainability", "SHAP TreeExplainer\nglobal + local", C["ml"])
    e = box(ax, 85, y1, 12, 9, "Model export", "trees → JSON\n(210 KB, no deps)", C["compute"])
    for a, b2 in ((s, g), (g, v), (v, t), (t, x), (x, e)):
        arrow(ax, anchor(a, "r"), anchor(b2, "l"))

    y2 = 27
    tfb = box(ax, 3, y2, 12, 10, "Terraform", "desired state\n(IaC = truth)", C["network"])
    col = box(ax, 18, y2, 12.5, 10, "Collectors", "boto3: S3, EC2 SG,\nIAM role (read-only)", C["compute"])
    nor = box(ax, 33.5, y2, 12, 10, "Normalizers", "AWS JSON →\ncommon schema", C["compute"])
    dr = box(ax, 48.5, y2, 12, 10, "Drift engine", "recursive diff\ndesired vs actual", C["compute"])
    fe = box(ax, 63.5, y2, 13, 10, "Feature extraction", "21-rule knowledge base\n+ drift frequency", C["compute"])
    rf = box(ax, 79.5, y2, 17.5, 10, "Risk classifier", "pure-Python RF\nLow / Medium / High /\nCritical  (or Review)", C["ml"])
    arrow(ax, anchor(tfb, "r"), anchor(col, "l"), "resources")
    for a, b2 in ((col, nor), (nor, dr), (dr, fe), (fe, rf)):
        arrow(ax, anchor(a, "r"), anchor(b2, "l"))
    arrow(ax, (dr[0] + dr[2] / 2, y2 + 10.25), (dr[0] + dr[2] / 2, y2 + 10.25), "")
    arrow(ax, (tfb[0] + 6, y2 - 0.25), (dr[0] + 3, y2 - 0.25), "desired state", rad=0.18, lpos=0.5,
          loff=(0, -2.6), color=C["network"], ls="--")
    arrow(ax, anchor(e, "b"), (rf[0] + rf[2] / 2 + 3, y2 + 10.25), "deployed model", loff=(4.5, 0), color=C["ml"], ls="--")

    y3 = 5
    d = box(ax, 3, y3, 14, 10, "DynamoDB", "finding history\n→ drift_frequency", C["database"])
    n = box(ax, 20, y3, 14, 10, "SNS email alert", "risk ≥ threshold\nor Review", C["integration"])
    r = box(ax, 37, y3, 14, 10, "Auto-remediation", "Critical + safe fix\n(opt-in)", C["security"])
    c = box(ax, 54, y3, 14, 10, "CloudWatch", "metrics · logs\nalarms · dashboard", C["mgmt"])
    a = box(ax, 71, y3, 12, 10, "REST API", "API Gateway\n+ Cognito JWT", C["network"])
    u = box(ax, 86, y3, 11, 10, "Streamlit UI", "offline analyzer\n+ live findings", C["external"])
    for b2 in (d, n, r, c):
        arrow(ax, (rf[0] + 4, y2 - 0.25), anchor(b2, "t"), "", color=C["neutral"], rad=0.0)
    arrow(ax, (d[0] + d[2] / 2, y3 - 0.25), (a[0] + a[2] / 2, y3 - 0.25), "read findings", rad=0.12, lpos=0.5,
          loff=(0, -1.6), color=C["database"])
    arrow(ax, anchor(a, "r"), anchor(u, "l"), "HTTPS")
    arrow(ax, (d[0] + d[2] / 2 - 2, y3 + 10.25), (fe[0] + 2, y2 - 0.25), "history", rad=-0.1, lpos=0.3,
          loff=(-2, 0), color=C["database"], ls="--")

    fig.savefig(os.path.join(OUT, "System_Architecture.png"), bbox_inches="tight", facecolor="white")
    plt.close(fig)


# ---------------------------------------------------------------------------
# Workflow -- one scan
# ---------------------------------------------------------------------------

def diamond(ax, cx, cy, w, h, text, color):
    from matplotlib.patches import Polygon
    ax.add_patch(Polygon([(cx, cy + h / 2), (cx + w / 2, cy), (cx, cy - h / 2), (cx - w / 2, cy)],
                         closed=True, facecolor="white", edgecolor=color, linewidth=1.6, zorder=3))
    ax.text(cx, cy, text, ha="center", va="center", fontsize=9, fontweight="bold", color=INK, zorder=4)
    return (cx - w / 2, cy - h / 2, w, h)


def workflow():
    fig, ax = setup(14, 13, 80, 92, "InfraDriftGuard — Drift Scan Workflow (per run)")
    cx = 26
    w = 26

    def step(y, title, sub="", color=C["compute"]):
        return box(ax, cx - w / 2, y, w, 6.2, title, sub, color, fs=9.8, sfs=7.8)

    b0 = step(80, "Trigger", "EventBridge schedule or POST /scan", C["integration"])
    b1 = step(71, "Load desired state", "DESIRED_STATE_JSON rendered by Terraform", C["network"])
    b2 = step(62, "Collect live configuration", "boto3 Get*/Describe* (read-only)")
    b3 = step(53, "Normalize to common schema", "S3 / Security Group / IAM role")
    b4 = step(44, "detect_drift(desired, actual)", "recursive attribute diff")
    d1 = diamond(ax, cx, 36, 16, 6, "Drift?", C["compute"])
    b5 = step(24, "Extract 9 features", "+ drift_frequency from DynamoDB history")
    b6 = step(15, "Random Forest risk prediction", "Low · Medium · High · Critical", C["ml"])
    b7 = step(4, "Store finding + publish metric", "DynamoDB · CloudWatch", C["database"])

    seq = [b0, b1, b2, b3, b4]
    for a, b2_ in zip(seq, seq[1:]):
        arrow(ax, anchor(a, "b"), anchor(b2_, "t"))
    arrow(ax, anchor(b4, "b"), (cx, 39.1))
    arrow(ax, (cx, 32.9), anchor(b5, "t"), "yes", loff=(1.6, 0))
    arrow(ax, anchor(b5, "b"), anchor(b6, "t"))
    arrow(ax, anchor(b6, "b"), anchor(b7, "t"))
    arrow(ax, (cx - 8.1, 36), (4, 36), "no", loff=(0, 0.8))
    ax.plot([4, 4], [36, 7.1], color=INK, lw=1.4, zorder=2)
    arrow(ax, (4, 7.1), (cx - w / 2 - 0.25, 7.1), "")
    ax.text(4.6, 22, "risk = Low\n(no drift)", fontsize=8, color=INK)

    # side branches
    d2 = diamond(ax, 60, 30, 18, 6.5, "Unknown\nattribute only?", C["security"])
    arrow(ax, (cx + 8.1, 36), (60, 33.4), "", rad=-0.2)
    rv = box(ax, 50, 39, 20, 5.5, "Label = Review", "never guess unseen changes", C["security"], fs=9.2, sfs=7.6)
    arrow(ax, (60, 33.4 + 0.1), anchor(rv, "b"), "yes", loff=(1.6, 0))
    arrow(ax, (60 - 9.1, 30), (cx + w / 2 + 0.25, 27.1), "no", loff=(0, 0.9))

    d3 = diamond(ax, 60, 18, 18, 6.5, "Risk ≥ High\nor Review?", C["integration"])
    arrow(ax, anchor(b6, "r"), (51, 18), "")
    sn = box(ax, 51, 6.5, 18, 5.5, "SNS email alert", "", C["integration"], fs=9.2)
    arrow(ax, (60, 14.75), anchor(sn, "t"), "yes", loff=(1.6, 0))

    d4 = diamond(ax, 60, 52, 20, 6.5, "Critical AND\nauto-remediate on?", C["security"])
    rm = box(ax, 50, 61, 20, 6, "Revert safely", "S3 public-access block on ·\nrevoke 0.0.0.0/0 SSH/RDP", C["security"],
             fs=9.2, sfs=7.4)
    arrow(ax, (69.1, 18), (71.5, 18), "")
    ax.plot([71.5, 71.5], [18, 52], color=INK, lw=1.4, zorder=2)
    arrow(ax, (71.5, 52), (70.25, 52), "")
    arrow(ax, (60, 55.4), anchor(rm, "b"), "yes", loff=(1.6, 0))
    ax.text(73, 70, "Errors on one resource are\nlogged and the scan continues\nwith the next resource.",
            fontsize=8, color="#5A6B86", ha="center", style="italic")

    fig.savefig(os.path.join(OUT, "Workflow.png"), bbox_inches="tight", facecolor="white")
    plt.close(fig)


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    aws_architecture()
    system_architecture()
    workflow()
    print("Wrote", ", ".join(sorted(os.listdir(OUT))))
