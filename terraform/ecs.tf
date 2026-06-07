resource "aws_cloudwatch_log_group" "app" {
  name = "/ecs/chaos-platform-app"
  retention_in_days = 7
}

resource "aws_ecs_cluster" "app" {
  name = "chaos-platform-cluster"

  tags = {
    Name = "chaos-platform-cluster"
  }
}

resource "aws_ecs_task_definition" "app" {
  family = "chaos-platform-app"
  requires_compatibilities = ["FARGATE"]
  network_mode = "awsvpc"

  # 256 CPU units = 0.25 vCPU, 512MB memory
  cpu = "256"
  memory = "512"

  execution_role_arn = aws_iam_role.ecs_execution_role.arn
  task_role_arn = aws_iam_role.ecs_task_role.arn

  container_definitions = jsonencode([{
    name  = "app"
    image = "${aws_ecr_repository.app.repository_url}:latest"

    portMappings = [{
      containerPort = 5000
      protocol = "tcp"
    }]

    # Stream all container logs to CloudWatch automatically
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group" = aws_cloudwatch_log_group.app.name
        "awslogs-region" = var.aws_region
        "awslogs-stream-prefix" = "app"
      }
    }

    # decide if the container is healthy before registering it with the ALB
    healthCheck = {
      command = ["CMD-SHELL", "curl -f http://localhost:5000/health || exit 1"]
      interval = 30
      timeout = 5
      retries = 2
      startPeriod = 10
    }
  }])
}

resource "aws_security_group" "ecs_tasks_sg" {
  name = "chaos-ecs-tasks-sg"
  vpc_id = aws_vpc.main.id

  ingress {
    from_port = 5000
    to_port = 5000
    protocol = "tcp"
    security_groups = [aws_security_group.alb_sg.id]
  }

  egress {
    from_port = 0
    to_port = 0
    protocol = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}


resource "aws_lb_target_group" "ecs_tg" {
  name = "chaos-ecs-tg"
  port = 5000
  protocol = "HTTP"
  vpc_id = aws_vpc.main.id
  target_type = "ip"

  health_check {
    path = "/health"
    matcher = "200"
    interval = 30
    timeout = 5
    healthy_threshold = 2
    unhealthy_threshold = 2
  }
}


resource "aws_lb_listener_rule" "ecs" {
  listener_arn = aws_lb_listener.http.arn
  priority     = 100

  action {
    type = "forward"
    target_group_arn = aws_lb_target_group.ecs_tg.arn
  }

  condition {
    path_pattern {
      values = ["/*"]
    }
  }
}


resource "aws_ecs_service" "app" {
  name = "chaos-platform-service"
  cluster = aws_ecs_cluster.app.id
  task_definition = aws_ecs_task_definition.app.arn
  desired_count = 2
  launch_type = "FARGATE"

  # Spread tasks across both AZs for high availability
  network_configuration {
    subnets = [aws_subnet.public_a.id, aws_subnet.public_b.id]
    security_groups  = [aws_security_group.ecs_tasks_sg.id]
    assign_public_ip = true
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.ecs_tg.arn
    container_name = "app"
    container_port = 5000
  }

  #replaces one task at a time so there's
  deployment_minimum_healthy_percent = 50
  deployment_maximum_percent = 200

  depends_on = [aws_lb_listener_rule.ecs]

  tags = {
    Name = "chaos-platform-service"
  }
}



# OUTPUTS
output "ecs_cluster_name" {
  value = aws_ecs_cluster.app.name
}

output "ecs_service_name" {
  value = aws_ecs_service.app.name
}

output "ecs_target_group_arn" {
  value = aws_lb_target_group.ecs_tg.arn
}
