terraform {
  required_version = ">= 1.6.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }
}

provider "aws" {
  region = "ap-southeast-2"

  default_tags {
    tags = {
      Project     = "InfrastructureDriftDetection"
      Environment = "Dev"
      ManagedBy   = "Terraform"
      Owner       = "Student1"
    }
  }
}

data "aws_vpc" "default" {
  default = true
}

resource "aws_security_group" "drift_demo" {
  name        = "infrastructure-drift-demo-sg"
  description = "Controlled security group used for infrastructure drift detection"
  vpc_id      = data.aws_vpc.default.id

  ingress {
    description = "HTTPS"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    description = "Allow outbound traffic"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

