# =============================================================================
# EKS Cluster
# - KMS envelope encryption for etcd secrets
# - OIDC provider (required for IRSA)
# - Mixed node groups: On-Demand (system) + Spot (app workloads)
# - AWS Node Termination Handler wired via node labels
# =============================================================================

locals {
  name = "${var.project}-${var.environment}"
}

# ── KMS Key for etcd secret encryption ───────────────────────────────────────

resource "aws_kms_key" "eks_secrets" {
  description             = "KMS CMK for EKS etcd secret envelope encryption — ${local.name}"
  deletion_window_in_days = 7
  enable_key_rotation     = true

  tags = { Name = "${local.name}-eks-secrets-kms" }
}

resource "aws_kms_alias" "eks_secrets" {
  name          = "alias/${local.name}-eks-secrets"
  target_key_id = aws_kms_key.eks_secrets.key_id
}

# ── EKS Cluster IAM Role ──────────────────────────────────────────────────────

data "aws_iam_policy_document" "eks_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["eks.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "eks_cluster" {
  name               = "${local.name}-eks-cluster-role"
  assume_role_policy = data.aws_iam_policy_document.eks_assume.json
}

resource "aws_iam_role_policy_attachment" "eks_cluster_policy" {
  role       = aws_iam_role.eks_cluster.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonEKSClusterPolicy"
}

resource "aws_iam_role_policy_attachment" "eks_vpc_resource_controller" {
  role       = aws_iam_role.eks_cluster.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonEKSVPCResourceController"
}

# ── EKS Cluster ───────────────────────────────────────────────────────────────

resource "aws_eks_cluster" "main" {
  name     = local.name
  version  = var.eks_cluster_version
  role_arn = aws_iam_role.eks_cluster.arn

  vpc_config {
    subnet_ids              = var.private_subnet_ids
    security_group_ids      = [var.eks_nodes_sg_id]
    endpoint_private_access = true
    endpoint_public_access  = true   # Set to false after CI/CD is wired through a bastion.
  }

  # etcd envelope encryption — satisfies the "Secrets are encrypted at rest" requirement.
  encryption_config {
    resources = ["secrets"]
    provider {
      key_arn = aws_kms_key.eks_secrets.arn
    }
  }

  enabled_cluster_log_types = ["api", "audit", "authenticator", "controllerManager", "scheduler"]

  depends_on = [
    aws_iam_role_policy_attachment.eks_cluster_policy,
    aws_iam_role_policy_attachment.eks_vpc_resource_controller,
  ]

  tags = { Name = local.name }
}

# ── OIDC Identity Provider (required for IRSA) ────────────────────────────────

data "tls_certificate" "eks" {
  url = aws_eks_cluster.main.identity[0].oidc[0].issuer
}

resource "aws_iam_openid_connect_provider" "eks" {
  client_id_list  = ["sts.amazonaws.com"]
  thumbprint_list = [data.tls_certificate.eks.certificates[0].sha1_fingerprint]
  url             = aws_eks_cluster.main.identity[0].oidc[0].issuer

  tags = { Name = "${local.name}-oidc" }
}

# ── Node IAM Role (shared by both node groups) ───────────────────────────────

data "aws_iam_policy_document" "node_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "node" {
  name               = "${local.name}-node-role"
  assume_role_policy = data.aws_iam_policy_document.node_assume.json
}

resource "aws_iam_role_policy_attachment" "node_worker" {
  role       = aws_iam_role.node.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonEKSWorkerNodePolicy"
}

resource "aws_iam_role_policy_attachment" "node_cni" {
  role       = aws_iam_role.node.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonEKS_CNI_Policy"
}

resource "aws_iam_role_policy_attachment" "node_ecr" {
  role       = aws_iam_role.node.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryReadOnly"
}

# Node Termination Handler needs SQS + EC2 describe to intercept Spot interruptions.
resource "aws_iam_role_policy_attachment" "node_ssm" {
  role       = aws_iam_role.node.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

# Inline policy: allow nodes to call EC2 describe-instances and SQS for NTH.
resource "aws_iam_role_policy" "node_nth" {
  name = "${local.name}-node-nth-policy"
  role = aws_iam_role.node.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "ec2:DescribeInstances",
          "ec2:DescribeTags",
          "autoscaling:CompleteLifecycleAction",
          "autoscaling:DescribeAutoScalingInstances",
          "sqs:DeleteMessage",
          "sqs:GetQueueAttributes",
          "sqs:GetQueueUrl",
          "sqs:ReceiveMessage",
        ]
        Resource = "*"
      }
    ]
  })
}

