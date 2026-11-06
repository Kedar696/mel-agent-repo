# Amazon RDS for PostgreSQL for the REST API's state (surveys, hand-offs, answers, opt-outs): Digital Green's
# database. Definition only, like the rest of this folder; CI runs `terraform validate` on it.
# The master password is generated and kept by AWS Secrets Manager (manage_master_user_password), so no secret
# is in this file or in the state. The API reads MEL_DATABASE_URL built from `db_endpoint` and that secret.

variable "db_instance_class" {
  description = "RDS instance class for the API's PostgreSQL."
  type        = string
  default     = "db.t4g.micro"
}

data "aws_vpc" "default" {
  region  = var.ui_region
  default = true
}

data "aws_subnets" "default" {
  region = var.ui_region
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default.id]
  }
}

resource "aws_db_subnet_group" "api" {
  region     = var.ui_region
  name       = "${var.project_name}-api"
  subnet_ids = data.aws_subnets.default.ids
}

resource "aws_security_group" "db" {
  region      = var.ui_region
  name        = "${var.project_name}-api-db"
  description = "PostgreSQL from inside the VPC only (the API's tasks or pods)."
  vpc_id      = data.aws_vpc.default.id
  ingress {
    from_port   = 5432
    to_port     = 5432
    protocol    = "tcp"
    cidr_blocks = [data.aws_vpc.default.cidr_block]
  }
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_db_instance" "api" {
  region                      = var.ui_region
  identifier                  = "${var.project_name}-api"
  engine                      = "postgres"
  engine_version              = "16"
  instance_class              = var.db_instance_class
  allocated_storage           = 20
  db_name                     = "mel"
  username                    = "mel"
  manage_master_user_password = true
  db_subnet_group_name        = aws_db_subnet_group.api.name
  vpc_security_group_ids      = [aws_security_group.db.id]
  publicly_accessible         = false
  storage_encrypted           = true
  backup_retention_period     = 7
  skip_final_snapshot         = true
}

output "db_endpoint" {
  description = "Host:port of the API's PostgreSQL; MEL_DATABASE_URL = postgresql://mel:<password>@<this>/mel."
  value       = aws_db_instance.api.endpoint
}

output "db_master_secret_arn" {
  description = "Secrets Manager secret holding the master password (AWS manages it)."
  value       = aws_db_instance.api.master_user_secret[0].secret_arn
}
