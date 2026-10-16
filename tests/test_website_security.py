"""Regression tests for the website crawler's SSRF defenses.

These exercise real bugs found in a security review: the crawler originally
followed redirects (allow_redirects=True) without re-validating the target,
so a same-domain page could 302 it into fetching localhost/an internal IP;
later, a security audit found two more real gaps -- host extraction via
naive netloc.split(':') confused userinfo for the real host (a URL like
'http://<root>:1@evil-host' passed the allowlist while the real connection
went to evil-host), and the public-IP verdict was cached indefinitely while
the real HTTP client re-resolved DNS independently at connect time (a
DNS-rebinding TOCTOU gap).
"""
from ingest import website_ingest as wi

ROOT = "syedmohammedsultan.online"


def test_normalize_url_collapses_trailing_slash_variants():
    """Regression test: a live run double-crawled portfolio.<domain> because
    an explicit .env seed (no trailing slash) and a crt.sh-discovered seed
    (always has one) weren't recognized as the same page."""
    assert wi._normalize_url("https://x.test") == wi._normalize_url("https://x.test/")
    assert wi._normalize_url("https://x.test/page") == wi._normalize_url("https://x.test/page/")


def test_same_site_accepts_root_and_subdomains():
    assert wi._same_site(ROOT, ROOT)
    assert wi._same_site(f"blog.{ROOT}", ROOT)


def test_same_site_rejects_lookalike_domain():
    # classic bypass: "evil<root>" is NOT a subdomain of <root> -- it just
    # happens to contain the string. endswith(".<root>") must reject it.
    assert not wi._same_site(f"evil{ROOT}", ROOT)
    assert not wi._same_site(f"{ROOT}.evil.com", ROOT)


def test_resolve_public_ip_rejects_loopback():
    assert wi._resolve_public_ip("127.0.0.1") is None


def test_resolve_public_ip_rejects_cloud_metadata_address():
    # 169.254.169.254 is the AWS/GCP/Azure instance-metadata address -- a
    # classic SSRF target and exactly the class of address this must block.
    assert wi._resolve_public_ip("169.254.169.254") is None


def test_resolve_public_ip_rejects_unresolvable_host():
    assert wi._resolve_public_ip("this-host-should-not-exist.invalid") is None


def test_resolve_public_ip_returns_the_resolved_address_when_safe():
    # A real, stable public IP literal -- ip_address() short-circuits any
    # actual DNS lookup for a literal, so this doesn't touch the network.
    assert wi._resolve_public_ip("93.184.216.34") == "93.184.216.34"


def test_resolve_public_ip_is_not_cached_across_calls(monkeypatch):
    """Regression test for the DNS-rebinding TOCTOU gap: a previous version
    wrapped this in @lru_cache, so a hostname's first (public) resolution
    stayed valid for the rest of the process even if DNS later changed to a
    private address. This must re-resolve every single call."""
    answers = iter(["93.184.216.34", "127.0.0.1"])

    def fake_getaddrinfo(host, *_a, **_k):
        ip = next(answers)
        return [(wi.socket.AF_INET, wi.socket.SOCK_STREAM, 6, "", (ip, 0))]

    monkeypatch.setattr(wi.socket, "getaddrinfo", fake_getaddrinfo)

    assert wi._resolve_public_ip("rebind.example") == "93.184.216.34"  # first answer: public
    assert wi._resolve_public_ip("rebind.example") is None  # second answer: private -- must not reuse a stale verdict


def test_is_safe_url_rejects_non_http_scheme():
    assert wi._is_safe_url(f"ftp://{ROOT}/file", ROOT)[0] is False
    assert wi._is_safe_url(f"file:///etc/passwd", ROOT)[0] is False


def test_is_safe_url_rejects_off_domain_target():
    assert wi._is_safe_url("https://attacker.example/", ROOT)[0] is False


def test_is_safe_url_rejects_userinfo_authority_confusion(monkeypatch):
    """Regression test for the audit-confirmed bypass: parsed.netloc.split(
    ':')[0] used to return the userinfo segment (e.g. the trusted-looking
    root domain) instead of the real host that requests/urllib3 actually
    connect to, letting a crafted 'user:port@attacker-host' URL sail through
    the domain allowlist entirely."""
    # Even if the "host" _resolve_public_ip would see were allowed through,
    # a URL with userinfo in its authority must be rejected before that
    # check ever runs.
    monkeypatch.setattr(wi, "_resolve_public_ip", lambda host: "203.0.113.1")
    is_safe, ip = wi._is_safe_url(f"http://{ROOT}:1@169.254.169.254/x", ROOT)
    assert is_safe is False
    assert ip is None


def test_is_safe_url_returns_the_validated_ip_on_success(monkeypatch):
    monkeypatch.setattr(wi, "_resolve_public_ip", lambda host: "203.0.113.1")
    is_safe, ip = wi._is_safe_url(f"https://{ROOT}/page", ROOT)
    assert is_safe is True
    assert ip == "203.0.113.1"


