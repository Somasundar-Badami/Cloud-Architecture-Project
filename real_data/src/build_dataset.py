"""
build_dataset.py -- Step 2: turn real tfsec findings into InfraDriftGuard's 9 features.

One record = one unique misconfiguration (rule + file + resource) in one real
GitHub repo, described at the first history snapshot where it appeared.

LABELS (neither is written by us, neither is a formula over the 9 features):
  risk_label    tfsec/Aqua Security published severity for that check
                (LOW/MEDIUM/HIGH/CRITICAL -> Low/Medium/High/Critical).
  fixed_later   measured from git history: 1 if the finding disappeared in a
                later snapshot while the resource itself was still there
                (= the real developers fixed it), 0 if it is still present at
                the newest snapshot. Empty if it cannot be observed (first seen
                in the newest snapshot, or the whole resource was deleted).

FEATURES (how each one is derived -- this part IS our mapping, see README):
  resource_type         Terraform type from tfsec's resource address (real)
  changed_attribute     attribute name on the flagged line of real code, or
                        "resource_block" when tfsec flags a missing setting
  security_sensitivity  fixed table: data/identity services High, network &
                        compute Medium, the rest Low (depends on type only)
  public_exposure       keyword match on the check's text + 0.0.0.0/0, ::/0,
                        public-read, publicly_accessible=true in the real block
  encryption_change     keyword match (encrypt, kms, tls, ssl, https ...)
  privilege_change      keyword match (iam, policy, wildcard, mfa, admin ...)
  port_exposure         from the real block: 0.0.0.0/0 | internal | none
  change_magnitude      git blame: share of the block's lines written by its
                        most recent commit (<25% Low, <60% Medium, else High)
  drift_frequency       git blame: number of distinct commits that wrote the
                        block's current lines (capped at 10)

    python build_dataset.py <repos_dir> <scan_dir> <out_csv>
"""
import csv, json, os, re, subprocess, sys
from collections import defaultdict

VULN_BY_DESIGN = {"bridgecrewio_terragoat", "RhinoSecurityLabs_cloudgoat"}

HIGH_SENS = ("s3", "iam", "kms", "db_", "rds", "dynamodb", "secretsmanager", "ssm", "redshift",
             "elasticsearch", "opensearch", "efs", "ebs", "docdb", "elasticache", "msk", "mq_",
             "neptune", "backup", "dax", "memorydb", "ecr", "athena", "glue")
MED_SENS = ("security_group", "network_acl", "vpc", "subnet", "lb", "alb", "elb", "cloudfront",
            "api_gateway", "apigatewayv2", "instance", "launch", "lambda", "ecs", "eks", "sns",
            "sqs", "cloudtrail", "kinesis", "emr", "workspaces", "codebuild", "batch", "transfer")

KW_PUBLIC = r"public|0\.0\.0\.0|::/0|internet|anonymous|ingress|egress|open to|world"
KW_ENC = r"encrypt|kms|\bcmk\b|customer.managed key|\btls\b|\bssl\b|https|in.transit|at.rest"
KW_PRIV = r"\biam\b|polic|wildcard|privilege|admin|\brole\b|\bmfa\b|password|access key|root|authoriz|authentic"
SEV = {"LOW": "Low", "MEDIUM": "Medium", "HIGH": "High", "CRITICAL": "Critical"}


def sh(args, cwd):
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True, errors="replace").stdout


def file_at(repo, commit, path, cache={}):
    k = (repo, commit, path)
    if k not in cache:
        cache[k] = sh(["git", "show", f"{commit}:{path}"], repo).split("\n")
    return cache[k]


def enclosing_block(lines, s, e):
    """Return 1-based (start, end) of the top-level block containing lines s..e."""
    i = s - 1
    while i >= 0 and not re.match(r'^(resource|data|module)\s+"', lines[i]):
        i -= 1
    if i < 0:
        return s, e
    depth, j = 0, i
    while j < len(lines):
        depth += lines[j].count("{") - lines[j].count("}")
        if depth <= 0 and j > i:
            break
        j += 1
    return i + 1, max(j + 1, e)


def blame(repo, commit, path, s, e):
    out = sh(["git", "blame", "--porcelain", "-L", f"{s},{e}", commit, "--", path], repo)
    line_commit, times, cur = [], {}, None
    for ln in out.split("\n"):
        m = re.match(r"^([0-9a-f]{40}) \d+ \d+", ln)
        if m:
            cur = m.group(1)
            line_commit.append(cur)
        elif ln.startswith("committer-time ") and cur:
            times[cur] = int(ln.split()[1])
    if not line_commit:
        return 0, "Low"
    distinct = set(line_commit)
    newest = max(distinct, key=lambda c: times.get(c, 0))
    share = line_commit.count(newest) / len(line_commit)
    mag = "Low" if share < 0.25 else ("Medium" if share < 0.6 else "High")
    return min(len(distinct), 10), mag


