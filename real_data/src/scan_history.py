"""
scan_history.py -- Step 1: collect REAL misconfiguration findings.

For every cloned public GitHub repo, take up to N snapshots of its history
(commits that changed .tf files, evenly spaced, newest included), export each
snapshot with `git archive`, and scan it with tfsec (Aqua Security).
Raw tfsec JSON is saved per snapshot so everything can be re-checked.

    python scan_history.py <repos_dir> <out_dir> [snapshots_per_repo]
"""
import json, os, subprocess, sys, tempfile, shutil, concurrent.futures as cf

TFSEC = os.environ.get("TFSEC", "tfsec")


def sh(args, cwd=None):
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True).stdout


def snapshots(repo, n):
    commits = sh(["git", "log", "--format=%H %ct", "--", "*.tf"], cwd=repo).split("\n")
    commits = [c.split() for c in commits if c.strip()][::-1]  # oldest -> newest
    if len(commits) <= n:
        return commits
    idx = sorted({round(i * (len(commits) - 1) / (n - 1)) for i in range(n)})
    return [commits[i] for i in idx]


def scan(repo, commit, out_dir):
    name = os.path.basename(repo)
    out = os.path.join(out_dir, f"{name}__{commit[:10]}.json")
    if os.path.exists(out):
        return out
    tmp = tempfile.mkdtemp()
    try:
        p1 = subprocess.Popen(["git", "archive", commit], cwd=repo, stdout=subprocess.PIPE)
        subprocess.run(["tar", "-x", "-C", tmp], stdin=p1.stdout, check=False)
        p1.wait()
        r = subprocess.run([TFSEC, tmp, "--format", "json", "--no-color", "--soft-fail",
                            "--no-module-downloads"], capture_output=True, text=True, timeout=600)
        data = json.loads(r.stdout or "{}")
        for x in data.get("results") or []:  # make paths repo-relative
            loc = x.get("location", {})
            loc["filename"] = os.path.relpath(loc.get("filename", ""), tmp)
        json.dump(data, open(out, "w"))
        return out
    except Exception as e:
        print("scan failed", name, commit[:10], e)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    repos_dir, out_dir = sys.argv[1], sys.argv[2]
    n = int(sys.argv[3]) if len(sys.argv) > 3 else 8
    os.makedirs(out_dir, exist_ok=True)
    jobs, index = [], []
    for d in sorted(os.listdir(repos_dir)):
        repo = os.path.join(repos_dir, d)
        for k, (c, ts) in enumerate(snapshots(repo, n)):
            index.append({"repo": d, "commit": c, "commit_time": int(ts), "snapshot": k})
            jobs.append((repo, c))
    with cf.ThreadPoolExecutor(8) as ex:
        list(ex.map(lambda j: scan(j[0], j[1], out_dir), jobs))
    json.dump(index, open(os.path.join(out_dir, "_snapshots.json"), "w"), indent=1)
    print(len(index), "snapshots scanned")
