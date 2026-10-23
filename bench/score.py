#!/usr/bin/env python3
"""Score scanner results against the synthetic benchmark's ground truth.

    python3 -m bench.score --results results_bench --gt bench/data/gt \\
        [--json score.json] [--md report.md] [--inr 88] [--worst 20]

--results holds the scanner's <id>.json files (docs/OUTPUT_FORMAT.md). --gt holds the specs
made by bench/synth/spec.py, one <id>.json per bill, optionally with a "photo" recipe.

What is scored, most important first:
  1. Safety. A bill marked auto_ok that is not fully correct is a "silent error": it would be
     posted to the ERP wrongly. This must be 0.
  2. Pricing. Every item row's quantity, rate and amount must be exactly right. Predicted rows
     are paired with truth rows by an order-preserving alignment (align_rows); unpaired truth
     rows are "missed", unpaired predicted rows are "extra" (hallucinated or duplicated).
  3. Header. Supplier GSTIN, invoice number, date, grand total and supplier name.

A missing or unreadable result file, or a scanner error payload ({"error": ...} or {"_raw": ...}
without line_items), counts as a failed bill and is listed. The exit status is 1 when there are
silent errors, missing or failed results, or unreadable truth files, so a run can gate CI.
"""
import argparse
import difflib
import json
import math
import re
import statistics
import sys
from pathlib import Path

QTY_TOL = 0.001       # quantities must agree to the gram / millilitre
MONEY_TOL = 0.01      # rates and amounts must agree to the paisa
STRICT_TOL = 0.005    # strict amount: equal at 2 decimal places
MATCH_MIN = 0.45      # row pairs less similar than this are never paired
DESC_WEIGHT = 0.6     # row similarity = 0.6 * description + 0.4 * numeric agreement
DESC_OK = 0.8         # description counted as read correctly (reported only, not part of pricing)
DESC_TIE = 0.05       # descriptions this close fit a predicted row equally well; numbers pick between them
NAME_MIN = 0.8        # supplier name fuzzy match

HEADER_FIELDS = ["gstin", "invoice_number", "date", "grand_total", "supplier_name"]
HEADER_LABELS = {"gstin": "GSTIN", "invoice_number": "invoice no.", "date": "date",
                 "grand_total": "grand total", "supplier_name": "supplier name"}
FLAGS = ["handwritten", "continued", "stamp_over_table", "rotated", "underlay", "has_correction", "no_gstin",
         "tax_inclusive"]
DIFFICULTY_ORDER = ["clean", "easy", "medium", "hard", "extreme"]


# ---------- normalising and comparing values ----------

# the first number in a string: '4 Boxes' -> 4, 'Rs. 1,23,456.50' -> 123456.50, '.5 kg' -> 0.5
NUMBER = re.compile(r"-?\d[\d,]*(?:\.\d+)?|(?<![A-Za-z])-?\.\d+")


def num(x):
    """A number from a result field, or None. Accepts strings like '1,234.50' or '4 Boxes' (the first
    number counts, so '4 Boxes (5 KG)' is 4); rejects booleans, NaN and infinity."""
    if x is None or isinstance(x, bool):
        return None
    if isinstance(x, (int, float)):
        v = float(x)
    else:
        s = str(x).strip()
        try:
            v = float(s.replace(",", ""))
        except ValueError:
            m = NUMBER.search(s)
            if not m:
                return None
            v = float(m.group().replace(",", ""))
    return v if math.isfinite(v) else None


def near(a, b, tol):
    """True when a and b are both numbers and differ by at most tol (plus float noise)."""
    a, b = num(a), num(b)
    return a is not None and b is not None and abs(a - b) <= tol + 1e-9


def norm_text(s):
    """Lowercase words and digits only: 'FROZEN Chicken (Varha)' -> 'frozen chicken varha'."""
    return " ".join(re.findall(r"[a-z0-9]+", str(s or "").lower()))


def desc_similarity(a, b):
    """difflib ratio of two item descriptions after norm_text, 0..1."""
    a, b = norm_text(a), norm_text(b)
    if not a or not b:
        return 0.0
    return difflib.SequenceMatcher(None, a, b).ratio()


def norm_invoice(s):
    """Invoice numbers compare on letters and digits only: '26-27/1064' -> '26271064'."""
    return re.sub(r"[^A-Z0-9]", "", str(s or "").upper())


def norm_gstin(s):
    """Uppercase, no whitespace; empty -> None."""
    return re.sub(r"\s", "", str(s or "")).upper() or None


def norm_name(s):
    """Supplier names: 'M/s Malabar Fresh Farms Private Limited' -> 'malabar fresh farms pvt ltd'."""
    s = str(s or "").lower()
    s = re.sub(r"^\s*m\s*/\s*s\b\.?\s*", "", s)
    s = re.sub(r"\bprivate\b", "pvt", s)
    s = re.sub(r"\blimited\b", "ltd", s)
    s = s.replace("&", " and ")
    return norm_text(s)


def name_similarity(a, b):
    a, b = norm_name(a), norm_name(b)
    if not a or not b:
        return 0.0
    return difflib.SequenceMatcher(None, a, b).ratio()


# ---------- item rows ----------

def rate_choices(gt):
    """Rates a correct reader may return: the pre-tax rate or the tax-inclusive rate (both get printed)."""
    r, t = gt["rate"], gt.get("tax_percent") or 0
    return list(dict.fromkeys([r, round(r * (1 + t / 100), 2)]))


