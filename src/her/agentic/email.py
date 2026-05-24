"""Email tools — read and send via macOS Mail.app.

Mirrors the Calendar integration: Mail.app already syncs Gmail / iCloud /
Exchange when the account is set up in System Settings → Internet
Accounts, so we get multi-account email access without any OAuth flow.

Backend: AppleScript via ``osascript``. Mail.app must be installed (ships
with macOS). The first call surfaces an Automation permission prompt for
Mail and System Events; the grant is per parent process, same as the
other macOS tools.

Performance notes
-----------------
Mail.app's ``messages of inbox whose read status is false`` is **very
slow** on large mailboxes — the unified ``inbox`` is a virtual
cross-account view and the ``whose`` clause forces Mail to materialize
every reference before filtering. On a Gmail account with thousands of
messages we measured 45+ seconds for a single call.

The implementation below works around that with three guard-rails:

1. **Per-account iteration.** We walk ``every account`` and query each
   account's own inbox mailbox. One slow account no longer blocks the
   others; one bad account is caught and skipped.
2. **Explicit slicing + in-loop filter.** Instead of ``whose read status``
   we fetch ``messages 1 thru N`` (most recent first, Mail.app's default
   sort) and check ``read status`` per message. ``N`` is bounded by
   ``_SCAN_PER_ACCOUNT`` so a huge mailbox can't stall the script.
3. **Generous Python timeout + AppleScript ``with timeout`` block.** The
   Python-side guard (120 s for reads) is the hard ceiling; the
   AppleScript-side ``with timeout`` gives a quicker, structured error
   when the Mail bridge specifically hangs.

``email_search`` likewise fetches a bounded slice per account and does
the case-insensitive substring match in Python, instead of the previous
per-message ``do shell script "echo … | tr"`` (which spawned one
subprocess per message — disaster on big mailboxes).
"""
from __future__ import annotations

import asyncio
import logging
import sys

from .registry import tool

log = logging.getLogger(__name__)

# Hard timeouts for the underlying osascript invocation.
_READ_TIMEOUT = 120.0          # list / search — first call may sync IMAP headers
_SEND_TIMEOUT = 45.0           # send — no sync needed

# AppleScript-level timeout (per Mail event). Slightly under the Python
# ceiling so we get an AppleScript error instead of a SIGKILL.
_APPLESCRIPT_TIMEOUT_S = 90

# How many of the most recent messages to scan per account when listing
# unread or searching. Bounds the work Mail.app has to do per call.
_SCAN_PER_ACCOUNT = 200

_SNIPPET_MAX = 240


class MailError(RuntimeError):
    """Raised when Mail.app / AppleScript can't satisfy a request."""


