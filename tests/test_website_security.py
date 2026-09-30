"""Regression tests for the website crawler's SSRF defenses.

These exercise real bugs found in a security review: the crawler originally
followed redirects (allow_redirects=True) without re-validating the target,
so a same-domain page could 302 it into fetching localhost/an internal IP.
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


def test_resolves_to_public_ip_rejects_loopback():
    assert wi._resolves_to_public_ip("127.0.0.1") is False


def test_resolves_to_public_ip_rejects_cloud_metadata_address():
    # 169.254.169.254 is the AWS/GCP/Azure instance-metadata address -- a
    # classic SSRF target and exactly the class of address this must block.
    assert wi._resolves_to_public_ip("169.254.169.254") is False


def test_resolves_to_public_ip_rejects_unresolvable_host():
    assert wi._resolves_to_public_ip("this-host-should-not-exist.invalid") is False


def test_is_safe_url_rejects_non_http_scheme():
    assert wi._is_safe_url(f"ftp://{ROOT}/file", ROOT) is False
    assert wi._is_safe_url(f"file:///etc/passwd", ROOT) is False


def test_is_safe_url_rejects_off_domain_target():
    assert wi._is_safe_url("https://attacker.example/", ROOT) is False


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

    def fake_fetch_capped(session, url):
        calls.append(url)
        if url == f"https://{ROOT}/start":
            return FakeResponse(redirect=True, location=f"http://internal.{ROOT}/secret")
        raise AssertionError(f"crawler followed an unsafe redirect to {url}")

    # The redirect target superficially matches the domain filter, but its
    # (mocked) DNS resolution is private -- this is the exact "misconfigured
    # subdomain points at internal infra" scenario the IP check exists for.
    monkeypatch.setattr(wi, "_resolves_to_public_ip", lambda host: host != f"internal.{ROOT}")
    monkeypatch.setattr(wi, "_fetch_capped", fake_fetch_capped)

    result = wi._fetch_following_safe_redirects(session=None, url=f"https://{ROOT}/start", root_domain=ROOT)

    assert result is None
    assert calls == [f"https://{ROOT}/start"]  # the unsafe target was never fetched


def test_fetch_capped_rejects_oversized_content_length(monkeypatch):
    class FakeResp:
        headers = {"content-length": str(wi.MAX_RESPONSE_BYTES + 1)}

        def close(self):
            pass

    class FakeSession:
        def get(self, *a, **k):
            return FakeResp()

    assert wi._fetch_capped(FakeSession(), "https://example/big") is None


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

    rp = wi._get_robot_parser(FakeSession(), "https://example.test", {})
    assert rp.can_fetch("AnyBot/1.0", "https://example.test/anything") is True


def test_get_robot_parser_treats_403_as_disallow_all(monkeypatch):
    class FakeResp:
        status_code = 403
        text = ""

    class FakeSession:
        def get(self, url, timeout):
            return FakeResp()

    rp = wi._get_robot_parser(FakeSession(), "https://example.test", {})
    assert rp.can_fetch("AnyBot/1.0", "https://example.test/anything") is False


def test_get_robot_parser_treats_404_as_allow_all(monkeypatch):
    class FakeResp:
        status_code = 404
        text = ""

    class FakeSession:
        def get(self, url, timeout):
            return FakeResp()

    rp = wi._get_robot_parser(FakeSession(), "https://example.test", {})
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

    assert wi._fetch_capped(FakeSession(), "https://example/bomb") is None
