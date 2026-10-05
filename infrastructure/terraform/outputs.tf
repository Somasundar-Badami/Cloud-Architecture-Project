output "drift_security_group_id" {
  description = "ID of the security group used for drift detection testing"
  value       = aws_security_group.drift_demo.id
}

