"""Crawl the user's website (and any live subdomains) and ingest page text.

Subdomain discovery uses crt.sh (public certificate-transparency logs) -- a
passive lookup of certificates already issued for the domain, not a scan of
the target's infrastructure. Crawling itself respects robots.txt per host,
is rate-limited to be polite, and treats every fetch (including redirects)
as untrusted: each hop is re-validated against the allowed domain and against
the SSRF checks below before being followed.
"""
from __future__ import annotations

import contextlib
import ipaddress
import socket
import time
from collections import deque
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup

from app.config import config
from app.rag import vectorstore
from ingest.common import chunks_from_document, embed_and_store

USER_AGENT = "PersonalRAGBot/1.0 (+personal knowledge base crawler, owner-operated)"
REQUEST_DELAY_SECONDS = 0.4
REQUEST_TIMEOUT = 15
ALLOWED_SCHEMES = {"http", "https"}
MAX_REDIRECTS = 5
MAX_RESPONSE_BYTES = 5_000_000  # guards against decompression bombs / giant pages


def discover_subdomains(root_domain: str) -> list[str]:
    url = f"https://crt.sh/?q=%25.{root_domain}&output=json"
    try:
        resp = requests.get(url, timeout=20, headers={"User-Agent": USER_AGENT})
        resp.raise_for_status()
        entries = resp.json()
    except Exception as exc:  # crt.sh is a best-effort community service
        print(f"  subdomain discovery skipped ({exc})")
        return []

    hosts: set[str] = set()
    for entry in entries:
        for name in entry.get("name_value", "").splitlines():
            name = name.strip().lower().lstrip("*.")
            if name.endswith(root_domain):
                hosts.add(name)
    return sorted(hosts)


def _same_site(host: str, root_domain: str) -> bool:
    return host == root_domain or host.endswith(f".{root_domain}")


def _normalize_url(url: str) -> str:
    """Canonical form so 'https://x.com' and 'https://x.com/' aren't treated
    as two different pages. Real bug found live: an explicit .env seed
    (no trailing slash) and a crt.sh-discovered seed for the same host
    (always built with a trailing slash) both crawled the same page,
    doubling its chunks in the index under two different url metadata
    values."""
    parsed = urlparse(url)
    path = parsed.path.rstrip("/") or "/"
    return parsed._replace(path=path).geturl()


def _resolve_public_ip(host: str) -> str | None:
    """SSRF guard: resolve host and return its IP if that IP is public (not
    private/loopback/link-local/reserved/multicast/unspecified), or None
    otherwise -- even if the hostname itself matches the allowed domain
    (e.g. a stale or misconfigured DNS record pointing a subdomain at
    internal infra).

    Deliberately uncached. A previous version memoized this verdict
    indefinitely (@lru_cache) while the real HTTP client re-resolved the
    hostname independently at connect time -- a DNS-rebinding attacker only
    needed to change the DNS answer at any point during a multi-minute
    crawl run to have later requests land on a different address than the
    one that was validated. Returning the resolved IP (instead of just a
    bool) lets the caller pin its connection to this exact address via
    _pin_dns, so the validated address and the connected-to address can
    never diverge."""
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return None
    if not infos:
        return None
    for _family, _type, _proto, _canon, sockaddr in infos:
        try:
            ip = ipaddress.ip_address(sockaddr[0])
        except ValueError:
            return None
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified:
            return None
    return infos[0][4][0]


@contextlib.contextmanager
def _pin_dns(host: str, ip: str):
    """For the duration of one connection attempt, force getaddrinfo()
    lookups of `host` to return exactly the validated `ip`. The Host
    header, TLS SNI, and certificate hostname verification all still
    operate on `host` (nothing here touches the URL string), so HTTPS
    correctness is preserved -- only the DNS answer used to open the
    socket is constrained to the address that was just validated. Safe in
    this single-threaded, synchronous crawler; not safe to use from
    concurrent code without a lock."""
    real_getaddrinfo = socket.getaddrinfo

    def pinned(h, *args, **kwargs):
        if h == host:
            return real_getaddrinfo(ip, *args, **kwargs)
        return real_getaddrinfo(h, *args, **kwargs)

    socket.getaddrinfo = pinned
    try:
        yield
    finally:
        socket.getaddrinfo = real_getaddrinfo


