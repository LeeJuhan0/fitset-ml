terraform {
  required_version = ">= 1.6"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    tls = {
      source  = "hashicorp/tls"
      version = "~> 4.0"
    }
  }

  backend "s3" {
    bucket = "fitset-tf-state"
    key    = "fitset-ml-server/terraform.tfstate"
    region = "ap-northeast-2"
  }
}

provider "aws" {
  region = var.aws_region
}

# ── SSH 키 ───────────────────────────────────────────────────────────────────

resource "tls_private_key" "deploy" {
  algorithm = "RSA"
  rsa_bits  = 4096
}

resource "aws_key_pair" "deploy" {
  key_name   = "fitset-ml-deploy"
  public_key = tls_private_key.deploy.public_key_openssh
}

# ── VPC ──────────────────────────────────────────────────────────────────────

resource "aws_vpc" "main" {
  cidr_block           = "10.0.0.0/16"
  enable_dns_support   = true
  enable_dns_hostnames = true
  tags = { Name = "fitset-ml-vpc" }
}

resource "aws_internet_gateway" "main" {
  vpc_id = aws_vpc.main.id
  tags   = { Name = "fitset-ml-igw" }
}

resource "aws_subnet" "public" {
  vpc_id                  = aws_vpc.main.id
  cidr_block              = "10.0.1.0/24"
  availability_zone       = "${var.aws_region}a"
  map_public_ip_on_launch = true
  tags = { Name = "fitset-ml-subnet-public" }
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.main.id
  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.main.id
  }
  tags = { Name = "fitset-ml-rt-public" }
}

resource "aws_route_table_association" "public" {
  subnet_id      = aws_subnet.public.id
  route_table_id = aws_route_table.public.id
}

# ── Security Group ───────────────────────────────────────────────────────────

resource "aws_security_group" "ml_server" {
  name        = "fitset-ml-sg"
  description = "FitSet ML Server"
  vpc_id      = aws_vpc.main.id

  ingress {
    description = "SSH"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    description = "FastAPI"
    from_port   = 8000
    to_port     = 8000
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    description = "MLflow UI"
    from_port   = 5001
    to_port     = 5001
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = { Name = "fitset-ml-sg" }
}

# ── IAM Role (S3 접근) ───────────────────────────────────────────────────────

resource "aws_iam_role" "ml_server" {
  name = "fitset-ml-server-role"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = { Service = "ec2.amazonaws.com" }
    }]
  })
}

resource "aws_iam_role_policy" "s3_access" {
  name = "fitset-s3-access"
  role = aws_iam_role.ml_server.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "s3:GetObject", "s3:PutObject", "s3:DeleteObject", "s3:ListBucket"
      ]
      Resource = [
        "arn:aws:s3:::fitset-dataset",
        "arn:aws:s3:::fitset-dataset/*",
        "arn:aws:s3:::fitset-models",
        "arn:aws:s3:::fitset-models/*",
      ]
    }]
  })
}

resource "aws_iam_instance_profile" "ml_server" {
  name = "fitset-ml-server-profile"
  role = aws_iam_role.ml_server.name
}

# ── EC2 (t3.small, ap-northeast-2a) ─────────────────────────────────────────

data "aws_ami" "amazon_linux_2023" {
  most_recent = true
  owners      = ["amazon"]
  filter {
    name   = "name"
    values = ["al2023-ami-*-x86_64"]
  }
}

resource "aws_instance" "ml_server" {
  ami                    = data.aws_ami.amazon_linux_2023.id
  instance_type          = var.instance_type
  subnet_id              = aws_subnet.public.id
  vpc_security_group_ids = [aws_security_group.ml_server.id]
  iam_instance_profile   = aws_iam_instance_profile.ml_server.name
  key_name               = aws_key_pair.deploy.key_name
  availability_zone      = "${var.aws_region}a"

  user_data = templatefile("${path.module}/user_data.sh", {
    repo_url = var.repo_url
  })

  root_block_device {
    volume_type           = "gp3"
    volume_size           = 30
    delete_on_termination = true
  }

  tags = { Name = "fitset-ml-server" }

  lifecycle {
    ignore_changes = [ami, user_data, root_block_device]
  }
}

# ── Elastic IP — 인스턴스 Stop/Start 해도 퍼블릭 IP 고정 ──────────────────────
resource "aws_eip" "ml_server" {
  domain   = "vpc"
  instance = aws_instance.ml_server.id
  tags     = { Name = "fitset-ml-server-eip" }
}

# ── EBS (gp3 20GB) — Stop 후에도 보존 ────────────────────────────────────────

resource "aws_ebs_volume" "mlflow_data" {
  availability_zone = "${var.aws_region}a"
  size              = 20
  type              = "gp3"
  tags              = { Name = "fitset-mlflow-data" }
}

resource "aws_volume_attachment" "mlflow_data" {
  device_name  = "/dev/xvdf"
  volume_id    = aws_ebs_volume.mlflow_data.id
  instance_id  = aws_instance.ml_server.id
  force_detach = false

  # DeleteOnTermination=false 는 별도 volume이므로 자동 보존됨
}
