variable "project"               { type = string }
variable "environment"           { type = string }
variable "private_subnet_ids"    { type = list(string) }
variable "data_plane_sg_id"      { type = string }
variable "docdb_instance_class"  { type = string }
variable "docdb_master_username" { type = string }
variable "docdb_master_password" {
  type      = string
  sensitive = true
}
