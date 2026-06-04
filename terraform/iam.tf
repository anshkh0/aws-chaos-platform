# =========================
# IAM: MONITORING INSTANCE
# Grants the monitoring EC2 instance permission to call
# ec2:DescribeInstances so Prometheus EC2 service discovery
# can find and scrape the app nodes automatically.
# =========================

resource "aws_iam_role" "monitoring_role" {
  name = "chaos-monitoring-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = { Service = "ec2.amazonaws.com" }
    }]
  })
}

resource "aws_iam_role_policy" "monitoring_ec2_read" {
  name = "chaos-monitoring-ec2-read"
  role = aws_iam_role.monitoring_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "ec2:DescribeInstances",
        "ec2:DescribeAvailabilityZones",
        "ec2:DescribeRegions",
        "ec2:DescribeTags"
      ]
      Resource = "*"
    }]
  })
}

resource "aws_iam_instance_profile" "monitoring_profile" {
  name = "chaos-monitoring-profile"
  role = aws_iam_role.monitoring_role.name
}
