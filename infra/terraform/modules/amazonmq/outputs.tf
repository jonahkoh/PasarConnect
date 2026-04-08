output "mq_broker_id"       { value = aws_mq_broker.main.id }
output "mq_amqps_endpoint"  { value = tolist(aws_mq_broker.main.instances[0].endpoints)[0] }
output "mq_console_url"     { value = "https://${aws_mq_broker.main.instances[0].console_url}" }
