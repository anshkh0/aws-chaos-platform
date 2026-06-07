# AMI
data "aws_ami" "amazon_linux" {
  most_recent = true
  owners      = ["amazon"]

  filter {
    name   = "name"
    values = ["al2023-ami-*"]
  }
}

# LAUNCH TEMPLATE
resource "aws_launch_template" "app_lt" {
  name_prefix   = "chaos-app-"
  image_id      = data.aws_ami.amazon_linux.id
  instance_type = "t2.micro"

  key_name = "chaos-key"

  vpc_security_group_ids = [aws_security_group.ec2_sg.id]

  user_data = base64encode(<<-EOF
#!/bin/bash
set -e
set -o pipefail

dnf install -y httpd tar

systemctl enable httpd
systemctl start httpd

# WEB APP
echo "OK - Chaos Platform Running" > /var/www/html/index.html

# Health endpoint
echo "OK" > /var/www/html/health
chmod 644 /var/www/html/health

# Metrics endpoint
cat > /var/www/html/metrics <<EOT
http_requests_total 42
cpu_usage_mock 0.12
memory_usage_mock 0.33
EOT
chmod 644 /var/www/html/metrics

# NODE EXPORTER
(
  useradd -rs /bin/false node_exporter 2>/dev/null || true

  NODE_EXPORTER_VERSION=1.8.1
  cd /tmp
  curl -sfLO "https://github.com/prometheus/node_exporter/releases/download/v$${NODE_EXPORTER_VERSION}/node_exporter-$${NODE_EXPORTER_VERSION}.linux-amd64.tar.gz"
  tar xzf "node_exporter-$${NODE_EXPORTER_VERSION}.linux-amd64.tar.gz"
  cp "node_exporter-$${NODE_EXPORTER_VERSION}.linux-amd64/node_exporter" /usr/local/bin/
  chmod +x /usr/local/bin/node_exporter

  cat > /etc/systemd/system/node_exporter.service <<EOT
[Unit]
Description=Prometheus Node Exporter
After=network.target

[Service]
User=node_exporter
ExecStart=/usr/local/bin/node_exporter
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOT

  systemctl daemon-reload
  systemctl enable node_exporter
  systemctl start node_exporter
) || echo "WARNING: node_exporter setup failed — Apache and /health are still active"

EOF
  )
}

# APPLICATION LOAD BALANCER
resource "aws_lb" "app_lb" {
  name               = "chaos-alb"
  load_balancer_type = "application"

  subnets = [
    aws_subnet.public_a.id,
    aws_subnet.public_b.id
  ]

  security_groups = [aws_security_group.alb_sg.id]
}

# TARGET GROUP
resource "aws_lb_target_group" "app_tg" {
  name     = "chaos-tg"
  port     = 80
  protocol = "HTTP"
  vpc_id   = aws_vpc.main.id

  health_check {
    path                = "/health"
    matcher             = "200"
    interval            = 30
    timeout             = 5
    healthy_threshold   = 2
    unhealthy_threshold = 2
  }
}

# LISTENER
resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.app_lb.arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.app_tg.arn
  }
}

# AUTO SCALING GROUP
resource "aws_autoscaling_group" "app_asg" {
  name                = "chaos-app-asg"
  desired_capacity    = 2
  max_size            = 3
  min_size            = 1

  vpc_zone_identifier = [
    aws_subnet.public_a.id,
    aws_subnet.public_b.id
  ]

 
  launch_template {
    id      = aws_launch_template.app_lt.id
    version = aws_launch_template.app_lt.latest_version
  }

  target_group_arns = [aws_lb_target_group.app_tg.arn]

  health_check_type         = "ELB"
  health_check_grace_period = 300

  # Rolling refresh: when the launch template version changes, Terraform automatically replaces instances without full teardown.
  instance_refresh {
    strategy = "Rolling"
    preferences {
      min_healthy_percentage = 50
    }
  }

  # Name tag for console visibility
  tag {
    key = "Name"
    value = "chaos-app"
    propagate_at_launch = true
  }

  # Role tag:
  tag {
    key = "Role"
    value = "app"
    propagate_at_launch = true
  }
}
