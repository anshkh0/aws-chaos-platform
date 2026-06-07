# Stores your Docker images — GitHub Actions pushes here,
# ECS pulls from here on every deployment
resource "aws_ecr_repository" "app" {
  name                 = "chaos-platform-app"
  image_tag_mutability = "MUTABLE"

  # Scan every image for known CVEs on push —
  # catches vulnerable dependencies before they hit ECS
  image_scanning_configuration {
    scan_on_push = true
  }

  tags = {
    Name = "chaos-platform-app"
  }
}

# Only keep the 10 most recent images — older ones get deleted automatically
# Prevents ECR storage costs from growing unbounded
resource "aws_ecr_lifecycle_policy" "app" {
  repository = aws_ecr_repository.app.name

  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep last 10 images"
      selection = {
        tagStatus   = "any"
        countType   = "imageCountMoreThan"
        countNumber = 10
      }
      action = { type = "expire" }
    }]
  })
}

output "ecr_repository_url" {
  description = "ECR URL — GitHub Actions pushes images here"
  value       = aws_ecr_repository.app.repository_url
}
