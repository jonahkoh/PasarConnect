variable "project"             { type = string }
variable "environment"         { type = string }
variable "private_subnet_ids"  { type = list(string) }
variable "data_plane_sg_id"    { type = string }
variable "mq_instance_type"    { type = string }
variable "mq_username"         { type = string }
variable "mq_password" {
  type      = string
  sensitive = true
}
