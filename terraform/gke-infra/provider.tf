provider "google" {
  credentials = file(var.credentials_file)
  project = var.project
  zone = var.zone
}