async def _osascript(script: str, timeout: float = _READ_TIMEOUT) -> str:
    """Run an AppleScript snippet and return its stdout (decoded)."""
    if sys.platform != "darwin":
        raise MailError("email tools require macOS (Mail.app + osascript)")
    proc = await asyncio.create_subprocess_exec(
        "osascript", "-e", script,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        # Drain the killed child so we don't leak a zombie. Best-effort.
        try:
            await asyncio.wait_for(proc.wait(), timeout=2.0)
        except asyncio.TimeoutError:
            pass
        raise MailError(
            f"Mail.app script timed out after {timeout:.0f}s — "
            "the mailbox may be large or Mail.app may be syncing. "
            "Try again in a moment, or narrow the request (smaller "
            "max_results, account_filter)."
        )
    if (proc.returncode or 0) != 0:
        err = stderr.decode(errors="replace").strip()
        # AppleScript surfaces a hung Mail.app as "AppleEvent timed out (-1712)".
        # That's a *different* failure from "mailbox too large": it almost
        # always means Mail itself is unresponsive (beachballing, lost IMAP
        # connection, stuck dialog). Tell the user what to do.
        if "-1712" in err or "AppleEvent timed out" in err:
            raise MailError(
                "Mail.app did not respond (AppleScript timeout). It is "
                "likely frozen or stuck syncing — try quitting and "
                "reopening Mail.app, then retry."
            )
        raise MailError(err or "Mail.app script failed")
    return stdout.decode(errors="replace")


def _escape_applescript(s: str) -> str:
    """Escape a Python string for safe interpolation into AppleScript ``"..."``."""
    return s.replace("\\", "\\\\").replace('"', '\\"')


# AppleScript helper that strips tabs / newlines from a field so the
# downstream tab-separated parser is unambiguous. Reused by every read op.
_CLEAN_FIELD_HANDLER = r"""
on cleanField(s)
    try
        set txt to (s as text)
    on error
        return ""
    end try
    set AppleScript's text item delimiters to {tab, return, linefeed}
    set parts to text items of txt
    set AppleScript's text item delimiters to " "
    set txt to parts as text
    set AppleScript's text item delimiters to ""
    return txt
end cleanField

on findInbox(acct)
    -- The Mail-specific `mailbox` / `mailboxes` keywords only resolve
    -- inside a `tell application "Mail"` block, so we wrap the body.
    tell application "Mail"
        try
            return mailbox "INBOX" of acct
        end try
        try
            repeat with bx in (mailboxes of acct)
                set bxName to (name of bx) as text
                ignoring case
                    if bxName contains "inbox" then return bx
                end ignoring
            end repeat
        end try
    end tell
    return missing value
end findInbox
"""


def _parse_tsv(raw: str, field_count: int) -> list[list[str]]:
    """Split AppleScript output into rows of ``field_count`` fields each."""
    rows: list[list[str]] = []
    for line in raw.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) < field_count:
            parts.extend([""] * (field_count - len(parts)))
        else:
            parts = parts[:field_count]
        rows.append(parts)
    return rows


def _truncate(text: str, limit: int) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "…"


def _split_addresses(raw: str) -> list[str]:
    """Split a comma- or semicolon-separated address string and trim each entry."""
    if not raw:
        return []
    cleaned: list[str] = []
    for piece in raw.replace(";", ",").split(","):
        addr = piece.strip()
        if addr:
            cleaned.append(addr)
    return cleaned


@tool(params={"max_results": {"minimum": 1, "maximum": 50}})
async def email_list_unread(
    max_results: int = 10,
    account_filter: str = "",
) -> list[dict]:
    """List the user's unread emails from macOS Mail.app, iterating per
    account so one slow IMAP server can't block the whole call. Reflects
    every account set up in System Settings → Internet Accounts: Google,
    iCloud, Exchange, … Use this when the user asks 'what new email do I
    have?', 'check my inbox', 'do I have any unread messages?'. Returns a
    JSON array of {subject, sender, date, account}. Body content is NOT
    included — for that, use `email_search` (which returns a short
    snippet) or open Mail.app.

    Args:
        max_results: Cap on total results across all accounts (default 10, max 50).
        account_filter: Optional substring matched against the account name
            (e.g. 'Google', 'iCloud') to restrict which accounts are queried.
    """
    cap = max(1, min(50, int(max_results)))
    needle_acct_esc = _escape_applescript((account_filter or "").lower().strip())
    script = _CLEAN_FIELD_HANDLER + f"""
    with timeout of {_APPLESCRIPT_TIMEOUT_S} seconds
        tell application "Mail"
            if not running then
                launch
                delay 1
            end if
            set output to ""
            set hits to 0
            set acctFilter to "{needle_acct_esc}"
            try
                set acctList to every account
            on error
                return ""
            end try
            repeat with acct in acctList
                if hits >= {cap} then exit repeat
                set acctName to my cleanField(name of acct)
                set skipAccount to false
                if acctFilter is not "" then
                    ignoring case
                        if acctName does not contain acctFilter then set skipAccount to true
                    end ignoring
                end if
                if not skipAccount then
                    set inboxBox to my findInbox(acct)
                    if inboxBox is not missing value then
                        try
                            set msgRefs to messages of inboxBox
                            set total to count of msgRefs
                            set scan to {_SCAN_PER_ACCOUNT}
                            if scan > total then set scan to total
                            repeat with i from 1 to scan
                                if hits >= {cap} then exit repeat
                                try
                                    set msg to item i of msgRefs
                                    if (read status of msg) is false then
                                        set subj to my cleanField(subject of msg)
                                        set sndr to my cleanField(sender of msg)
                                        set dateStr to my cleanField((date received of msg) as text)
                                        set output to output & subj & tab & sndr & tab & dateStr & tab & acctName & linefeed
                                        set hits to hits + 1
                                    end if
                                on error
                                    -- skip unreadable individual message
                                end try
                            end repeat
                        on error
                            -- skip account whose inbox can't be enumerated
                        end try
                    end if
                end if
            end repeat
            return output
        end tell
    end timeout
    """
    raw = await _osascript(script, timeout=_READ_TIMEOUT)
    results: list[dict] = []
    for subject, sender, date, account in _parse_tsv(raw, 4):
        results.append({
            "subject": subject,
            "sender": sender,
            "date": date,
            "account": account,
        })
    return results