def with_tax(gt):
    """The row's taxable value plus CGST and SGST."""
    taxable = gt.get("taxable", gt["amount"])
    return round(taxable + (gt.get("cgst") or 0) + (gt.get("sgst") or 0), 2)


def amount_choices(gt):
    """Amounts a correct reader may return: the printed amount, the taxable value or taxable + CGST + SGST."""
    return list(dict.fromkeys([gt["amount"], gt.get("taxable", gt["amount"]), with_tax(gt)]))


def check_row(pred, gt):
    """Field-by-field correctness of one predicted row against its truth row."""
    q = near(pred.get("quantity"), gt["quantity"], QTY_TOL)
    r = any(near(pred.get("rate"), x, MONEY_TOL) for x in rate_choices(gt))
    a = any(near(pred.get("amount"), x, MONEY_TOL) for x in amount_choices(gt))
    strict = near(pred.get("amount"), gt["amount"], STRICT_TOL)
    # a tax-inclusive rate only goes with a tax-inclusive amount: 2 x 105 = 200 is not a right row
    consistent = near(pred.get("rate"), gt["rate"], MONEY_TOL) or near(pred.get("amount"), with_tax(gt), MONEY_TOL)
    return {"qty": q, "rate": r, "amount": a, "amount_strict": strict, "consistent": consistent,
            "price_perfect": q and r and a and consistent, "price_perfect_strict": q and r and strict and consistent}


def numbers_agree(pred, gt):
    """Agreement of a row's numbers, 0..1: amount counts half, qty and rate a quarter each."""
    c = check_row(pred, gt)
    return 0.5 * c["amount"] + 0.25 * c["qty"] + 0.25 * c["rate"]


def row_similarity(pred, gt):
    """How alike two rows are, 0..1: description similarity plus agreement of amount, qty and rate."""
    return (DESC_WEIGHT * desc_similarity(pred.get("description"), gt["description"])
            + (1 - DESC_WEIGHT) * numbers_agree(pred, gt))


def align_rows(pred_items, gt_items, min_sim=MATCH_MIN):
    """Pair predicted rows with truth rows, keeping both in top-to-bottom order.

    Like sequence alignment: dynamic programming picks the order-preserving set of pairs with
    the largest total of (similarity - min_sim). So a pair is only made when it beats leaving
    both rows unpaired, and one strong pair beats two weak ones. Because similarity includes the
    numbers, rows with identical descriptions are told apart by qty/rate/amount.

    Numbers only choose between truth rows whose descriptions fit the predicted row about equally
    well. When a predicted description clearly names one truth row (similarity >= DESC_OK), its
    numbers earn nothing towards any other row. Otherwise a reader that shifts the numbers one row
    down a run of look-alike items ("KUMBAYAH MANGO 275ML" with the BERRY MIX row's qty, rate and
    amount) would be paired by numbers and scored as nearly all right, when every item has the
    wrong price.

    Returns {"pairs": [(gt_index, pred_index, similarity), ...],
             "missed": [gt indexes never paired], "extra": [pred indexes never paired]}.
    """
    n, m = len(gt_items), len(pred_items)
    desc = [[desc_similarity(p.get("description"), g["description"]) for p in pred_items] for g in gt_items]
    sim = [[0.0] * m for _ in range(n)]
    for j in range(m):
        top = max(desc[i][j] for i in range(n)) if n else 0.0     # how well pred[j] fits its best truth row
        for i in range(n):
            names_other_row = top >= DESC_OK and desc[i][j] < top - DESC_TIE
            numeric = 0.0 if names_other_row else numbers_agree(pred_items[j], gt_items[i])
            sim[i][j] = DESC_WEIGHT * desc[i][j] + (1 - DESC_WEIGHT) * numeric
    # best[i][j] = best total for aligning gt[i:] with pred[j:]; suffix form lets us walk forward
    best = [[0.0] * (m + 1) for _ in range(n + 1)]
    for i in range(n - 1, -1, -1):
        for j in range(m - 1, -1, -1):
            s = max(best[i + 1][j], best[i][j + 1])
            if sim[i][j] >= min_sim:
                s = max(s, best[i + 1][j + 1] + sim[i][j] - min_sim)
            best[i][j] = s
    pairs, i, j = [], 0, 0
    while i < n and j < m:
        if sim[i][j] >= min_sim and best[i][j] == best[i + 1][j + 1] + sim[i][j] - min_sim:
            pairs.append((i, j, round(sim[i][j], 3)))
            i, j = i + 1, j + 1
        elif best[i][j] == best[i + 1][j]:
            i += 1
        else:
            j += 1
    paired_gt = {p[0] for p in pairs}
    paired_pred = {p[1] for p in pairs}
    return {"pairs": pairs,
            "missed": [i for i in range(n) if i not in paired_gt],
            "extra": [j for j in range(m) if j not in paired_pred]}


# ---------- one bill ----------

def _obj(x):
    """x when it is a dict, else {}: a malformed field must not crash the whole run."""
    return x if isinstance(x, dict) else {}


