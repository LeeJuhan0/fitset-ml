variable "aws_region" {
  default = "ap-northeast-2"
}

variable "instance_type" {
  default = "t3.small"
}

variable "repo_url" {
  description = "GitHub repo SSH URL (EC2 초기 클론용)"
  default     = "git@github.com:asm-hangang/fitset-ml-server.git"
}