# ── On-Demand Node Group — system workloads (ArgoCD, Kong, Prometheus) ────────

resource "aws_eks_node_group" "system" {
  cluster_name    = aws_eks_cluster.main.name
  node_group_name = "${local.name}-system"
  node_role_arn   = aws_iam_role.node.arn
  subnet_ids      = var.private_subnet_ids

  ami_type       = "AL2_x86_64"
  instance_types = [var.on_demand_instance_type]
  capacity_type  = "ON_DEMAND"

  scaling_config {
    desired_size = var.on_demand_desired
    min_size     = var.on_demand_desired
    max_size     = var.on_demand_desired + 1
  }

  # Taint system nodes so only system-tolerating pods (ArgoCD, Kong, Prometheus)
  # are scheduled here. App pods land on the Spot group by default.
  taint {
    key    = "dedicated"
    value  = "system"
    effect = "NO_SCHEDULE"
  }

  labels = {
    role = "system"
  }

  update_config {
    max_unavailable = 1
  }

  depends_on = [
    aws_iam_role_policy_attachment.node_worker,
    aws_iam_role_policy_attachment.node_cni,
    aws_iam_role_policy_attachment.node_ecr,
  ]

  tags = { Name = "${local.name}-system-ng" }
}

# ── Spot Node Group — app workloads (all microservices) ───────────────────────

resource "aws_eks_node_group" "app" {
  cluster_name    = aws_eks_cluster.main.name
  node_group_name = "${local.name}-app-spot"
  node_role_arn   = aws_iam_role.node.arn
  subnet_ids      = var.private_subnet_ids

  ami_type       = "AL2_x86_64"
  instance_types = var.spot_instance_types
  capacity_type  = "SPOT"

  scaling_config {
    desired_size = var.spot_desired
    min_size     = var.spot_min
    max_size     = var.spot_max
  }

  labels = {
    role                             = "app"
    "node.kubernetes.io/lifecycle"   = "spot"
  }

  update_config {
    max_unavailable = 1
  }

  depends_on = [
    aws_iam_role_policy_attachment.node_worker,
    aws_iam_role_policy_attachment.node_cni,
    aws_iam_role_policy_attachment.node_ecr,
  ]

  tags = { Name = "${local.name}-app-spot-ng" }
}

# ── SQS Queue for AWS Node Termination Handler ────────────────────────────────
# NTH polls this queue for Spot interruption notices forwarded by EventBridge.

resource "aws_sqs_queue" "nth" {
  name                      = "${local.name}-nth"
  message_retention_seconds = 300

  tags = { Name = "${local.name}-nth" }
}

resource "aws_sqs_queue_policy" "nth" {
  queue_url = aws_sqs_queue.nth.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect    = "Allow"
        Principal = { Service = "events.amazonaws.com" }
        Action    = "sqs:SendMessage"
        Resource  = aws_sqs_queue.nth.arn
      }
    ]
  })
}

# Forward EC2 Spot interruption warnings and rebalance events to the SQS queue.
resource "aws_cloudwatch_event_rule" "spot_interruption" {
  name        = "${local.name}-spot-interruption"
  description = "Forward Spot interruption warnings to NTH SQS queue."

  event_pattern = jsonencode({
    source      = ["aws.ec2"]
    detail-type = ["EC2 Spot Instance Interruption Warning"]
  })
}

resource "aws_cloudwatch_event_target" "spot_interruption" {
  rule      = aws_cloudwatch_event_rule.spot_interruption.name
  target_id = "nth-sqs"
  arn       = aws_sqs_queue.nth.arn
}

resource "aws_cloudwatch_event_rule" "rebalance" {
  name        = "${local.name}-rebalance"
  description = "Forward EC2 instance rebalance recommendations to NTH SQS queue."

  event_pattern = jsonencode({
    source      = ["aws.ec2"]
    detail-type = ["EC2 Instance Rebalance Recommendation"]
  })
}

resource "aws_cloudwatch_event_target" "rebalance" {
  rule      = aws_cloudwatch_event_rule.rebalance.name
  target_id = "nth-sqs-rebalance"
  arn       = aws_sqs_queue.nth.arn
}