def result_problem(d):
    """Why a parsed result file is not a usable scan, or None when it is one.

    Error payloads ({"error": ...}, {"_raw": "<unparsed model text>"}, _meta.status == "error")
    and objects without line_items count as failed scans, like a missing file."""
    if not isinstance(d, dict):
        return "result is not a JSON object"
    meta = _obj(d.get("_meta"))
    err = d.get("error") or d.get("_error") or meta.get("error")
    if err or meta.get("status") == "error":
        return f"scanner error: {str(err or 'status error')[:120]}"
    if "line_items" not in d:
        return "scanner returned unparsed output (_raw)" if "_raw" in d else "result has no line_items"
    return None


def _on(v):
    """A photo-recipe entry is switched on: truthy, and not a dict saying enabled/present = False."""
    if isinstance(v, dict):
        return bool(v) and v.get("enabled", True) is not False and v.get("present", True) is not False
    return bool(v)


def _stamp_over_table(photo):
    """Whether a stamp covers the item table. Accepts photo["stamp_over_table"], or a "stamp"/"stamps"
    entry (dict or list of dicts) with over_table/on_table/covers_table, or where/region == "table"."""
    if "stamp_over_table" in photo:
        return bool(photo["stamp_over_table"])
    stamps = photo.get("stamps") or photo.get("stamp") or []
    if isinstance(stamps, dict):
        stamps = [stamps]
    if not isinstance(stamps, list):
        return False
    for s in stamps:
        if not isinstance(s, dict) or not _on(s):
            continue
        where = str(s.get("where") or s.get("region") or s.get("position") or s.get("placement") or "").lower()
        if s.get("over_table") or s.get("on_table") or s.get("covers_table") or where in ("table", "items", "over_table"):
            return True
    return False


def bill_flags(spec):
    """The difficulty flags that apply to a truth spec, in FLAGS order."""
    photo = spec.get("photo") or {}
    deg = num(photo.get("rotate_deg"))
    on = {
        "handwritten": bool(spec.get("handwritten_items")),
        "continued": bool(spec.get("continued")),
        "stamp_over_table": _stamp_over_table(photo),
        "rotated": deg is not None and round(deg) % 360 != 0,
        # bench/build.py records the underlay as photo["underlay_gstin"]
        "underlay": _on(photo.get("underlay")) or _on(photo.get("underlay_gstin")),
        "has_correction": any((spec.get("corrections") or {}).values()),
        "no_gstin": not norm_gstin(_obj(spec.get("supplier")).get("gstin")),
        "tax_inclusive": spec.get("tax_mode") == "inclusive",
    }
    return [f for f in FLAGS if on[f]]


def difficulty(spec):
    d = (spec.get("photo") or {}).get("difficulty")
    return "n/a" if d is None else str(d)


def _f(x):
    """Short number for messages: 7665.0 -> '7665', 2.25 -> '2.25', None -> 'none'."""
    x = num(x)
    return "none" if x is None else f"{x:.3f}".rstrip("0").rstrip(".")


def _or(values):
    return " or ".join(_f(v) for v in values)


def score_header(pred, spec):
    """Header fields: {field: True/False, or None when not scored}, plus problem messages."""
    sup, gt_sup = _obj(pred.get("supplier")), _obj(spec.get("supplier"))
    truth_total = _obj(spec.get("totals")).get("grand_total")
    pred_total = _obj(pred.get("totals")).get("grand_total")
    gt_gstin = norm_gstin(gt_sup.get("gstin"))
    ok = {
        # no GSTIN printed => the reader must return none, not invent one
        "gstin": norm_gstin(sup.get("gstin")) == gt_gstin,
        "invoice_number": norm_invoice(pred.get("invoice_number")) == norm_invoice(spec.get("invoice_number"))
        and bool(norm_invoice(spec.get("invoice_number"))),
        "date": str(pred.get("invoice_date") or "").strip() == spec.get("invoice_date"),
        # continued pages print no total: not scored
        "grand_total": None if truth_total is None or spec.get("continued") else near(pred_total, truth_total, MONEY_TOL),
        "supplier_name": name_similarity(sup.get("name"), gt_sup.get("name")) >= NAME_MIN,
    }
    shown = {"gstin": (sup.get("gstin"), gt_sup.get("gstin")),
             "invoice_number": (pred.get("invoice_number"), spec.get("invoice_number")),
             "date": (pred.get("invoice_date"), spec.get("invoice_date")),
             "grand_total": (_f(pred_total), _f(truth_total)),
             "supplier_name": (sup.get("name"), gt_sup.get("name"))}
    problems = [f"{HEADER_LABELS[k]} {shown[k][0]!r} (truth {shown[k][1]!r})"
                for k in HEADER_FIELDS if ok[k] is False]
    return ok, problems


def _row_text(it):
    return f"{str(it.get('description') or '')[:32]!r} {_f(it.get('quantity'))} x {_f(it.get('rate'))} = {_f(it.get('amount'))}"


