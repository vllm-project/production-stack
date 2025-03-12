resource "google_project_service" "services" {
    for_each = toset(var.gcp_services)
    disable_on_destroy = false
    project = var.project
    service = each.value
}

resource "time_sleep" "wait_60_seconds" {
    depends_on = [ google_project_service.services ]
    create_duration = "60s"
}
