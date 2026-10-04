#!/usr/bin/env python3
"""A tamper-evident record of trades and research.

Every entry in ledger/chain.jsonl carries the SHA-256 hash of the entry before
it, so changing or deleting any past entry breaks every hash after it. Each day
the latest hash is written to a small file in ledger/stamps and timestamped
with OpenTimestamps, which records it in the Bitcoin blockchain. Anyone can
later check that the ledger existed in that exact form on that date.

run.sh calls these commands.
  ledger.py setup TOKEN QUERY_ID      save the IBKR Flex Web Service token and query ID
  ledger.py sync                      download trades from IBKR, add new ones, stamp
  ledger.py add FILE [NOTE]           fingerprint a file (a statement, a report) and stamp
  ledger.py research FILE             fingerprint a research file, quietly, without stamping
  ledger.py stamp [--force]           timestamp the latest state (once a day unless forced)
  ledger.py verify                    check the chain, the stored files and the timestamps
  ledger.py pnl                       work out realized and unrealized P&L from the ledger
"""
import datetime
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

KIT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LEDGER = os.path.join(KIT, "ledger")
CHAIN = os.path.join(LEDGER, "chain.jsonl")
FILES = os.path.join(LEDGER, "files")
STAMPS = os.path.join(LEDGER, "stamps")
SETTINGS = os.path.join(KIT, "settings.env")
GENESIS = "0" * 64
FLEX_SEND = "https://ndcdyn.interactivebrokers.com/AccountManagement/FlexWebService/SendRequest"
FLEX_GET = "https://gdcdyn.interactivebrokers.com/AccountManagement/FlexWebService/GetStatement"
MOCK_FLEX = os.environ.get("LEDGER_MOCK_FLEX")  # tests only: path to a Flex XML file


def say(msg):
    print("  " + msg, flush=True)


def now_utc():
    return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat()


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def entry_hash(entry):
    body = dict((k, v) for k, v in entry.items() if k != "hash")
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=False).encode("utf-8")).hexdigest()


def read_chain():
    if not os.path.exists(CHAIN):
        return []
    out = []
    with open(CHAIN, encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                out.append(json.loads(line))
    return out


def append(kind, data, chain=None):
    """Add one entry to the end of the chain and return it."""
    os.makedirs(LEDGER, exist_ok=True)
    chain = chain if chain is not None else read_chain()
    prev = chain[-1]["hash"] if chain else GENESIS
    entry = {"seq": len(chain) + 1, "time": now_utc(), "kind": kind, "data": data, "prev": prev}
    entry["hash"] = entry_hash(entry)
    with open(CHAIN, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, sort_keys=True, ensure_ascii=False) + "\n")
        fh.flush()
        os.fsync(fh.fileno())
    chain.append(entry)
    return entry


def store_file(path):
    """Copy a file into ledger/files under its hash, and return (hash, stored name)."""
    os.makedirs(FILES, exist_ok=True)
    digest = sha256_file(path)
    base = re.sub(r"[^A-Za-z0-9._-]+", "_", os.path.basename(path))[-80:]
    name = "%s_%s" % (digest[:16], base)
    dest = os.path.join(FILES, name)
    if not os.path.exists(dest):
        shutil.copyfile(path, dest)
    return digest, name


def already_fingerprinted(chain, digest):
    return any(e["kind"] in ("file", "research") and e["data"].get("sha256") == digest for e in chain)


# ---------------------------------------------------------------------------
# IBKR Flex

def read_settings():
    vals = {}
    if os.path.exists(SETTINGS):
        for line in open(SETTINGS, encoding="utf-8"):
            m = re.match(r'^\s*([A-Z_]+)="?(.*?)"?\s*$', line)
            if m:
                vals[m.group(1)] = m.group(2)
    vals.update(dict((k, v) for k, v in os.environ.items() if k.startswith("IBKR_FLEX_")))
    return vals