def _is_safe_url(url: str, root_domain: str) -> tuple[bool, str | None]:
    """Returns (is_safe, validated_ip). Callers that go on to fetch `url`
    must pin their connection to validated_ip via _pin_dns rather than
    letting the HTTP client re-resolve the hostname independently (see
    _resolve_public_ip's docstring for why)."""
    parsed = urlparse(url)
    if parsed.scheme not in ALLOWED_SCHEMES:
        return False, None
    if "@" in parsed.netloc:
        # Reject embedded userinfo outright: legitimate crawl targets never
        # need it, and it is the classic authority-confusion SSRF vector --
        # parsed.netloc.split(':')[0] used to return the userinfo username
        # here (e.g. "<root_domain>" in "<root_domain>:1234@evil-host")
        # instead of the real host that requests/urllib3 actually connect
        # to, letting a URL with a trusted-looking userinfo segment sail
        # through both the domain allowlist and the public-IP check below
        # while the real TCP connection went to an attacker-chosen host.
        return False, None
    host = (parsed.hostname or "").lower()
    if not host or not _same_site(host, root_domain):
        return False, None
    ip = _resolve_public_ip(host)
    return (ip is not None), ip


def _get_robot_parser(
    session: requests.Session, host_root: str, host: str, ip: str, cache: dict[str, RobotFileParser]
) -> RobotFileParser:
    """Fetch and parse robots.txt through our own session (with our real
    User-Agent) rather than RobotFileParser.read()'s built-in fetcher.

    Real bug found live: RobotFileParser.read() uses a bare urllib call with
    Python's default User-Agent, which Cloudflare's bot-management blocked
    with a 403 (error 1010) even though our actual crawler UA was never
    blocked. read() treats a 403 on robots.txt as "disallow everything" (the
    correct, standard interpretation of an auth-gated robots.txt) -- so every
    Cloudflare-fronted site got fully skipped despite explicitly allowing
    crawling (`Allow: /`), and completely silently, since this happened
    before any per-page diagnostic could fire."""
    if host_root not in cache:
        rp = RobotFileParser()
        robots_url = urljoin(host_root, "/robots.txt")
        rp.set_url(robots_url)
        try:
            with _pin_dns(host, ip):
                resp = session.get(robots_url, timeout=REQUEST_TIMEOUT)
            if resp.status_code in (401, 403):
                rp.disallow_all = True
            elif resp.status_code >= 400:
                rp.allow_all = True
            else:
                rp.parse(resp.text.splitlines())
        except requests.RequestException:
            pass  # unreachable robots.txt: RobotFileParser's default (unparsed) state is permissive
        cache[host_root] = rp
    return cache[host_root]


def _fetch_capped(session: requests.Session, url: str, host: str, ip: str) -> requests.Response | None:
    """GET with a hard cap on response size, streamed so a lying/huge body
    never gets fully buffered in memory. Pinned to the already-validated
    `ip` for the duration of the connection (see _pin_dns)."""
    with _pin_dns(host, ip):
        resp = session.get(url, timeout=REQUEST_TIMEOUT, allow_redirects=False, stream=True)
        declared_length = resp.headers.get("content-length")
        if declared_length and int(declared_length) > MAX_RESPONSE_BYTES:
            resp.close()
            return None

        chunks = []
        total = 0
        for chunk in resp.iter_content(chunk_size=65536):
            total += len(chunk)
            if total > MAX_RESPONSE_BYTES:
                resp.close()
                return None
            chunks.append(chunk)
        resp._content = b"".join(chunks)  # populate .text/.json() from what we already read
    return resp


def _fetch_following_safe_redirects(
    session: requests.Session, url: str, root_domain: str
) -> tuple[str, requests.Response] | None:
    """Manual redirect loop: every hop (not just the initial URL) is
    re-validated -- including a fresh DNS resolution pinned to the
    connection -- so a same-domain page can't 302 the crawler into fetching
    localhost/an internal IP/a different domain, and no cached verdict from
    an earlier hop or an earlier page can go stale by the time this hop's
    connection is actually opened."""
    current = url
    for _ in range(MAX_REDIRECTS + 1):
        is_safe, ip = _is_safe_url(current, root_domain)
        if not is_safe:
            return None
        host = urlparse(current).hostname or ""
        resp = _fetch_capped(session, current, host, ip)
        if resp is None:
            return None
        if resp.is_redirect or resp.is_permanent_redirect:
            location = resp.headers.get("location")
            if not location:
                return None
            current = urljoin(current, location).split("#")[0]
            continue
        return current, resp
    return None  # too many redirects


def extract_text(html: str) -> tuple[str, str]:
    soup = BeautifulSoup(html, "html.parser")
    title = soup.title.string.strip() if soup.title and soup.title.string else ""

    for tag in soup(["script", "style", "nav", "footer", "header", "aside", "noscript"]):
        tag.decompose()

    main = soup.find("main") or soup.find("article") or soup.body or soup
    lines = [line.strip() for line in main.get_text(separator="\n").splitlines()]
    text = "\n".join(line for line in lines if line)
    return title, text


