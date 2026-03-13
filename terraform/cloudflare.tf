# ─── Cloudflare DNS ───────────────────────────────────────────────────────────

# API subdomain → Cloud Run
resource "cloudflare_record" "api" {
  zone_id = var.cloudflare_zone_id
  name    = "api"
  content = trimprefix(google_cloud_run_v2_service.backend.uri, "https://")
  type    = "CNAME"
  proxied = true
}