def sensitivity(rtype):
    t = rtype.replace("aws_", "")
    if any(k in t for k in HIGH_SENS):
        return "High"
    if any(k in t for k in MED_SENS):
        return "Medium"
    return "Low"


def resource_exists(repo, commit, path, address):
    m = re.search(r"(aws_[a-z0-9_]+)\.([A-Za-z0-9_\-]+)", address or "")
    if not m:
        return False
    pat = re.compile(r'resource\s+"%s"\s+"%s"' % (m.group(1), re.escape(m.group(2))))
    return any(pat.search(l) for l in file_at(repo, commit, path))


def main(repos_dir, scan_dir, out_csv):
    snaps = json.load(open(os.path.join(scan_dir, "_snapshots.json")))
    by_repo = defaultdict(list)
    for s in snaps:
        by_repo[s["repo"]].append(s)
    rows = []
    for repo_name, ss in sorted(by_repo.items()):
        ss.sort(key=lambda s: s["snapshot"])
        repo = os.path.join(repos_dir, repo_name)
        seen = {}  # key -> dict(first, last, finding)
        for k, s in enumerate(ss):
            p = os.path.join(scan_dir, f"{repo_name}__{s['commit'][:10]}.json")
            try:
                res = json.load(open(p)).get("results") or []
            except Exception:
                continue
            for x in res:
                if x.get("rule_provider") != "aws" or not x["location"]["filename"].endswith(".tf"):
                    continue
                key = (x["long_id"], x["location"]["filename"], x.get("resource", ""))
                if key not in seen:
                    seen[key] = {"first": k, "last": k, "x": x}
                else:
                    seen[key]["last"] = k
        final = len(ss) - 1
        for (rule, path, address), v in seen.items():
            x, first, last = v["x"], v["first"], v["last"]
            commit = ss[first]["commit"]
            lines = file_at(repo, commit, path)
            s, e = x["location"]["start_line"], x["location"]["end_line"]
            if not lines or s < 1 or s > len(lines):
                continue
            bs, be = enclosing_block(lines, s, e)
            block = "\n".join(lines[bs - 1:be])
            m = re.match(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=", lines[s - 1]) if (e - s) <= 1 else None
            attr = m.group(1) if m else "resource_block"
            rtype = (re.search(r"(aws_[a-z0-9_]+)", address or "") or
                     re.search(r'resource\s+"(aws_[a-z0-9_]+)"', lines[bs - 1]) or [None, "unknown"])[1]
            text = " ".join([x.get("long_id", "").replace("-", " "), x.get("rule_description", ""),
                             x.get("description", ""), x.get("impact", "")]).lower()
            world = bool(re.search(r"0\.0\.0\.0/0|::/0", block))
            internal = bool(re.search(r'"(10\.|172\.(1[6-9]|2\d|3[01])\.|192\.168\.)', block))
            public = bool(re.search(KW_PUBLIC, text)) or world or bool(
                re.search(r"public-read|publicly_accessible\s*=\s*true", block))
            drift_freq, mag = blame(repo, commit, path, bs, be)
            if last < final:
                fixed = 1 if resource_exists(repo, ss[last + 1]["commit"], path, address) else ""
            else:
                fixed = 0 if first < final else ""
            rows.append({
                "record_id": "", "repo": repo_name, "commit": commit[:12],
                "commit_time": ss[first]["commit_time"], "file": path, "line": s,
                "rule_id": x["rule_id"], "check": rule, "resource_address": address,
                "intentionally_vulnerable": repo_name in VULN_BY_DESIGN,
                "resource_type": rtype, "changed_attribute": attr,
                "security_sensitivity": sensitivity(rtype),
                "public_exposure": public,
                "encryption_change": bool(re.search(KW_ENC, text)),
                "privilege_change": bool(re.search(KW_PRIV, text)),
                "port_exposure": "0.0.0.0/0" if world else ("internal" if internal else "none"),
                "change_magnitude": mag, "drift_frequency": drift_freq,
                "risk_label": SEV[x["severity"]], "fixed_later": fixed,
            })
    for i, r in enumerate(rows, 1):
        r["record_id"] = f"REAL{i:05d}"
    with open(out_csv, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print(len(rows), "records ->", out_csv)


if __name__ == "__main__":
    main(*sys.argv[1:4])
