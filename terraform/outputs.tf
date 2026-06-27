output "ec2_public_ip" {
  value = aws_eip.ml_server.public_ip
}

output "ec2_public_dns" {
  value = aws_eip.ml_server.public_dns
}

output "ssh_private_key" {
  value     = tls_private_key.deploy.private_key_pem
  sensitive = true
}
