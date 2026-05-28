# -*- coding: utf-8 -*-
"""Minimal HTTPS transport over .NET HttpWebRequest (IronPython 2.7).

The IronPython 2.7 stdlib (urllib2 / httplib) has known TLS/SNI issues
against modern endpoints, so license traffic to api.keygen.sh goes
through the CLR's HttpWebRequest, which uses the .NET Framework 4.8 TLS
stack. This is the only networking module; keygen_client talks to it
through a single function so the orchestration above stays testable
under CPython with an injected mock transport.

    request(method, url, headers=None, body=None, timeout_ms=15000)
        -> (status_int, response_text)

A non-2xx HTTP response is returned normally as (status, body) so the
caller can read Keygen's JSON:API error codes. Connectivity / timeout
failures raise HttpError(0, ...).

This module imports clr at module load, so it is imported LAZILY by
keygen_client (never at CPython test time).
"""

import clr  # type: ignore
clr.AddReference("System")

from System.IO import StreamReader                    # type: ignore
from System.Text import Encoding                      # type: ignore
from System.Net import (                              # type: ignore
    HttpWebRequest, WebRequest, WebException,
    ServicePointManager, SecurityProtocolType,
)


class HttpError(Exception):
    """Network-level failure (DNS, connection refused, timeout, TLS).

    status is 0 for these. HTTP responses with a status code - including
    4xx/5xx - are returned normally, not raised, so the caller can read
    the body."""

    def __init__(self, status, message):
        super(HttpError, self).__init__(message)
        self.status = status


def _enable_modern_tls():
    proto = SecurityProtocolType.Tls12
    try:
        proto |= SecurityProtocolType.Tls13
    except (AttributeError, ValueError):
        pass
    ServicePointManager.SecurityProtocol = proto


_enable_modern_tls()


# Headers that HttpWebRequest exposes as typed properties and refuses to
# accept via Headers.Add - mapped case-insensitively to their setter.
_RESTRICTED = ("content-type", "accept", "user-agent")


def request(method, url, headers=None, body=None, timeout_ms=15000):
    """Perform an HTTP request. Returns (status_int, response_text)."""
    req = WebRequest.Create(url)        # HttpWebRequest for http(s) URLs
    req.Method = method
    req.Timeout = timeout_ms
    req.ReadWriteTimeout = timeout_ms

    restricted = {}
    for name, value in (headers or {}).items():
        if name.lower() in _RESTRICTED:
            restricted[name.lower()] = value
        else:
            req.Headers.Add(name, value)
    if "content-type" in restricted:
        req.ContentType = restricted["content-type"]
    if "accept" in restricted:
        req.Accept = restricted["accept"]
    if "user-agent" in restricted:
        req.UserAgent = restricted["user-agent"]

    if body is not None:
        data = Encoding.UTF8.GetBytes(body)
        req.ContentLength = data.Length
        stream = req.GetRequestStream()
        try:
            stream.Write(data, 0, data.Length)
        finally:
            stream.Close()

    try:
        response = req.GetResponse()
        return _read(response)
    except WebException as exc:
        # 4xx / 5xx arrive as WebException but carry a readable Response.
        if exc.Response is not None:
            return _read(exc.Response)
        raise HttpError(0, "Network error: {0}".format(exc.Message))
    except Exception as exc:
        raise HttpError(0, "Request failed: {0}".format(exc))


def _read(response):
    status = int(response.StatusCode.value__)
    reader = StreamReader(response.GetResponseStream(), Encoding.UTF8)
    try:
        text = reader.ReadToEnd()
    finally:
        reader.Close()
        response.Close()
    return status, text