def test_fetch_following_safe_redirects_refuses_unsafe_redirect_target(monkeypatch):
    """The core regression test: a same-domain start URL that redirects to a
    hostname resolving to a private IP must be refused, and the crawler must
    never issue a second request to that unsafe target."""

    class FakeResponse:
        def __init__(self, *, redirect: bool, location: str = ""):
            self.is_redirect = redirect
            self.is_permanent_redirect = False
            self.status_code = 302 if redirect else 200
            self.headers = {"location": location} if redirect else {}

    calls = []

    def fake_fetch_capped(session, url, host, ip):
        calls.append(url)
        if url == f"https://{ROOT}/start":
            return FakeResponse(redirect=True, location=f"http://internal.{ROOT}/secret")
        raise AssertionError(f"crawler followed an unsafe redirect to {url}")

    # The redirect target superficially matches the domain filter, but its
    # (mocked) DNS resolution is private -- this is the exact "misconfigured
    # subdomain points at internal infra" scenario the IP check exists for.
    monkeypatch.setattr(
        wi, "_resolve_public_ip", lambda host: None if host == f"internal.{ROOT}" else "203.0.113.1"
    )
    monkeypatch.setattr(wi, "_fetch_capped", fake_fetch_capped)

    result = wi._fetch_following_safe_redirects(session=None, url=f"https://{ROOT}/start", root_domain=ROOT)

    assert result is None
    assert calls == [f"https://{ROOT}/start"]  # the unsafe target was never fetched


def test_fetch_capped_pins_dns_to_the_validated_ip(monkeypatch):
    """The connection must be pinned to the already-validated IP rather than
    letting the HTTP client re-resolve the hostname independently -- that
    independent re-resolution is exactly the TOCTOU gap this closes."""

    class FakeResp:
        headers: dict = {}

        def iter_content(self, chunk_size):
            return iter([])

        def close(self):
            pass

    seen_hosts = []

    class FakeSession:
        def get(self, *a, **k):
            # Exercise the pin: resolve the same host _fetch_capped was
            # given and confirm it comes back as the pinned IP, not
            # whatever a real DNS lookup would return.
            seen_hosts.append(wi.socket.getaddrinfo("pinned.example", None))
            return FakeResp()

    wi._fetch_capped(FakeSession(), "https://pinned.example/page", "pinned.example", "203.0.113.9")

    assert seen_hosts[0][0][4][0] == "203.0.113.9"
    # The override must not leak past the `with` block.
    assert wi.socket.getaddrinfo is not None
    real_result = wi.socket.getaddrinfo("127.0.0.1", None)
    assert real_result[0][4][0] == "127.0.0.1"  # unrelated host resolves normally again


def test_fetch_capped_rejects_oversized_content_length(monkeypatch):
    class FakeResp:
        headers = {"content-length": str(wi.MAX_RESPONSE_BYTES + 1)}

        def close(self):
            pass

    class FakeSession:
        def get(self, *a, **k):
            return FakeResp()

    assert wi._fetch_capped(FakeSession(), "https://example/big", "example", "203.0.113.1") is None


def test_get_robot_parser_uses_our_session_not_urllib_default(monkeypatch):
    """Regression test: RobotFileParser.read() fetches with Python's default
    urllib User-Agent, which got a real 403 from Cloudflare (bot-management)
    even though our actual crawler UA was never blocked -- read() then
    silently disallows the entire site. Fetching through our own session
    (with our real UA) instead must correctly parse a permissive robots.txt."""

    class FakeResp:
        status_code = 200
        text = "User-agent: *\nAllow: /\n"

    class FakeSession:
        def get(self, url, timeout):
            return FakeResp()

    rp = wi._get_robot_parser(FakeSession(), "https://example.test", "example.test", "203.0.113.1", {})
    assert rp.can_fetch("AnyBot/1.0", "https://example.test/anything") is True


def test_get_robot_parser_treats_403_as_disallow_all(monkeypatch):
    class FakeResp:
        status_code = 403
        text = ""

    class FakeSession:
        def get(self, url, timeout):
            return FakeResp()

    rp = wi._get_robot_parser(FakeSession(), "https://example.test", "example.test", "203.0.113.1", {})
    assert rp.can_fetch("AnyBot/1.0", "https://example.test/anything") is False


def test_get_robot_parser_treats_404_as_allow_all(monkeypatch):
    class FakeResp:
        status_code = 404
        text = ""

    class FakeSession:
        def get(self, url, timeout):
            return FakeResp()

    rp = wi._get_robot_parser(FakeSession(), "https://example.test", "example.test", "203.0.113.1", {})
    assert rp.can_fetch("AnyBot/1.0", "https://example.test/anything") is True


def test_fetch_capped_rejects_decompression_bomb_by_actual_size(monkeypatch):
    """No Content-Length header is declared, but the decoded body exceeds the
    cap -- this is what a decompression bomb looks like on the wire."""

    class FakeResp:
        headers: dict = {}

        def iter_content(self, chunk_size):
            chunk = b"a" * chunk_size
            for _ in range(wi.MAX_RESPONSE_BYTES // chunk_size + 5):
                yield chunk

        def close(self):
            pass

    class FakeSession:
        def get(self, *a, **k):
            return FakeResp()

    assert wi._fetch_capped(FakeSession(), "https://example/bomb", "example", "203.0.113.1") is None