def crawl(seed_urls: list[str], root_domain: str, max_pages: int):
    """Yields (url, title, text) for each page successfully crawled."""
    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT

    robots_cache: dict[str, RobotFileParser] = {}
    visited: set[str] = set()
    queue: deque[str] = deque(seed_urls)
    pages_fetched = 0

    while queue and pages_fetched < max_pages:
        url = _normalize_url(queue.popleft().split("#")[0])
        if url in visited:
            continue
        visited.add(url)
        is_safe, ip = _is_safe_url(url, root_domain)
        if not is_safe:
            print(f"  skip {url} (failed safety check)")
            continue

        parsed = urlparse(url)
        host = parsed.hostname or ""
        host_root = f"{parsed.scheme}://{host}" + (f":{parsed.port}" if parsed.port else "")
        robots = _get_robot_parser(session, host_root, host, ip, robots_cache)
        if not robots.can_fetch(USER_AGENT, url):
            print(f"  skip {url} (disallowed by robots.txt)")
            continue

        try:
            fetched = _fetch_following_safe_redirects(session, url, root_domain)
        except requests.RequestException as exc:
            print(f"  skip {url} ({exc})")
            continue

        if fetched is None:
            print(f"  skip {url} (fetch failed: too many redirects, size cap, or unsafe redirect target)")
            continue
        final_url, resp = fetched
        content_type = resp.headers.get("content-type", "")
        if resp.status_code >= 400 or "text/html" not in content_type:
            print(f"  skip {url} (status {resp.status_code}, content-type {content_type!r})")
            continue

        title, text = extract_text(resp.text)
        if not text:
            print(f"  skip {url} (no extractable text -- likely a JS-rendered page with an empty static HTML body)")
            continue
        pages_fetched += 1
        yield final_url, title, text

        soup = BeautifulSoup(resp.text, "html.parser")
        for a in soup.find_all("a", href=True):
            link = urljoin(final_url, a["href"]).split("#")[0]
            if link not in visited:
                queue.append(link)

        time.sleep(REQUEST_DELAY_SECONDS)


def _purge_stale_pages(kept_urls: set[str]) -> None:
    stored_urls = {
        m["url"] for m in vectorstore.list_metadatas({"source": "website"}) if m.get("url")
    }
    for stale in stored_urls - kept_urls:
        print(f"purging stale page from index: {stale}")
        vectorstore.delete_where({"source": "website", "url": stale})


def _diagnose_unsafe_seed(url: str, root_domain: str) -> str:
    """Explain why a seed URL was rejected, so a silent zero-page crawl isn't
    a mystery (this bit us during testing: crt.sh was down AND the apex
    domain had no A/AAAA record, so every seed failed with no explanation)."""
    parsed = urlparse(url)
    if parsed.scheme not in ALLOWED_SCHEMES:
        return f"scheme {parsed.scheme!r} is not http/https"
    if "@" in parsed.netloc:
        return "URL contains userinfo (user:pass@host), which is rejected outright"
    host = (parsed.hostname or "").lower()
    if not host or not _same_site(host, root_domain):
        return f"host {host!r} does not match {root_domain!r}"
    try:
        socket.getaddrinfo(host, None)
    except socket.gaierror:
        return f"{host!r} does not resolve (no DNS record)"
    return f"{host!r} resolves to a private/reserved IP address"


def ingest() -> None:
    seeds = list(config.website_seed_urls)

    if config.website_discover_subdomains:
        print(f"Discovering subdomains of {config.website_root_domain} via crt.sh ...")
        hosts = discover_subdomains(config.website_root_domain)
        print(f"  found {len(hosts)} candidate host(s): {', '.join(hosts) or '(none)'}")
        for host in hosts:
            seeds.append(f"https://{host}/")

    print(f"Crawling from {len(seeds)} seed URL(s), max {config.website_max_pages} pages...")
    for seed in seeds:
        is_safe, _ip = _is_safe_url(seed, config.website_root_domain)
        if not is_safe:
            reason = _diagnose_unsafe_seed(seed, config.website_root_domain)
            print(f"  seed rejected: {seed} ({reason})")

    kept_urls: set[str] = set()
    for url, title, text in crawl(seeds, config.website_root_domain, config.website_max_pages):
        kept_urls.add(url)
        metadata = {"source": "website", "url": url, "title": title}
        page_chunks = chunks_from_document(url, text, metadata)
        # Clear this page's previous chunks first so a shrunk/edited page
        # doesn't leave stale chunks behind alongside the fresh ones.
        vectorstore.delete_where({"source": "website", "url": url})
        print(f"  {url} -> {len(page_chunks)} chunks")
        embed_and_store(page_chunks, label=f"chunks ({url})")

    _purge_stale_pages(kept_urls)


if __name__ == "__main__":
    ingest()
