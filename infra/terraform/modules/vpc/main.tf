# =============================================================================
# VPC — single NAT Gateway (cost-optimised for competition/dev)
# Two AZs: one public subnet + one private subnet per AZ.
# Private subnets host EKS nodes, RDS, DocumentDB, Amazon MQ.
# Public subnets host the NAT Gateway and load balancers only.
# =============================================================================

locals {
  name = "${var.project}-${var.environment}"

  # Carve /20 blocks from the VPC CIDR so each subnet has 4094 usable IPs.
  public_cidrs  = [for i, az in var.availability_zones : cidrsubnet(var.vpc_cidr, 4, i)]
  private_cidrs = [for i, az in var.availability_zones : cidrsubnet(var.vpc_cidr, 4, i + length(var.availability_zones))]
}

# ── VPC ───────────────────────────────────────────────────────────────────────

resource "aws_vpc" "main" {
  cidr_block           = var.vpc_cidr
  enable_dns_support   = true
  enable_dns_hostnames = true   # Required for EKS node registration and RDS hostname resolution.

  tags = {
    Name = "${local.name}-vpc"
    # EKS uses these tags to discover subnets for load-balancer provisioning.
    "kubernetes.io/cluster/${local.name}" = "shared"
  }
}

# ── Internet Gateway (public subnets only) ────────────────────────────────────

resource "aws_internet_gateway" "main" {
  vpc_id = aws_vpc.main.id
  tags   = { Name = "${local.name}-igw" }
}

# ── Public Subnets ────────────────────────────────────────────────────────────

resource "aws_subnet" "public" {
  count             = length(var.availability_zones)
  vpc_id            = aws_vpc.main.id
  cidr_block        = local.public_cidrs[count.index]
  availability_zone = var.availability_zones[count.index]

  # Nodes in public subnets get a public IP — NOT used for app nodes,
  # but required for NAT GW and ALB placement.
  map_public_ip_on_launch = true

  tags = {
    Name = "${local.name}-public-${var.availability_zones[count.index]}"
    "kubernetes.io/role/elb"                          = "1"   # ALB controller tag
    "kubernetes.io/cluster/${local.name}"             = "shared"
  }
}

# ── Private Subnets ───────────────────────────────────────────────────────────

resource "aws_subnet" "private" {
  count             = length(var.availability_zones)
  vpc_id            = aws_vpc.main.id
  cidr_block        = local.private_cidrs[count.index]
  availability_zone = var.availability_zones[count.index]

  tags = {
    Name = "${local.name}-private-${var.availability_zones[count.index]}"
    "kubernetes.io/role/internal-elb"                 = "1"   # Internal NLB tag
    "kubernetes.io/cluster/${local.name}"             = "shared"
  }
}

# ── NAT Gateway — single instance in first AZ (cost-optimised) ───────────────

resource "aws_eip" "nat" {
  domain = "vpc"
  tags   = { Name = "${local.name}-nat-eip" }

  depends_on = [aws_internet_gateway.main]
}

resource "aws_nat_gateway" "main" {
  allocation_id = aws_eip.nat.id
  subnet_id     = aws_subnet.public[0].id   # Always placed in first public subnet.

  tags = { Name = "${local.name}-nat" }

  depends_on = [aws_internet_gateway.main]
}

# ── Route Tables ──────────────────────────────────────────────────────────────

# Public: route all traffic to the Internet Gateway.
resource "aws_route_table" "public" {
  vpc_id = aws_vpc.main.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.main.id
  }

  tags = { Name = "${local.name}-public-rt" }
}

resource "aws_route_table_association" "public" {
  count          = length(aws_subnet.public)
  subnet_id      = aws_subnet.public[count.index].id
  route_table_id = aws_route_table.public.id
}

# Private: route outbound traffic through the single NAT Gateway.
resource "aws_route_table" "private" {
  vpc_id = aws_vpc.main.id

  route {
    cidr_block     = "0.0.0.0/0"
    nat_gateway_id = aws_nat_gateway.main.id
  }

  tags = { Name = "${local.name}-private-rt" }
}

resource "aws_route_table_association" "private" {
  count          = length(aws_subnet.private)
  subnet_id      = aws_subnet.private[count.index].id
  route_table_id = aws_route_table.private.id
}

# ── Security Groups ───────────────────────────────────────────────────────────

# Shared security group inherited by RDS, DocumentDB, and MQ.
# Only accepts traffic from within the VPC CIDR (EKS pods + other services).
resource "aws_security_group" "data_plane" {
  name        = "${local.name}-data-plane-sg"
  description = "Allow inbound from VPC only - shared by RDS, DocumentDB, Amazon MQ."
  vpc_id      = aws_vpc.main.id

  ingress {
    description = "PostgreSQL"
    from_port   = 5432
    to_port     = 5432
    protocol    = "tcp"
    cidr_blocks = [var.vpc_cidr]
  }

  ingress {
    description = "DocumentDB (MongoDB wire protocol)"
    from_port   = 27017
    to_port     = 27017
    protocol    = "tcp"
    cidr_blocks = [var.vpc_cidr]
  }

  ingress {
    description = "Amazon MQ - AMQP"
    from_port   = 5671
    to_port     = 5671
    protocol    = "tcp"
    cidr_blocks = [var.vpc_cidr]
  }

  ingress {
    description = "Amazon MQ - RabbitMQ management UI (restrict in prod)"
    from_port   = 15671
    to_port     = 15671
    protocol    = "tcp"
    cidr_blocks = [var.vpc_cidr]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = { Name = "${local.name}-data-plane-sg" }
}

# EKS worker node security group — allows full internal VPC traffic
# so pods can reach databases and the message broker without extra rules.
resource "aws_security_group" "eks_nodes" {
  name        = "${local.name}-eks-nodes-sg"
  description = "EKS worker nodes - full intra-VPC traffic allowed."
  vpc_id      = aws_vpc.main.id

  ingress {
    description = "All traffic from within VPC"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = [var.vpc_cidr]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = { Name = "${local.name}-eks-nodes-sg" }
}
