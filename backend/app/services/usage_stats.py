"""Weekly usage aggregation from Cloud Run's own request logs.

Reads Cloud Logging directly rather than adding any new tracking — Cloud Run
already writes a request-log entry per HTTP call. Aggregates are computed
in-memory; IP addresses are only ever used to size a set and are discarded
before this function returns, so no IP address leaves this module.
"""

import logging
from collections import Counter
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

from google.cloud import logging as cloud_logging

logger = logging.getLogger(__name__)

_SERVICE_NAME = "mfs-backend"
_SERVICE_FILTER = f'resource.type="cloud_run_revision" resource.labels.service_name="{_SERVICE_NAME}"'
_TOP_PATHS_LIMIT = 5


def get_weekly_summary() -> dict:
    """Aggregate the trailing 7 days of backend request logs.

    Returns total requests, distinct visitor count, top request paths, and
    error count. No IP addresses or per-request rows are included.
    """
    since = datetime.now(timezone.utc) - timedelta(days=7)
    since_str = since.strftime("%Y-%m-%dT%H:%M:%SZ")

    client = cloud_logging.Client()

    request_filter = f'{_SERVICE_FILTER} httpRequest.status>=100 timestamp>="{since_str}"'
    total_requests = 0
    visitor_ips: set[str] = set()
    path_counts: Counter[str] = Counter()

    for entry in client.list_entries(filter_=request_filter):
        total_requests += 1
        http_request = getattr(entry, "http_request", None) or {}
        remote_ip = http_request.get("remoteIp")
        if remote_ip:
            visitor_ips.add(remote_ip)
        request_url = http_request.get("requestUrl", "")
        path = urlsplit(request_url).path or "(unknown)"
        path_counts[path] += 1

    distinct_visitors = len(visitor_ips)
    del visitor_ips  # aggregated already — don't carry raw IPs any further

    error_filter = f'{_SERVICE_FILTER} severity>=ERROR timestamp>="{since_str}"'
    error_count = sum(1 for _ in client.list_entries(filter_=error_filter))

    return {
        "window_days": 7,
        "total_requests": total_requests,
        "distinct_visitors": distinct_visitors,
        "error_count": error_count,
        "top_paths": [{"path": path, "count": count} for path, count in path_counts.most_common(_TOP_PATHS_LIMIT)],
    }