@tool(
    params={
        "max_results": {"minimum": 1, "maximum": 50},
        "days_back": {"minimum": 1, "maximum": 365},
    },
)
async def email_search(
    query: str,
    max_results: int = 10,
    days_back: int = 30,
    account_filter: str = "",
) -> list[dict]:
    """Search the user's Mail.app inbox for messages whose subject, sender,
    or body content contains the given text, within the last `days_back`
    days. Iterates per account (one slow IMAP server can't stall the
    whole call) and fetches a bounded slice per account; the actual
    case-insensitive match runs in Python so we avoid a subprocess per
    message. Use this for 'find the email from Anna', 'did Marco send me
    anything about the meeting?', 'cerca la mail della banca'. Returns a
    JSON array of {subject, sender, date, account, snippet}.

    Args:
        query: Text to search for (subject + sender + body, case-insensitive).
        max_results: Cap on results (default 10, max 50).
        days_back: How many days back to consider (default 30, max 365).
        account_filter: Optional substring matched against account name.
    """
    needle = (query or "").strip()
    if not needle:
        raise MailError("query is empty")

    cap = max(1, min(50, int(max_results)))
    days = max(1, min(365, int(days_back)))
    needle_acct_esc = _escape_applescript((account_filter or "").lower().strip())
    # We pass the cutoff date directly into the AppleScript so messages
    # older than `days_back` are skipped without their bodies being read.

    # We ask AppleScript for the most recent _SCAN_PER_ACCOUNT messages of
    # each account's inbox along with subject/sender/date/account/body
    # (body capped to ~800 chars in-script to keep stdout small). Python
    # then does the date-cutoff and the case-insensitive substring match.
    script = _CLEAN_FIELD_HANDLER + f"""
    with timeout of {_APPLESCRIPT_TIMEOUT_S} seconds
        tell application "Mail"
            if not running then
                launch
                delay 1
            end if
            set output to ""
            set acctFilter to "{needle_acct_esc}"
            set cutoff to (current date) - ({days} * days)
            try
                set acctList to every account
            on error
                return ""
            end try
            repeat with acct in acctList
                set acctName to my cleanField(name of acct)
                set skipAccount to false
                if acctFilter is not "" then
                    ignoring case
                        if acctName does not contain acctFilter then set skipAccount to true
                    end ignoring
                end if
                if not skipAccount then
                    set inboxBox to my findInbox(acct)
                    if inboxBox is not missing value then
                        try
                            set msgRefs to messages of inboxBox
                            set total to count of msgRefs
                            set scan to {_SCAN_PER_ACCOUNT}
                            if scan > total then set scan to total
                            repeat with i from 1 to scan
                                try
                                    set msg to item i of msgRefs
                                    set msgDate to date received of msg
                                    if msgDate < cutoff then exit repeat
                                    set subj to my cleanField(subject of msg)
                                    set sndr to my cleanField(sender of msg)
                                    set dateStr to my cleanField(msgDate as text)
                                    set bodyText to ""
                                    try
                                        set rawBody to (content of msg) as text
                                        if (length of rawBody) > 800 then
                                            set bodyText to text 1 thru 800 of rawBody
                                        else
                                            set bodyText to rawBody
                                        end if
                                    end try
                                    set bodyText to my cleanField(bodyText)
                                    set output to output & subj & tab & sndr & tab & dateStr & tab & acctName & tab & bodyText & linefeed
                                on error
                                    -- skip unreadable message
                                end try
                            end repeat
                        on error
                            -- skip enumeration error
                        end try
                    end if
                end if
            end repeat
            return output
        end tell
    end timeout
    """
    raw = await _osascript(script, timeout=_READ_TIMEOUT)
    needle_lc = needle.lower()
    results: list[dict] = []
    for subject, sender, date, account, body in _parse_tsv(raw, 5):
        hay = f"{subject}\n{sender}\n{body}".lower()
        if needle_lc not in hay:
            continue
        results.append({
            "subject": subject,
            "sender": sender,
            "date": date,
            "account": account,
            "snippet": _truncate(body, _SNIPPET_MAX),
        })
        if len(results) >= cap:
            break
    return results


