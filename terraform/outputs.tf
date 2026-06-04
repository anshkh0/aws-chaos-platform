output "alb_dns_name" {
  description = "Your app URL — paste this into a browser to confirm the system is live"
  value       = aws_lb.app_lb.dns_name
}

output "vpc_id" {
  value = aws_vpc.main.id
}

output "public_subnet_a" {
  value = aws_subnet.public_a.id
}

output "public_subnet_b" {
  value = aws_subnet.public_b.id
}

output "alb_sg_id" {
  value = aws_security_group.alb_sg.id
}

output "ec2_sg_id" {
  value = aws_security_group.ec2_sg.id
}

output "monitoring_ip" {
  description = "Monitoring server public IP — Grafana: http://<ip>:3000 | Prometheus: http://<ip>:9090"
  value       = aws_instance.monitoring.public_ip
}
