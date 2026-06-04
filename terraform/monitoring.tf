resource "aws_instance" "monitoring" {
  ami           = data.aws_ami.amazon_linux.id
  instance_type = "t2.micro"

  subnet_id              = aws_subnet.public_a.id
  vpc_security_group_ids = [aws_security_group.monitoring_sg.id]

  # IAM profile gives Prometheus permission to call ec2:DescribeInstances
  iam_instance_profile = aws_iam_instance_profile.monitoring_profile.name

  key_name = "chaos-key"

  user_data = base64encode(<<-EOF
#!/bin/bash
set -e

dnf update -y
dnf install -y docker
systemctl enable docker
systemctl start docker
usermod -aG docker ec2-user || true

# Wait for Docker socket to be ready before running containers
timeout 60 bash -c 'until docker info &>/dev/null; do sleep 5; done'

# PROMETHEUS CONFIG
mkdir -p /etc/prometheus

cat > /etc/prometheus/prometheus.yml <<EOT
global:
  scrape_interval: 15s
  evaluation_interval: 15s

scrape_configs:

  # Prometheus self-monitoring
  - job_name: 'prometheus'
    static_configs:
      - targets: ['localhost:9090']

  # Node exporter on all app EC2 instances (port 9100)
  - job_name: 'node_exporter'
    ec2_sd_configs:
      - region: ${var.aws_region}
        port: 9100
        filters:
          - name: tag:Role
            values: ['app']
    relabel_configs:
      - source_labels: [__meta_ec2_private_ip]
        target_label: instance
      - source_labels: [__meta_ec2_availability_zone]
        target_label: availability_zone
      - source_labels: [__meta_ec2_tag_Name]
        target_label: name

  # App /metrics endpoint on all app EC2 instances (port 80)
  - job_name: 'app_metrics'
    fallback_scrape_protocol: PrometheusText0.0.4
    ec2_sd_configs:
      - region: ${var.aws_region}
        port: 80
        filters:
          - name: tag:Role
            values: ['app']
    metrics_path: '/metrics'
    relabel_configs:
      - source_labels: [__meta_ec2_private_ip]
        target_label: instance
EOT

# PROMETHEUS
docker run -d \
  --name prometheus \
  --network host \
  --restart unless-stopped \
  -v /etc/prometheus/prometheus.yml:/etc/prometheus/prometheus.yml \
  prom/prometheus

# GRAFANA
docker run -d \
  --name grafana \
  --restart unless-stopped \
  -p 3000:3000 \
  -e GF_SECURITY_ADMIN_USER=admin \
  -e GF_SECURITY_ADMIN_PASSWORD=chaos123 \
  grafana/grafana

EOF
  )

  tags = {
    Name = "monitoring-server"
  }
}