@tool(safe=False)
async def email_send(
    to: str,
    subject: str,
    body: str,
    cc: str = "",
    send: bool = True,
) -> dict:
    """Compose (and by default send) a new email via macOS Mail.app from the
    user's default account. ALWAYS read the recipients, subject, and body
    back to the user verbally and ask for explicit confirmation BEFORE
    calling — outgoing email is irreversible. To leave the message as an
    open draft so the user can review or edit it in Mail.app, pass
    `send=false`. Returns {"sent": bool, "to": [...], "subject": "..."}.

    Args:
        to: Recipient address(es). Multiple are accepted as a comma- or
            semicolon-separated list, e.g. 'alice@x.com, bob@y.com'.
        subject: Subject line.
        body: Plain-text body. Newlines are preserved.
        cc: Optional CC address(es), same format as `to`.
        send: True to send immediately (default). False to open the compose
            window as a draft for the user to review and send manually.
    """
    to_list = _split_addresses(to)
    cc_list = _split_addresses(cc)
    if not to_list:
        raise MailError("at least one recipient (`to`) is required")
    if not subject:
        raise MailError("`subject` is required")

    subj_esc = _escape_applescript(subject)
    body_esc = _escape_applescript(body or "")
    visible = "false" if send else "true"

    recipient_lines: list[str] = []
    for addr in to_list:
        addr_esc = _escape_applescript(addr)
        recipient_lines.append(
            f'    make new to recipient at end of to recipients with properties {{address:"{addr_esc}"}}'
        )
    for addr in cc_list:
        addr_esc = _escape_applescript(addr)
        recipient_lines.append(
            f'    make new cc recipient at end of cc recipients with properties {{address:"{addr_esc}"}}'
        )
    recipients_block = "\n".join(recipient_lines)

    send_line = "    send" if send else ""

    script = f"""
    with timeout of {_APPLESCRIPT_TIMEOUT_S} seconds
        tell application "Mail"
            if not running then
                launch
                delay 1
            end if
            set newMsg to make new outgoing message with properties {{subject:"{subj_esc}", content:"{body_esc}", visible:{visible}}}
            tell newMsg
{recipients_block}
{send_line}
            end tell
        end tell
    end timeout
    """
    await _osascript(script, timeout=_SEND_TIMEOUT)
    return {
        "sent": bool(send),
        "to": to_list,
        "cc": cc_list,
        "subject": subject,
    }
