"""
This module passes the end user's address along to OBP-API in the X-Forwarded-For header.

The problem it solves: Opey does not call OBP-API directly on the user's behalf. A request
starts in the user's browser, passes through API Explorer II, reaches Opey, and Opey's
tools (the OBP-MCP server) make the actual OBP-API request. Without help, OBP-API would see
every request as coming from OBP-MCP, so its per-address rate limits, address penalties and
busiest-callers view would all see a single address.

The convention used across the chain is the ordinary X-Forwarded-For one: every hop appends
the address of the peer it received the request from, and forwards the list. Opey
therefore takes the list it received from API Explorer II, appends API Explorer II's
address, and hands the result to each OBP tool call. OBP-MCP appends Opey's address before
calling OBP-API.

Opey keeps no list of trusted addresses. OBP-API alone decides whom to believe: it reads
the list from the right, skips every address in its `trust.proxy.peers` Prop, and takes
the first address that is not trusted as the client. So a forged value at the left of the
list is never reached, and a caller that is not trusted is itself taken as the client.

Tool arguments are written by the model, so a model (or a prompt injection) could put its
own address headers there. `with_forwarded_for` always removes those before setting the
list that Opey built.
"""

import ipaddress
from dataclasses import dataclass
from typing import Any, Mapping, Optional

FORWARDED_FOR_HEADER = "X-Forwarded-For"

# Headers that name a client address. A tool call must never carry any of these except the
# X-Forwarded-For value Opey sets itself.
_CLIENT_ADDRESS_HEADERS = {"x-forwarded-for", "x-real-ip", "forwarded"}


def canonical_address(address: str) -> str:
    """
    Return an address in the form the whole chain agrees on.

    IPv6 addresses lose any surrounding brackets and are written in their shortest form, and
    IPv4 addresses reported in IPv6-mapped form (::ffff:203.0.113.7) are written as plain
    IPv4. A value that is not an address (a test client's host name, for example) is
    returned trimmed but otherwise unchanged.
    """
    unbracketed = address.strip().removeprefix("[").removesuffix("]")
    try:
        parsed = ipaddress.ip_address(unbracketed)
    except ValueError:
        return unbracketed
    if isinstance(parsed, ipaddress.IPv6Address) and parsed.ipv4_mapped is not None:
        return str(parsed.ipv4_mapped)
    return str(parsed)


def forwarded_for_chain(request: Any) -> Optional[str]:
    """
    Build the X-Forwarded-For list to pass on for an incoming request.

    The result is the X-Forwarded-For list the caller sent, if any, followed by the address
    of the peer that sent this request, for example "203.0.113.7, 10.0.0.5". When the caller
    sent no list it is just the peer's address. When the peer's address is unknown there is
    nothing trustworthy to add, so the result is None and no header is passed on.
    """
    client = getattr(request, "client", None)
    if client is None or not getattr(client, "host", None):
        return None
    peer_address = canonical_address(client.host)

    received_values = [value.strip() for value in request.headers.getlist(FORWARDED_FOR_HEADER)]
    received_chain = ", ".join(value for value in received_values if value)
    return f"{received_chain}, {peer_address}" if received_chain else peer_address


def with_forwarded_for(tool_args: Mapping[str, Any], chain: Optional[str]) -> dict:
    """
    Return a copy of a tool call's arguments carrying Opey's X-Forwarded-For list.

    Any client address header already in the arguments' "headers" (X-Forwarded-For,
    X-Real-IP or Forwarded, in any letter case) is removed, because the model wrote it.
    Then, when a list is known, X-Forwarded-For is set to it. The arguments passed in are
    never changed, so the tool call saved in the conversation keeps its original form and
    the user's address never reaches the model or the saved conversation.
    """
    existing_headers = tool_args.get("headers") or {}
    headers = {
        name: value
        for name, value in existing_headers.items()
        if name.lower() not in _CLIENT_ADDRESS_HEADERS
    }
    if chain is not None:
        headers[FORWARDED_FOR_HEADER] = chain

    rewritten = dict(tool_args)
    if headers or "headers" in tool_args:
        rewritten["headers"] = headers
    return rewritten


def tool_accepts_headers(tool: Any) -> bool:
    """
    Tell whether a tool takes a "headers" argument that it forwards as HTTP headers.

    Only such tools (OBP-MCP's call_obp_api today) have their arguments rewritten; other
    tools never see the user's address.
    """
    if tool is None:
        return False
    try:
        arguments = tool.args
    except Exception:
        return False
    return isinstance(arguments, Mapping) and "headers" in arguments


@dataclass(frozen=True)
class ForwardedFor:
    """
    This class holds an X-Forwarded-For list inside a graph run's configuration.

    The list is wrapped rather than stored as a plain string because LangGraph copies every
    plain string, number or boolean in the configuration into the metadata of each saved
    checkpoint, and LangChain copies them into tracing metadata. Wrapped, the user's address
    stays in memory for the run only.
    """

    chain: str

    def __repr__(self) -> str:
        return "ForwardedFor(<hidden>)"


def forwarded_for_config(request: Any) -> Optional[ForwardedFor]:
    """Build the value a chat route stores under "forwarded_for" in a run's configuration."""
    chain = forwarded_for_chain(request)
    return ForwardedFor(chain) if chain is not None else None


def forwarded_for_from_config(config: Optional[Mapping[str, Any]]) -> Optional[str]:
    """Read the X-Forwarded-For list a chat route stored in a graph run's configuration."""
    if not config:
        return None
    stored = (config.get("configurable") or {}).get("forwarded_for")
    return stored.chain if isinstance(stored, ForwardedFor) else None