def score_bill(pred, spec, missing_reason=None):
    """Score one scanner result (dict from <id>.json) against its truth spec.

    pred=None means the result file is missing or unreadable, and a result that is an error
    payload (see result_problem) counts the same: the bill fails everything ("missing" is True,
    status "missing" or "error"). Returns a flat, JSON-ready dict; see aggregate() for how the
    fields are summed.
    """
    gt_items = spec.get("items") or []
    reasons = spec.get("expected_review_reasons") or []
    # a failed scan may still report its cost and time in _meta, so keep that
    meta = _obj(pred.get("_meta")) if isinstance(pred, dict) else {}
    if pred is None:
        failure, status = missing_reason or "no result file", "missing"
    else:
        failure = result_problem(pred)
        status = "error" if failure else str(meta.get("status") or "unknown")
    if failure:
        pred = None
    b = {"id": spec.get("id"), "template": spec.get("template") or "?", "difficulty": difficulty(spec),
         "flags": bill_flags(spec), "expected_review": bool(spec.get("expected_review")),
         "expected_review_reasons": reasons, "missing": pred is None, "gt_rows": len(gt_items)}
    problems = []
    if pred is None:
        pred_items = []
        problems.append(failure)
    else:
        items = pred.get("line_items")
        pred_items = [it if isinstance(it, dict) else {} for it in (items if isinstance(items, list) else [])]
    b["status"] = status
    b["auto_ok"] = b["status"] == "auto_ok"
    b["pred_rows"] = len(pred_items)

    # rows
    al = align_rows(pred_items, gt_items)
    rows, counts = [], dict.fromkeys(("qty", "rate", "amount", "amount_strict", "price_perfect",
                                      "price_perfect_strict", "desc_ok"), 0)
    row_problems = []
    for gi, pj, s in al["pairs"]:
        c = check_row(pred_items[pj], gt_items[gi])
        c["desc_ok"] = desc_similarity(pred_items[pj].get("description"), gt_items[gi]["description"]) >= DESC_OK
        rows.append({"gt": gi, "pred": pj, "sim": s, **c})
        for k in counts:
            counts[k] += c[k]
        if not c["price_perfect"]:
            p, g = pred_items[pj], gt_items[gi]
            bad = []
            if not c["qty"]:
                bad.append(f"qty {_f(p.get('quantity'))} (truth {_f(g['quantity'])})")
            if not c["rate"]:
                bad.append(f"rate {_f(p.get('rate'))} (truth {_or(rate_choices(g))})")
            if not c["amount"]:
                bad.append(f"amount {_f(p.get('amount'))} (truth {_or(amount_choices(g))})")
            if c["qty"] and c["rate"] and c["amount"] and not c["consistent"]:
                bad.append(f"rate {_f(p.get('rate'))} includes tax but amount {_f(p.get('amount'))} does not")
            row_problems.append(f"row {gi + 1} {g['description'][:28]}: " + ", ".join(bad))
    # an extra row that would pair strongly with a missed row was read out of printed order
    reordered = 0
    extra_msgs = []
    for pj in al["extra"]:
        strong = [gi for gi in al["missed"] if row_similarity(pred_items[pj], gt_items[gi]) >= 0.9]
        reordered += bool(strong)
        note = f" (out of order: truth row {strong[0] + 1})" if strong else ""
        extra_msgs.append(f"extra row {_row_text(pred_items[pj])}{note}")
    if pred is not None:
        problems += [f"missed row {gi + 1} {_row_text(gt_items[gi])}" for gi in al["missed"]]
        problems += row_problems + extra_msgs

    b.update({"matched": len(al["pairs"]), "missed": len(al["missed"]), "extra": len(al["extra"]),
              "reordered": reordered,
              "qty_ok": counts["qty"], "rate_ok": counts["rate"], "amount_ok": counts["amount"],
              "amount_strict_ok": counts["amount_strict"], "price_perfect": counts["price_perfect"],
              "price_perfect_strict": counts["price_perfect_strict"], "desc_ok": counts["desc_ok"],
              "rows": rows, "missed_rows": al["missed"], "extra_rows": al["extra"]})

    # header
    if pred is None:
        truth_total = _obj(spec.get("totals")).get("grand_total")
        skip_total = truth_total is None or spec.get("continued")
        header = {k: (None if k == "grand_total" and skip_total else False) for k in HEADER_FIELDS}
    else:
        header, header_problems = score_header(pred, spec)
        problems += header_problems
    b["header"] = header
    b["header_ok"] = all(v is not False for v in header.values())

    # bill level
    n = len(gt_items)
    b["items_perfect"] = b["matched"] == n and b["price_perfect"] == n and b["extra"] == 0 and pred is not None
    b["items_perfect_strict"] = b["items_perfect"] and b["price_perfect_strict"] == n
    b["bill_perfect"] = b["items_perfect"] and b["header_ok"]
    b["errors"] = (b["missed"] + b["extra"] + (b["matched"] - b["price_perfect"])
                   + sum(v is False for v in header.values()))

    # safety
    b["silent_error"] = b["auto_ok"] and not b["bill_perfect"]
    b["missed_review"] = b["auto_ok"] and b["expected_review"]
    b["unnecessary_review"] = (not b["missing"] and not b["auto_ok"] and not b["expected_review"]
                               and b["bill_perfect"])
    if b["missed_review"]:
        problems.insert(0, "auto_ok but truth expects review (" + ", ".join(reasons or ["?"]) + ")")
    if b["silent_error"]:
        problems.insert(0, "AUTO_OK BUT WRONG")

    b["cost_usd"] = num(_obj(meta.get("usage")).get("cost_usd"))
    b["seconds"] = num(meta.get("seconds"))
    b["issues"] = [str(i) for i in meta.get("issues")] if isinstance(meta.get("issues"), list) else []
    b["problems"] = problems
    return b


