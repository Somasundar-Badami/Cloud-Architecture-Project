import json
import subprocess
import sys


def run_command(command: list[str]) -> str:
    """Run a shell command and return stdout."""
    result = subprocess.run(
        command,
        capture_output=True,
        text=True
    )

    if result.returncode != 0:
        print(result.stderr, file=sys.stderr)
        raise RuntimeError(f"Command failed: {' '.join(command)}")

    return result.stdout.strip()


def get_terraform_security_group_id() -> str:
    """Get the Security Group ID from Terraform output."""
    return run_command(
        [
            "terraform",
            "-chdir=../../infrastructure/terraform",
            "output",
            "-raw",
            "drift_security_group_id",
        ]
    )


def get_expected_rules() -> list[dict]:
    """Expected ingress rules defined by Terraform."""
    return [
        {
            "protocol": "tcp",
            "from_port": 443,
            "to_port": 443,
            "cidr": "0.0.0.0/0",
        }
    ]


def get_actual_rules(security_group_id: str) -> list[dict]:
    """Get current AWS ingress rules."""
    output = run_command(
        [
            "aws",
            "ec2",
            "describe-security-groups",
            "--group-ids",
            security_group_id,
            "--query",
            "SecurityGroups[0].IpPermissions",
            "--output",
            "json",
        ]
    )

    permissions = json.loads(output)

    rules = []

    for permission in permissions:
        protocol = permission.get("IpProtocol")
        from_port = permission.get("FromPort")
        to_port = permission.get("ToPort")

        for ip_range in permission.get("IpRanges", []):
            rules.append(
                {
                    "protocol": protocol,
                    "from_port": from_port,
                    "to_port": to_port,
                    "cidr": ip_range.get("CidrIp"),
                }
            )

    return rules


def detect_drift(expected: list[dict], actual: list[dict]) -> dict:
    expected_set = {
        (
            rule["protocol"],
            rule["from_port"],
            rule["to_port"],
            rule["cidr"],
        )
        for rule in expected
    }

    actual_set = {
        (
            rule["protocol"],
            rule["from_port"],
            rule["to_port"],
            rule["cidr"],
        )
        for rule in actual
    }

    added = actual_set - expected_set
    removed = expected_set - actual_set

    added_rules = [
        {
            "protocol": rule[0],
            "from_port": rule[1],
            "to_port": rule[2],
            "cidr": rule[3],
        }
        for rule in added
    ]

    removed_rules = [
        {
            "protocol": rule[0],
            "from_port": rule[1],
            "to_port": rule[2],
            "cidr": rule[3],
        }
        for rule in removed
    ]

    return {
        "drift_detected": bool(added_rules or removed_rules),
        "expected_rules": expected,
        "actual_rules": actual,
        "added_rules": added_rules,
        "removed_rules": removed_rules,
    }


def main():
    security_group_id = get_terraform_security_group_id()

    expected = get_expected_rules()
    actual = get_actual_rules(security_group_id)

    drift = detect_drift(expected, actual)

    result = {
        "resource_type": "AWS::EC2::SecurityGroup",
        "resource_id": security_group_id,
        **drift,
    }

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
