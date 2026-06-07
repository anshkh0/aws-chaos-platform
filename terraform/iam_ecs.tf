# =============================================================
# ECS TASK EXECUTION ROLE
# Used by ECS itself (not your app) to:
# - Pull your image from ECR
# - Write logs to CloudWatch
# =============================================================
resource "aws_iam_role" "ecs_execution_role" {
  name = "chaos-ecs-execution-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = { Service = "ecs-tasks.amazonaws.com" }
    }]
  })
}

# AWS managed policy — gives ECS everything it needs to pull images
# and write logs without us having to define each permission manually
resource "aws_iam_role_policy_attachment" "ecs_execution_role_policy" {
  role       = aws_iam_role.ecs_execution_role.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}


# =============================================================
# ECS TASK ROLE
# Used by YOUR APP CODE running inside the container.
# Add permissions here if your app needs to call AWS services.
# Currently empty — the Flask app doesn't call any AWS APIs.
# =============================================================
resource "aws_iam_role" "ecs_task_role" {
  name = "chaos-ecs-task-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = { Service = "ecs-tasks.amazonaws.com" }
    }]
  })
}
