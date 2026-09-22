# Explainable AI-Based Infrastructure Drift Detection Framework

## Overview

An AI-assisted framework for detecting and prioritizing infrastructure drift
in enterprise AWS environments by comparing desired Infrastructure-as-Code
state with actual cloud resource state.

The system combines deterministic drift detection with machine learning-based
risk classification and Explainable AI (XAI) to explain why a detected drift
is considered low, medium, high, or critical risk.

## Problem Statement

Cloud infrastructure can diverge from the intended Infrastructure-as-Code
configuration because of manual changes, unauthorized modifications,
configuration errors, emergency fixes, or operational activities.

Such drift can introduce security, availability, compliance, and cost risks.

## Proposed Solution

The proposed system will:

1. Compare Terraform desired state with actual AWS resource configuration.
2. Detect and record infrastructure drift.
3. Enrich drift events using AWS audit information.
4. Extract features describing the drift and affected resource.
5. Classify drift severity using machine learning.
6. Generate SHAP-based explanations for model predictions.
7. Display detected drift, risk scores, and explanations through a web dashboard.
8. Generate notifications for high-risk drift events.

## Technology Stack

### Cloud
- Amazon Web Services (AWS)
- AWS Config
- AWS CloudTrail
- Amazon EventBridge
- AWS Lambda
- Amazon S3
- Amazon DynamoDB
- Amazon SNS
- Amazon CloudWatch
- AWS IAM
- Amazon Cognito

### Infrastructure
- Terraform

### Machine Learning
- Python
- Scikit-learn
- XGBoost
- SHAP

### Backend
- FastAPI

### Frontend
- React
- TypeScript

## High-Level Workflow

```text
Terraform Desired State
          |
          v
    Drift Detection
          |
          v
 AWS Config + CloudTrail
          |
          v
   Feature Engineering
          |
          v
    ML Risk Classifier
          |
          v
      SHAP / XAI
          |
          v
 Dashboard + Alerts + Audit History