# ---------- many bills ----------

def _frac(a, b):
    return round(a / b, 4) if b else None


def aggregate(bills, inr=88.0):
    """Sum score_bill() results into counts and rates (rates are fractions 0..1, None when undefined)."""
    n = len(bills)

    def total(key):
        return sum(b[key] for b in bills)

    truth = total("gt_rows")
    rows = {"truth": truth, "predicted": total("pred_rows"), "matched": total("matched"),
            "missed": total("missed"), "extra": total("extra"), "reordered": total("reordered"),
            "qty_ok": total("qty_ok"), "rate_ok": total("rate_ok"), "amount_ok": total("amount_ok"),
            "amount_strict_ok": total("amount_strict_ok"), "price_perfect": total("price_perfect"),
            "price_perfect_strict": total("price_perfect_strict"), "desc_ok": total("desc_ok")}
    # accuracies are over truth rows, so missed rows count as wrong
    rows.update({"price_accuracy": _frac(rows["price_perfect"], truth),
                 "price_accuracy_strict": _frac(rows["price_perfect_strict"], truth),
                 "qty_accuracy": _frac(rows["qty_ok"], truth), "rate_accuracy": _frac(rows["rate_ok"], truth),
                 "amount_accuracy": _frac(rows["amount_ok"], truth), "desc_accuracy": _frac(rows["desc_ok"], truth),
                 "precision": _frac(rows["price_perfect"], rows["predicted"])})

    header = {}
    for k in HEADER_FIELDS:
        scored = [b["header"][k] for b in bills if b["header"][k] is not None]
        header[k] = {"ok": sum(scored), "n": len(scored), "accuracy": _frac(sum(scored), len(scored))}

    auto = [b for b in bills if b["auto_ok"]]
    expect = [b for b in bills if b["expected_review"]]
    should_auto = [b for b in bills if not b["expected_review"] and b["bill_perfect"] and not b["missing"]]
    safety = {"auto_ok": len(auto), "automation_rate": _frac(len(auto), n),
              "automation_ceiling": _frac(n - len(expect), n),
              "silent_errors": total("silent_error"),
              "auto_ok_correct": sum(b["bill_perfect"] for b in auto),
              "auto_ok_precision": _frac(sum(b["bill_perfect"] for b in auto), len(auto)),
              "expected_review": len(expect), "missed_review": total("missed_review"),
              "should_automate": len(should_auto), "unnecessary_review": total("unnecessary_review")}

    costs = [b["cost_usd"] for b in bills if b["cost_usd"] is not None]
    usd = sum(costs)
    per_bill = usd / len(costs) if costs else None
    cost = {"bills_with_cost": len(costs), "usd_total": round(usd, 6),
            "usd_per_bill": None if per_bill is None else round(per_bill, 6),
            "inr_total": round(usd * inr, 3),
            "inr_per_bill": None if per_bill is None else round(per_bill * inr, 4),
            "inr_per_1000_bills": None if per_bill is None else round(per_bill * inr * 1000, 1)}

    secs = sorted(b["seconds"] for b in bills if b["seconds"] is not None)
    latency = {"bills": len(secs),
               "avg": round(statistics.mean(secs), 2) if secs else None,
               "median": round(statistics.median(secs), 2) if secs else None,
               # nearest rank: 90% of bills took at most this long
               "p90": secs[math.ceil(0.9 * len(secs)) - 1] if secs else None,
               "max": secs[-1] if secs else None}

    return {"bills": n, "missing": total("missing"),
            "items_perfect": total("items_perfect"), "items_perfect_rate": _frac(total("items_perfect"), n),
            "items_perfect_strict": total("items_perfect_strict"),
            "items_perfect_strict_rate": _frac(total("items_perfect_strict"), n),
            "bill_perfect": total("bill_perfect"), "bill_perfect_rate": _frac(total("bill_perfect"), n),
            "rows": rows, "header": header, "safety": safety, "cost": cost, "latency": latency}


def _difficulty_key(d):
    return (DIFFICULTY_ORDER.index(d) if d in DIFFICULTY_ORDER else len(DIFFICULTY_ORDER), d)


def breakdowns(bills, inr=88.0):
    """aggregate() per template, per photo difficulty and per flag ('no flags' = none of them)."""
    by_template = {t: aggregate([b for b in bills if b["template"] == t], inr)
                   for t in sorted({b["template"] for b in bills})}
    by_difficulty = {d: aggregate([b for b in bills if b["difficulty"] == d], inr)
                     for d in sorted({b["difficulty"] for b in bills}, key=_difficulty_key)}
    by_flag = {f: aggregate([b for b in bills if f in b["flags"]], inr)
               for f in FLAGS if any(f in b["flags"] for b in bills)}
    plain = [b for b in bills if not b["flags"]]
    if plain:
        by_flag["no flags"] = aggregate(plain, inr)
    return {"by_template": by_template, "by_difficulty": by_difficulty, "by_flag": by_flag}


def worst_bills(bills, limit=20):
    """Bills that went wrong, worst first: silent errors, then missed reviews, then most errors.
    Missing results are listed separately, so they are left out here."""
    bad = [b for b in bills if not b["missing"] and (not b["bill_perfect"] or b["missed_review"])]
    bad.sort(key=lambda b: (-b["silent_error"], -b["missed_review"], -b["errors"], str(b["id"])))
    return bad[:limit]