def write_setting(key, value):
    lines = []
    if os.path.exists(SETTINGS):
        lines = [ln for ln in open(SETTINGS, encoding="utf-8").read().splitlines()
                 if not ln.startswith(key + "=")]
    clean = re.sub(r'["\\$`\s]', "", value)
    lines.append('%s="%s"' % (key, clean))
    with open(SETTINGS, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    os.chmod(SETTINGS, 0o600)


def http_get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "special-sits-kit/1.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


def flex_download(token, query):
    if MOCK_FLEX:
        return open(MOCK_FLEX, "rb").read()
    q = urllib.parse.urlencode({"t": token, "q": query, "v": "3"})
    root = ET.fromstring(http_get(FLEX_SEND + "?" + q))
    status = (root.findtext("Status") or "").strip()
    if status != "Success":
        raise RuntimeError("IBKR refused the request (%s %s). Check the token and query ID, and that the "
                           "Flex Web Service is enabled." % (root.findtext("ErrorCode") or "",
                                                            (root.findtext("ErrorMessage") or "").strip()))
    ref = (root.findtext("ReferenceCode") or "").strip()
    get_url = (root.findtext("Url") or "").strip() or FLEX_GET
    wait = 5
    for _ in range(12):
        time.sleep(wait)
        body = http_get(get_url + "?" + urllib.parse.urlencode({"t": token, "q": ref, "v": "3"}))
        head = body[:400].decode("utf-8", "replace")
        if "<FlexQueryResponse" in head:
            return body
        r = ET.fromstring(body)
        code = (r.findtext("ErrorCode") or "").strip()
        if code in ("1019", "1018", "1009", "1004", "1021"):
            wait = min(wait * 2, 60)
            continue
        raise RuntimeError("IBKR could not produce the report (%s %s)." % (code, (r.findtext("ErrorMessage") or "").strip()))
    raise RuntimeError("IBKR was still preparing the report after several minutes. Try again later.")


def num(v, default=0.0):
    try:
        return float(str(v).replace(",", ""))
    except (TypeError, ValueError):
        return default


TRADE_KEYS = ("accountId", "currency", "fxRateToBase", "assetCategory", "symbol", "description", "conid",
              "multiplier", "tradeID", "ibExecID", "transactionID", "tradeDate", "dateTime", "buySell",
              "quantity", "tradePrice", "ibCommission", "ibCommissionCurrency", "netCash", "fifoPnlRealized",
              "openCloseIndicator", "orderType", "exchange")
POSITION_KEYS = ("accountId", "currency", "fxRateToBase", "assetCategory", "symbol", "description", "conid",
                 "multiplier", "position", "markPrice", "positionValue", "costBasisPrice", "costBasisMoney",
                 "fifoPnlUnrealized", "reportDate")


def parse_flex(xml_bytes):
    root = ET.fromstring(xml_bytes)
    trades, positions, meta = [], [], {}
    for st in root.iter("FlexStatement"):
        meta = {"accountId": st.get("accountId"), "fromDate": st.get("fromDate"),
                "toDate": st.get("toDate"), "whenGenerated": st.get("whenGenerated")}
    for tag in ("Trade", "TradeConfirm"):
        for el in root.iter(tag):
            level = (el.get("levelOfDetail") or "EXECUTION").upper()
            if level not in ("EXECUTION", ""):
                continue
            t = dict((k, el.get(k)) for k in TRADE_KEYS if el.get(k) not in (None, ""))
            if not t.get("symbol") or not t.get("quantity"):
                continue
            q = num(t["quantity"])
            if (t.get("buySell") or "").upper().startswith("SELL") and q > 0:
                t["quantity"] = repr(-q)
            t["id"] = t.get("tradeID") or t.get("ibExecID") or t.get("transactionID") or hashlib.sha256(
                json.dumps(t, sort_keys=True).encode()).hexdigest()[:24]
            trades.append(t)
    for el in root.iter("OpenPosition"):
        level = (el.get("levelOfDetail") or "SUMMARY").upper()
        if level not in ("SUMMARY", ""):
            continue
        p = dict((k, el.get(k)) for k in POSITION_KEYS if el.get(k) not in (None, ""))
        if p.get("symbol"):
            positions.append(p)
    return trades, positions, meta


# ---------------------------------------------------------------------------
# Timestamps

def have_ots():
    return shutil.which("ots") is not None


def stamp(force=False, quiet=False):
    chain = read_chain()
    if not chain:
        if not quiet:
            say("the ledger is empty, so there is nothing to stamp yet")
        return
    os.makedirs(STAMPS, exist_ok=True)
    today = datetime.date.today().strftime("%Y%m%d")
    head = chain[-1]
    existing = sorted(f for f in os.listdir(STAMPS) if f.endswith(".txt"))
    if existing and not force:
        last_path = os.path.join(STAMPS, existing[-1])
        last = open(last_path, encoding="utf-8").read()
        if ("hash " + head["hash"]) in last:
            upgrade(quiet=True)
            if not quiet:
                say("already stamped at entry %d, nothing new since" % head["seq"])
            return
        gap = float(os.environ.get("LEDGER_MIN_STAMP_MINUTES", "10")) * 60
        if time.time() - os.path.getmtime(last_path) < gap:
            if not quiet:
                say("stamped a few minutes ago, so the next stamp will cover the new entries")
            return
    name = "head-%s-%s.txt" % (today, datetime.datetime.now().strftime("%H%M%S"))
    path = os.path.join(STAMPS, name)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("Special situations ledger\nentries %d\nhash %s\nrecorded %s\n" % (
            head["seq"], head["hash"], now_utc()))
    if sign_head(path) and not quiet:
        say("signed %s with your ledger key" % name)
    if have_ots():
        r = subprocess.run(["ots", "stamp", path], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                           universal_newlines=True)
        if r.returncode == 0 and os.path.exists(path + ".ots"):
            if not quiet:
                say("stamped entry %d with OpenTimestamps. The proof completes in a few hours." % head["seq"])
        elif not quiet:
            say("wrote %s but OpenTimestamps did not respond. Run ./run.sh ledger stamp later." % name)
    elif not quiet:
        say("wrote %s. Install the OpenTimestamps client to anchor it in Bitcoin (see docs/manual.md)." % name)
    upgrade(quiet=True)


SIGN_KEY = os.path.expanduser(os.environ.get("LEDGER_SIGNING_KEY") or "~/.ssh/special_sits_ledger_ed25519")
ALLOWED = os.path.join(LEDGER, "allowed_signers")
NAMESPACE = "special-sits-ledger"


def sign_head(path):
    """Sign a stamped head with your SSH key, so the record provably comes from you."""
    if not (os.path.exists(SIGN_KEY) and shutil.which("ssh-keygen")):
        return False
    r = subprocess.run(["ssh-keygen", "-Y", "sign", "-f", SIGN_KEY, "-n", NAMESPACE, path],
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True)
    return r.returncode == 0 and os.path.exists(path + ".sig")


def signer_identity():
    if not os.path.exists(ALLOWED):
        return None
    first = open(ALLOWED, encoding="utf-8").read().split()
    return first[0] if first else None


def check_signature(path):
    ident = signer_identity()
    if not ident or not os.path.exists(path + ".sig") or not shutil.which("ssh-keygen"):
        return None
    with open(path, "rb") as fh:
        r = subprocess.run(["ssh-keygen", "-Y", "verify", "-f", ALLOWED, "-I", ident, "-n", NAMESPACE, "-s", path + ".sig"],
                           stdin=fh, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    return r.returncode == 0


def cmd_keygen(identity):
    os.makedirs(os.path.dirname(SIGN_KEY), exist_ok=True)
    if not shutil.which("ssh-keygen"):
        sys.exit("ssh-keygen isn't installed. In Ubuntu, run: sudo apt install openssh-client")
    if not os.path.exists(SIGN_KEY):
        subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", identity, "-f", SIGN_KEY], check=True)
        say("made a signing key at %s. Keep a backup of it somewhere safe and private" % SIGN_KEY)
    else:
        say("using your existing signing key at %s" % SIGN_KEY)
    pub = open(SIGN_KEY + ".pub", encoding="utf-8").read().strip()
    principal = re.sub(r"[^A-Za-z0-9@._-]+", "-", identity).strip("-").lower() or "investor"
    os.makedirs(LEDGER, exist_ok=True)
    with open(ALLOWED, "w", encoding="utf-8") as fh:
        fh.write('%s namespaces="%s" %s\n' % (principal, NAMESPACE, pub))
    fp = subprocess.run(["ssh-keygen", "-lf", SIGN_KEY + ".pub"], stdout=subprocess.PIPE, universal_newlines=True).stdout.strip()
    say("the public half is in ledger/allowed_signers, so anyone can check your signatures")
    say("your key's fingerprint is %s" % fp)
    say("send that fingerprint to yourself by email now, so there is an independent, dated record of which key is yours")


def upgrade(quiet=False):
    if not have_ots() or not os.path.isdir(STAMPS):
        return
    for f in sorted(os.listdir(STAMPS)):
        if f.endswith(".ots"):
            subprocess.run(["ots", "upgrade", os.path.join(STAMPS, f)], stdout=subprocess.PIPE,
                           stderr=subprocess.STDOUT, universal_newlines=True)
    for f in os.listdir(STAMPS):
        if f.endswith(".ots.bak"):
            os.remove(os.path.join(STAMPS, f))


def stamp_status(path):
    """Complete, pending, or missing, for one head file."""
    ots = path + ".ots"
    if not os.path.exists(ots):
        return "no proof"
    if not have_ots():
        return "proof saved"
    r = subprocess.run(["ots", "info", ots], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True)
    return "complete" if "BitcoinBlockHeaderAttestation" in r.stdout else "pending"


# ---------------------------------------------------------------------------
# Commands

def cmd_setup(token, query):
    write_setting("IBKR_FLEX_TOKEN", token)
    write_setting("IBKR_FLEX_QUERY", query)
    say("saved the Flex token and query ID in settings.env (readable only by you)")


def import_flex(xml_bytes, source_name, chain):
    trades, positions, meta = parse_flex(xml_bytes)
    known = set(e["data"].get("id") for e in chain if e["kind"] == "trade")
    new = [t for t in trades if t["id"] not in known]
    new.sort(key=lambda t: (t.get("dateTime") or t.get("tradeDate") or "", t["id"]))
    for t in new:
        t["source"] = source_name
        append("trade", t, chain)
    if positions:
        append("positions", {"account": meta.get("accountId"), "asOf": meta.get("toDate") or meta.get("whenGenerated"),
                             "positions": positions, "source": source_name}, chain)
    return len(new), len(trades), len(positions)


def cmd_sync():
    s = read_settings()
    token, query = s.get("IBKR_FLEX_TOKEN"), s.get("IBKR_FLEX_QUERY")
    if not (token and query) and not MOCK_FLEX:
        sys.exit("Set up the IBKR connection first with ./run.sh ledger setup TOKEN QUERY_ID (see docs/manual.md).")
    say("asking IBKR for the latest trades")
    xml_bytes = flex_download(token, query)
    os.makedirs(FILES, exist_ok=True)
    tmp = os.path.join(LEDGER, "flex-%s.xml" % datetime.datetime.now().strftime("%Y%m%d-%H%M%S"))
    with open(tmp, "wb") as fh:
        fh.write(xml_bytes)
    chain = read_chain()
    digest, name = store_file(tmp)
    os.remove(tmp)
    if not already_fingerprinted(chain, digest):
        append("file", {"sha256": digest, "stored": name, "note": "IBKR Flex report"}, chain)
    added, seen, npos = import_flex(xml_bytes, name, chain)
    say("%d new trade%s recorded (%d in the report), %d open position%s" % (
        added, "" if added == 1 else "s", seen, npos, "" if npos == 1 else "s"))
    stamp()


def cmd_add(path, note="", kind="file", quiet=False):
    if not os.path.isfile(path):
        sys.exit("No file at %s" % path)
    chain = read_chain()
    digest, name = store_file(path)
    if already_fingerprinted(chain, digest):
        if not quiet:
            say("this exact file is already in the ledger")
        return
    data = {"sha256": digest, "stored": name, "original": os.path.relpath(os.path.abspath(path), KIT), "note": note}
    append(kind, data, chain)
    if path.lower().endswith(".xml"):
        try:
            added, seen, npos = import_flex(open(path, "rb").read(), name, chain)
            say("imported %d new trade%s from the Flex file" % (added, "" if added == 1 else "s"))
        except ET.ParseError:
            pass
    if not quiet:
        say("fingerprinted %s" % os.path.basename(path))
        stamp()


def cmd_verify():
    chain = read_chain()
    if not chain:
        say("the ledger is empty")
        return 0
    problems = 0
    prev = GENESIS
    for i, e in enumerate(chain, 1):
        if e.get("seq") != i or e.get("prev") != prev or entry_hash(e) != e.get("hash"):
            say("entry %d does not match the chain. The ledger was changed after it was written." % i)
            problems += 1
        prev = e.get("hash")
    for e in chain:
        if e["kind"] in ("file", "research"):
            p = os.path.join(FILES, e["data"]["stored"])
            if not os.path.exists(p):
                say("stored file %s is missing" % e["data"]["stored"])
                problems += 1
            elif sha256_file(p) != e["data"]["sha256"]:
                say("stored file %s was changed" % e["data"]["stored"])
                problems += 1
    by_hash = dict((e["hash"], e["seq"]) for e in chain)
    heads = sorted(f for f in os.listdir(STAMPS) if f.endswith(".txt")) if os.path.isdir(STAMPS) else []
    upgrade(quiet=True)
    complete = pending = signed_ok = 0
    for f in heads:
        text = open(os.path.join(STAMPS, f), encoding="utf-8").read()
        m = re.search(r"hash ([0-9a-f]{64})", text)
        if not m or m.group(1) not in by_hash:
            say("%s points to a state that is not in the current chain" % f)
            problems += 1
            continue
        st = stamp_status(os.path.join(STAMPS, f))
        complete += st == "complete"
        pending += st == "pending"
        sig = check_signature(os.path.join(STAMPS, f))
        if sig is True:
            signed_ok += 1
        elif sig is False:
            say("the signature on %s does not match. The stamp or the key was changed" % f)
            problems += 1
    say("%d entries checked, %d problem%s" % (len(chain), problems, "" if problems == 1 else "s"))
    say("%d timestamp%s, %d complete in Bitcoin, %d still pending" % (
        len(heads), "" if len(heads) == 1 else "s", complete, pending))
    if signer_identity():
        say("%d stamp%s signed with your key and checked" % (signed_ok, "" if signed_ok == 1 else "s"))
    if heads:
        say("anyone can check a stamp by dropping %s and its .ots file into opentimestamps.org" % heads[-1])
    return 1 if problems else 0


def fifo_pnl(trades):
    """Realized P&L per trade by FIFO, used when IBKR does not report fifoPnlRealized."""
    lots, out = {}, {}
    for t in trades:
        key = t.get("conid") or t["symbol"]
        mult = num(t.get("multiplier"), 1.0) or 1.0
        qty = num(t.get("quantity"))
        price = num(t.get("tradePrice"))
        comm = num(t.get("ibCommission"))
        book = lots.setdefault(key, [])
        realized, remaining = comm, qty
        while remaining and book and (book[0][0] > 0) != (remaining > 0):
            lot_qty, lot_price = book[0]
            take = min(abs(remaining), abs(lot_qty)) * (1 if remaining > 0 else -1)
            realized += (lot_price - price) * take * mult
            book[0][0] += take
            remaining -= take
            if abs(book[0][0]) < 1e-9:
                book.pop(0)
        if abs(remaining) > 1e-9:
            book.append([remaining, price])
        out[t["id"]] = realized if abs(remaining - qty) > 1e-9 else comm
    return out


def cmd_pnl():
    chain = read_chain()
    trades = [e["data"] for e in chain if e["kind"] == "trade"]
    snaps = [e["data"] for e in chain if e["kind"] == "positions"]
    if not trades and not snaps:
        say("no trades in the ledger yet")
        return
    trades.sort(key=lambda t: (t.get("dateTime") or t.get("tradeDate") or "", t["id"]))
    computed = fifo_pnl(trades)
    by_month, by_symbol, comm = {}, {}, {}
    for t in trades:
        cur = t.get("currency") or "?"
        pnl = num(t["fifoPnlRealized"]) if "fifoPnlRealized" in t else computed.get(t["id"], 0.0)
        month = (t.get("tradeDate") or t.get("dateTime") or "")[:6]
        month = "%s-%s" % (month[:4], month[4:6]) if month.isdigit() else (t.get("tradeDate") or "")[:7]
        by_month.setdefault((month, cur), 0.0)
        by_month[(month, cur)] += pnl
        by_symbol.setdefault((t["symbol"], cur), 0.0)
        by_symbol[(t["symbol"], cur)] += pnl
        comm[cur] = comm.get(cur, 0.0) + num(t.get("ibCommission"))
    lines = ["# P&L from the ledger", "",
             "Built %s from %d trades. Realized P&L uses IBKR's FIFO figures where the report includes them "
             "and a FIFO calculation otherwise. IBKR's statements remain the official record." % (
                 now_utc(), len(trades)), "",
             "## Realized by month", "", "| Month | Currency | Realized P&L |", "|---|---|---|"]
    lines += ["| %s | %s | %s |" % (m, c, "{:,.2f}".format(v)) for (m, c), v in sorted(by_month.items())]
    lines += ["", "## Realized by symbol", "", "| Symbol | Currency | Realized P&L |", "|---|---|---|"]
    lines += ["| %s | %s | %s |" % (s, c, "{:,.2f}".format(v)) for (s, c), v in sorted(by_symbol.items())]
    lines += ["", "Commissions paid, by currency. %s" % ", ".join(
        "%s %s" % (c, "{:,.2f}".format(-v)) for c, v in sorted(comm.items()))]
    if snaps:
        last = snaps[-1]
        unreal = {}
        for p in last["positions"]:
            cur = p.get("currency") or "?"
            if "fifoPnlUnrealized" in p:
                u = num(p["fifoPnlUnrealized"])
            else:
                u = (num(p.get("markPrice")) - num(p.get("costBasisPrice"))) * num(p.get("position")) * (num(p.get("multiplier"), 1.0) or 1.0)
            unreal[cur] = unreal.get(cur, 0.0) + u
        lines += ["", "## Unrealized as of %s" % (last.get("asOf") or "the latest report"), "",
                  "| Currency | Unrealized P&L |", "|---|---|"]
        lines += ["| %s | %s |" % (c, "{:,.2f}".format(v)) for c, v in sorted(unreal.items())]
    os.makedirs(LEDGER, exist_ok=True)
    with open(os.path.join(LEDGER, "pnl.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    total = {}
    for (m, c), v in by_month.items():
        total[c] = total.get(c, 0.0) + v
    say("realized P&L %s" % ", ".join("%s %s" % (c, "{:,.2f}".format(v)) for c, v in sorted(total.items())))
    say("details in ledger/pnl.md")


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    cmd, args = sys.argv[1], sys.argv[2:]
    if cmd == "setup" and len(args) == 2:
        cmd_setup(args[0], args[1])
    elif cmd == "sync":
        cmd_sync()
    elif cmd == "add" and args:
        cmd_add(args[0], " ".join(args[1:]))
    elif cmd == "research" and args:
        for a in args:
            if os.path.isfile(a):
                cmd_add(a, "research", kind="research", quiet=True)
    elif cmd == "stamp":
        stamp(force="--force" in args, quiet="--quiet" in args)
    elif cmd == "keygen":
        cmd_keygen(" ".join(args).strip() or "investor")
    elif cmd == "verify":
        sys.exit(cmd_verify())
    elif cmd == "pnl":
        cmd_pnl()
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