# ---------- loading ----------

def load_truth(gt_dir):
    """({id: spec} for every <id>.json in gt_dir that looks like a bench spec (has "items"),
    [names of .json files that could not be read]). Other JSON files, like a manifest, are ignored;
    unreadable ones are returned so a broken truth file can't silently shrink the benchmark."""
    specs, unreadable = {}, []
    for f in sorted(Path(gt_dir).glob("*.json")):
        try:
            d = json.loads(f.read_text())
        except (OSError, ValueError):
            unreadable.append(f.name)
            continue
        if isinstance(d, dict) and isinstance(d.get("items"), list):
            specs[f.stem] = d
    return specs, unreadable


def load_result(results_dir, bill_id):
    """(result dict, None) or (None, reason it can't be used)."""
    f = Path(results_dir) / f"{bill_id}.json"
    if not f.exists():
        return None, "no result file"
    try:
        d = json.loads(f.read_text())
    except (OSError, ValueError) as e:
        return None, f"unreadable result file ({e.__class__.__name__})"
    if not isinstance(d, dict):
        return None, "result file is not a JSON object"
    return d, None


def build_report(results_dir, gt_dir, inr=88.0, worst=20):
    """Score every truth spec in gt_dir against results_dir. Returns the full report dict."""
    specs, unreadable_truth = load_truth(gt_dir)
    bills = []
    for bill_id, spec in specs.items():
        pred, reason = load_result(results_dir, bill_id)
        b = score_bill(pred, {**spec, "id": spec.get("id") or bill_id}, reason)
        b["id"] = bill_id
        bills.append(b)
    known = set(specs)
    unscored = sorted(f.stem for f in Path(results_dir).glob("*.json") if f.stem not in known) \
        if Path(results_dir).is_dir() else []
    return {"results_dir": str(results_dir), "gt_dir": str(gt_dir), "inr_per_usd": inr,
            "overall": aggregate(bills, inr), **breakdowns(bills, inr),
            "missing": [{"id": b["id"], "reason": b["problems"][0]} for b in bills if b["missing"]],
            "silent_errors": [b["id"] for b in bills if b["silent_error"]],
            "worst": [b["id"] for b in worst_bills(bills, worst)],
            "unscored_results": unscored, "unreadable_truth": unreadable_truth, "bills": bills}


# ---------- output ----------

def _pct(x):
    return "-" if x is None else f"{100 * x:.1f}%"


def _of(a, b):
    return f"{a}/{b} ({_pct(_frac(a, b))})"


def _secs(x):
    return "-" if x is None else f"{x:.1f} s"


def _inr(x, dp=3):
    return "-" if x is None else f"Rs {x:,.{dp}f}"


def summary_text(report):
    """The console summary: headline lines, breakdown tables, missing and silent-error lists."""
    o = report["overall"]
    r, s, c, lat, h = o["rows"], o["safety"], o["cost"], o["latency"], o["header"]
    out = [f"Synthetic benchmark: {o['bills']} bills, {r['truth']} truth rows "
           f"(results {report['results_dir']}, truth {report['gt_dir']})"]
    if report.get("unreadable_truth"):
        out.append(f"WARNING  unreadable truth files, not scored: {', '.join(report['unreadable_truth'])}")
    if not o["bills"]:
        out.append("no ground-truth specs found")
        return "\n".join(out)
    out += [
        "",
        f"SAFETY   silent errors (auto_ok but wrong; must be 0): {s['silent_errors']}",
        f"         auto_ok {_of(s['auto_ok'], o['bills'])}, ceiling {_pct(s['automation_ceiling'])}; "
        f"auto_ok precision {_pct(s['auto_ok_precision'])}",
        f"         missed expected review {s['missed_review']}/{s['expected_review']}; "
        f"unnecessary review {s['unnecessary_review']}/{s['should_automate']}",
        f"PRICING  rows price-perfect {_of(r['price_perfect'], r['truth'])}; strict amount {_pct(r['price_accuracy_strict'])}",
        f"         qty {_pct(r['qty_accuracy'])}  rate {_pct(r['rate_accuracy'])}  amount {_pct(r['amount_accuracy'])}  "
        f"description {_pct(r['desc_accuracy'])}; missed rows {r['missed']}, extra rows {r['extra']}",
        f"BILLS    every row price-perfect {_of(o['items_perfect'], o['bills'])}; "
        f"fully correct incl. header {_of(o['bill_perfect'], o['bills'])}",
        "HEADER   " + "  ".join(f"{HEADER_LABELS[k]} {_pct(h[k]['accuracy'])}" for k in HEADER_FIELDS)
        + f"  (total scored on {h['grand_total']['n']})",
        f"COST     ${c['usd_total']:.4f} ({_inr(c['inr_total'], 2)}); {_inr(c['inr_per_bill'])}/bill; "
        f"{_inr(c['inr_per_1000_bills'], 0)} per 1,000 bills",
        f"LATENCY  avg {_secs(lat['avg'])}, median {_secs(lat['median'])}, p90 {_secs(lat['p90'])}, max {_secs(lat['max'])}",
    ]
    head = f"{'':20} {'bills':>5} {'rows':>5} {'price':>6} {'qty':>6} {'rate':>6} {'amount':>6} " \
           f"{'items':>6} {'bill':>6} {'auto':>6} {'silent':>6}"
    for title, key in (("template", "by_template"), ("difficulty", "by_difficulty"), ("flag", "by_flag")):
        groups = report[key]
        if not groups:
            continue
        out += ["", f"by {title}".ljust(20) + head[20:]]
        for name, a in groups.items():
            out.append(f"{str(name)[:20]:20} {a['bills']:5} {a['rows']['truth']:5} "
                       f"{_pct(a['rows']['price_accuracy']):>6} {_pct(a['rows']['qty_accuracy']):>6} "
                       f"{_pct(a['rows']['rate_accuracy']):>6} {_pct(a['rows']['amount_accuracy']):>6} "
                       f"{_pct(a['items_perfect_rate']):>6} {_pct(a['bill_perfect_rate']):>6} "
                       f"{_pct(a['safety']['automation_rate']):>6} {a['safety']['silent_errors']:6}")
    by_id = {b["id"]: b for b in report["bills"]}
    if report["silent_errors"]:
        out += ["", f"silent errors ({len(report['silent_errors'])}):"]
        for i in report["silent_errors"]:
            out.append(f"  {i}: " + "; ".join(by_id[i]["problems"][1:4]))
    if report["missing"]:
        out += ["", f"missing or failed results ({len(report['missing'])}): "
                + ", ".join(f"{m['id']} ({m['reason']})" for m in report["missing"])]
    return "\n".join(out)


def _md(s):
    return str(s).replace("|", "\\|").replace("\n", " ")


def _group_table(groups, label):
    lines = [f"| {label} | Bills | Rows | Rows price-perfect | Qty | Rate | Amount | Missed / extra rows "
             f"| Bills all rows right | Bills fully correct | auto_ok | Silent errors | Cost/bill |",
             "|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|"]
    for name, a in groups.items():
        r = a["rows"]
        lines.append(f"| {_md(name)} | {a['bills']} | {r['truth']} | {_pct(r['price_accuracy'])} | "
                     f"{_pct(r['qty_accuracy'])} | {_pct(r['rate_accuracy'])} | {_pct(r['amount_accuracy'])} | "
                     f"{r['missed']} / {r['extra']} | {_pct(a['items_perfect_rate'])} | {_pct(a['bill_perfect_rate'])} | "
                     f"{_pct(a['safety']['automation_rate'])} | {a['safety']['silent_errors']} | "
                     f"{_inr(a['cost']['inr_per_bill'])} |")
    return lines


def markdown(report):
    """The --md report: headline numbers, field accuracy, breakdowns, worst bills, missing results."""
    o = report["overall"]
    r, s, c, lat, h = o["rows"], o["safety"], o["cost"], o["latency"], o["header"]
    by_id = {b["id"]: b for b in report["bills"]}
    silent = s["silent_errors"]
    L = ["# Synthetic benchmark report", "",
         f"{o['bills']} synthetic bills with {r['truth']} item rows. Results `{_md(report['results_dir'])}`, "
         f"ground truth `{_md(report['gt_dir'])}`."
         + (f" **{o['missing']} result{'s' if o['missing'] > 1 else ''} missing or failed** (counted as failures)."
            if o["missing"] else "")
         + (f" **Unreadable truth files, not scored: {_md(', '.join(report['unreadable_truth']))}.**"
            if report.get("unreadable_truth") else ""), "",
         "## Headline", "",
         "| Metric | Result |", "|---|---|",
         f"| **Silent errors**: auto_ok but wrong (must be 0) | **{silent}**{'' if not silent else ' (FAIL)'} |",
         f"| **Rows price-perfect** (qty, rate and amount all exact) | **{_of(r['price_perfect'], r['truth'])}** |",
         f"| Rows price-perfect, amount must equal the printed line total | {_of(r['price_perfect_strict'], r['truth'])} |",
         f"| Bills with every row price-perfect and no extra rows | {_of(o['items_perfect'], o['bills'])} |",
         f"| Bills fully correct (rows + header) | {_of(o['bill_perfect'], o['bills'])} |",
         f"| Automation rate (auto_ok) | {_of(s['auto_ok'], o['bills'])}; ceiling {_pct(s['automation_ceiling'])} "
         f"(bills that need no review) |",
         f"| auto_ok precision (auto_ok bills that are fully correct) | {_pct(s['auto_ok_precision'])} |",
         f"| Missed expected review (truth says review, got auto_ok) | {s['missed_review']} of {s['expected_review']} |",
         f"| Unnecessary review (correct, needs no review, still flagged) | {s['unnecessary_review']} of "
         f"{s['should_automate']} |",
         f"| Cost | ${c['usd_total']:.4f} ({_inr(c['inr_total'], 2)}) total; {_inr(c['inr_per_bill'])} per bill; "
         f"about {_inr(c['inr_per_1000_bills'], 0)} per 1,000 bills |",
         f"| Latency per bill | avg {_secs(lat['avg'])}, median {_secs(lat['median'])}, p90 {_secs(lat['p90'])}, "
         f"max {_secs(lat['max'])} |",
         "", "## Item rows", "",
         "| | Correct | Accuracy |", "|---|--:|--:|",
         f"| Quantity | {r['qty_ok']} / {r['truth']} | {_pct(r['qty_accuracy'])} |",
         f"| Rate (pre-tax or tax-inclusive) | {r['rate_ok']} / {r['truth']} | {_pct(r['rate_accuracy'])} |",
         f"| Amount (printed, taxable or taxable + GST) | {r['amount_ok']} / {r['truth']} | {_pct(r['amount_accuracy'])} |",
         f"| Amount, printed value only | {r['amount_strict_ok']} / {r['truth']} | "
         f"{_pct(_frac(r['amount_strict_ok'], r['truth']))} |",
         f"| Description readable (similarity >= {DESC_OK}) | {r['desc_ok']} / {r['truth']} | {_pct(r['desc_accuracy'])} |",
         "",
         f"Missed rows: {r['missed']}. Extra rows: {r['extra']} ({r['reordered']} of them out of printed order). "
         f"Predicted rows that are price-perfect: {_of(r['price_perfect'], r['predicted'])}.",
         "", "## Header fields", "",
         "| Field | Correct | Accuracy |", "|---|--:|--:|"]
    for k in HEADER_FIELDS:
        L.append(f"| {HEADER_LABELS[k]} | {h[k]['ok']} / {h[k]['n']} | {_pct(h[k]['accuracy'])} |")
    L += ["", "Grand total is not scored on continued pages (no total printed)."]
    for title, key, label in (("By template", "by_template", "Template"),
                              ("By photo difficulty", "by_difficulty", "Difficulty"),
                              ("By flag", "by_flag", "Flag")):
        if report[key]:
            L += ["", f"## {title}", ""] + _group_table(report[key], label)
    if report["by_flag"]:
        L += ["", "A bill can have several flags, so flag rows overlap."]

    worst = [by_id[i] for i in report["worst"]]
    L += ["", f"## Worst {len(worst)} bills", ""]
    if worst:
        L += ["| Bill | Template | Difficulty | Flags | Status | Rows right | What went wrong |",
              "|---|---|---|---|---|--:|---|"]
        for b in worst:
            probs = b["problems"][:6] + ([f"... {len(b['problems']) - 6} more"] if len(b["problems"]) > 6 else [])
            L.append(f"| {_md(b['id'])} | {_md(b['template'])} | {_md(b['difficulty'])} | {_md(', '.join(b['flags']) or '-')} | "
                     f"{'**' + b['status'] + '**' if b['silent_error'] else b['status']} | "
                     f"{b['price_perfect']}/{b['gt_rows']} | {_md('; '.join(probs))} |")
    else:
        L.append("Every scored bill is fully correct.")
    if report["missing"]:
        L += ["", f"## Missing or failed results ({len(report['missing'])})", "",
              "No result file, an unreadable one, or a scanner error payload. These count as failed bills above.", ""]
        L += [f"- {_md(m['id'])}: {_md(m['reason'])}" for m in report["missing"]]
    if report.get("unscored_results"):
        L += ["", f"Result files with no ground truth (ignored): {', '.join(report['unscored_results'])}"]
    L += ["", "## How it is scored", "",
          "- Predicted rows are paired with truth rows top to bottom by an order-preserving alignment that "
          "weighs description similarity and agreement of amount, qty and rate. Numbers only choose between truth "
          "rows whose descriptions fit equally well, so one item's price read against another item counts as wrong. "
          "Unpaired truth rows are missed; unpaired predicted rows are extra.",
          f"- Quantity must match within {QTY_TOL}; rate and amount within Rs {MONEY_TOL}. Rate may be the pre-tax "
          "or tax-inclusive rate; amount may be the printed amount, the taxable value or taxable + CGST + SGST. "
          "A tax-inclusive rate must come with a tax-inclusive amount.",
          "- GSTIN exact (no GSTIN printed means none must be returned); invoice number exact on letters and digits; "
          f"date exact; grand total within Rs {MONEY_TOL}; supplier name similarity >= {NAME_MIN}.",
          "- A silent error is a bill marked auto_ok that is not fully correct: it would go into the ERP wrong.",
          ""]
    return "\n".join(L)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Score scanner results against synthetic benchmark ground truth.")
    ap.add_argument("--results", required=True, help="folder of scanner output <id>.json files")
    ap.add_argument("--gt", required=True, help="folder of ground-truth spec <id>.json files")
    ap.add_argument("--json", help="write the full machine-readable report here")
    ap.add_argument("--md", help="write a markdown report here")
    ap.add_argument("--inr", type=float, default=88.0, help="rupees per US dollar (default 88)")
    ap.add_argument("--worst", type=int, default=20, help="how many worst bills to list in the markdown report")
    a = ap.parse_args(argv)
    if not Path(a.gt).is_dir():
        ap.error(f"ground-truth folder not found: {a.gt}")
    if not Path(a.results).is_dir():
        print(f"warning: results folder not found: {a.results} (every bill counts as missing)", file=sys.stderr)

    report = build_report(a.results, a.gt, a.inr, max(0, a.worst))
    print(summary_text(report))
    if a.json:
        Path(a.json).write_text(json.dumps(report, indent=1, ensure_ascii=False))
        print(f"\nwrote {a.json}")
    if a.md:
        Path(a.md).write_text(markdown(report))
        print(f"wrote {a.md}")
    o = report["overall"]
    return 1 if o["safety"]["silent_errors"] or o["missing"] or report["unreadable_truth"] or not o["bills"] else 0


if __name__ == "__main__":
    sys.exit(main())
