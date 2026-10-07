"""Eval harness: runs a pipeline arm over a labelled synthetic split and scores it.

Arms (for the ablation):
  hybrid    --extractor heuristic   deterministic parser + rule engine (no LLM, free)
  hybrid    --extractor gemini      Gemini extraction + rule engine (the production design)
  llm_only                          Gemini reads the PDF + contract and reports findings itself

    python -m evals.run_eval --split test --mode hybrid --extractor heuristic
    python -m evals.run_eval --split test --mode llm_only --limit 60

Writes evals/results/<split>_<arm>.json and .md. Numbers come only from runs of
this script; nothing in the README is typed in by hand.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from freight_audit.extraction import ExtractionError, ExtractionResult, extract
from freight_audit.models import Contract, ErrorType, Finding, Invoice
from freight_audit.rules import PriorInvoice, audit_invoice

HERE = Path(__file__).resolve().parent
HEADER_FIELDS = ["invoice_number", "carrier", "invoice_date", "contract_ref", "bl_number", "origin", "destination",
                 "container_type", "container_count", "ship_date", "currency", "exchange_rate", "equipment_out",
                 "equipment_in", "discharge_date", "pickup_date", "subtotal", "tax_amount", "total"]
LINE_FIELDS = ["charge_type", "quantity", "unit_rate", "amount"]
NUMERIC = {"exchange_rate", "subtotal", "tax_amount", "total", "quantity", "unit_rate", "amount", "container_count"}


def same(field: str, a, b) -> bool:
    if a is None or b is None:
        return a is None and b is None
    if field in NUMERIC:
        return abs(Decimal(str(a)) - Decimal(str(b))) < Decimal("0.005")
    return str(a).strip() == str(b).strip()


def score_extraction(gt: dict, got: dict | None, per_field: dict) -> tuple[int, int]:
    ok = n = 0
    for f in HEADER_FIELDS:
        hit = got is not None and same(f, gt.get(f), got.get(f))
        per_field[f][0] += hit
        per_field[f][1] += 1
        ok, n = ok + hit, n + 1
    gl, xl = gt["lines"], (got or {}).get("lines", [])
    for i in range(max(len(gl), len(xl))):
        for f in LINE_FIELDS:
            hit = i < len(gl) and i < len(xl) and same(f, gl[i][f], xl[i][f])
            per_field[f"line.{f}"][0] += hit
            per_field[f"line.{f}"][1] += 1
            ok, n = ok + hit, n + 1
    return ok, n


def match(labels: list[dict], findings: list[Finding]):
    used, tp, fn = set(), [], []
    for lab in labels:
        for j, f in enumerate(findings):
            if j not in used and f.error_type.value == lab["type"] and f.line_no == lab["line_no"]:
                used.add(j)
                tp.append((lab, f))
                break
        else:
            fn.append(lab)
    fp = [f for j, f in enumerate(findings) if j not in used]
    return tp, fn, fp


def pct(a: float, b: float) -> float | None:
    return round(100 * a / b, 1) if b else None


def _dump_out(seq: int, o: dict) -> dict:
    rec = dict(seq=seq, tokens=list(o["tokens"]), cost=o["cost"], latency=o["latency"])
    if "error" in o:
        rec["error"] = o["error"]
    elif "findings" in o:
        rec["findings"] = [f.model_dump(mode="json") for f in o["findings"]]
    else:
        res = o["extraction"]
        rec["extraction"] = dict(invoice=res.invoice.model_dump(mode="json"), method=res.method, notes=res.notes)
    return rec


def _load_out(rec: dict) -> dict:
    o = dict(tokens=tuple(rec["tokens"]), cost=rec["cost"], latency=rec["latency"])
    if "error" in rec:
        o["error"] = rec["error"]
    elif "findings" in rec:
        o["findings"] = [Finding.model_validate(f) for f in rec["findings"]]
    else:
        e = rec["extraction"]
        o["extraction"] = ExtractionResult(invoice=Invoice.model_validate(e["invoice"]), method=e["method"], raw={},
                                           notes=e["notes"])
    return o


def run(args) -> dict:
    data = Path(args.data)
    contracts = {p.stem: Contract.model_validate_json(p.read_text(encoding="utf-8"))
                 for p in (data / "contracts").glob("*.json")}
    rows = [json.loads(l) for l in open(data / args.split / "labels.jsonl", encoding="utf-8")]
    if args.limit:
        rows = rows[: args.limit]
    pdfs = {r["seq"]: (data / args.split / r["file"]).read_bytes() for r in rows}
    arm = args.mode if args.mode == "llm_only" else f"hybrid_{args.extractor}"
    print(f"[{arm}] {len(rows)} invoices from {args.split}", file=sys.stderr)

    # ---- phase 1: per-invoice model work (parallel when it calls an API)
    def work(r):
        t0 = time.perf_counter()
        try:
            if args.mode == "llm_only":
                from freight_audit.llm_auditor import llm_audit

                gt_prior = [PriorInvoice(p["seq"], p["invoice"]["invoice_number"], p["invoice"]["carrier"],
                                         p["invoice"]["bl_number"], Decimal(p["invoice"]["total"]), p["invoice"]["currency"])
                            for p in rows if p["seq"] < r["seq"]]
                findings, usage = llm_audit(pdfs[r["seq"]], contracts[r["contract_id"]], gt_prior)
                return dict(findings=findings, tokens=(usage.input_tokens, usage.output_tokens), cost=usage.cost_usd,
                            latency=time.perf_counter() - t0)
            res = extract(pdfs[r["seq"]], mode=args.extractor)
            return dict(extraction=res, tokens=(res.input_tokens, res.output_tokens), cost=res.cost_usd,
                        latency=time.perf_counter() - t0)
        except (ExtractionError, ValueError, KeyError) as e:
            return dict(error=f"{type(e).__name__}: {e}", tokens=(0, 0), cost=0.0, latency=time.perf_counter() - t0)
        except Exception as e:  # API errors etc. - count as failures, don't abort the run
            return dict(error=f"{type(e).__name__}: {e}", tokens=(0, 0), cost=0.0, latency=time.perf_counter() - t0,
                        transient=True)

    # Checkpoint: each finished invoice is appended to a JSONL file, so a long API run can be watched
    # (progress on stderr) and resumed after an interruption. Transient API failures are not saved,
    # so a resume retries them. --fresh discards the checkpoint.
    ckpt = Path(args.out) / f".ckpt_{args.split}_{arm}{f'_n{args.limit}' if args.limit else ''}.jsonl"
    done: dict[int, dict] = {}
    if ckpt.exists() and not args.fresh:
        for line in ckpt.read_text(encoding="utf-8").splitlines():
            rec = json.loads(line)
            done[rec["seq"]] = _load_out(rec)
        print(f"[{arm}] resuming: {len(done)} invoices restored from {ckpt.name}", file=sys.stderr)
    elif ckpt.exists():
        ckpt.unlink()
    todo = [r for r in rows if r["seq"] not in done]
    workers = 1 if (args.mode == "hybrid" and args.extractor == "heuristic") else args.workers
    t_start, finished = time.perf_counter(), 0
    ckpt.parent.mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(workers) as ex, open(ckpt, "a", encoding="utf-8") as fh:
        futures = {ex.submit(work, r): r for r in todo}
        for fut in as_completed(futures):
            r, o = futures[fut], fut.result()
            done[r["seq"]] = o
            finished += 1
            if not o.get("transient"):
                fh.write(json.dumps(_dump_out(r["seq"], o)) + "\n")
                fh.flush()
            if workers > 1 or len(todo) <= 100 or finished % 25 == 0:
                rate = (time.perf_counter() - t_start) / finished
                status = "ok" if "error" not in o else o["error"][:60]
                print(f"[{arm}] {len(done)}/{len(rows)} seq {r['seq']} ({r['template']}) {o['latency']:.0f}s {status}"
                      f" | ETA {rate * (len(todo) - finished) / 60:.0f} min", file=sys.stderr, flush=True)
    outs = [done[r["seq"]] for r in rows]

    # ---- phase 2: sequential audit (duplicate detection needs order) and scoring
    per_type = defaultdict(lambda: dict(tp=0, fn=0, fp=0))
    per_field = defaultdict(lambda: [0, 0])
    ext_ok = ext_n = perfect = failures = review = 0
    clean_lines = flagged_clean_lines = clean_inv = flagged_clean_inv = 0
    injected = identified = false_claimed = Decimal(0)
    history: list[PriorInvoice] = []
    per_invoice = []
    for r, o in zip(rows, outs):
        labels = r["errors"]
        findings: list[Finding] = []
        got = None
        if "error" in o:
            failures += 1
            review += 1
        elif args.mode == "llm_only":
            findings = o["findings"]
        else:
            res = o["extraction"]
            inv = res.invoice
            got = json.loads(inv.model_dump_json())
            contract = contracts.get(inv.contract_ref or "") or next(
                (c for c in contracts.values() if c.carrier.lower() == inv.carrier.lower()), None)
            if contract is None:
                review += 1
            else:
                result = audit_invoice(inv, contract, history)
                findings = result.findings
                review += result.needs_review
            history.append(PriorInvoice(r["seq"], inv.invoice_number, inv.carrier, inv.bl_number, inv.total, inv.currency))
        if args.mode != "llm_only":
            ok, n = score_extraction(r["invoice"], got, per_field)
            ext_ok, ext_n, perfect = ext_ok + ok, ext_n + n, perfect + (ok == n)

        tp, fn, fp = match(labels, findings)
        for lab, f in tp:
            per_type[lab["type"]]["tp"] += 1
            identified += min(f.difference, Decimal(str(lab["overcharge"])))
        for lab in fn:
            per_type[lab["type"]]["fn"] += 1
        for f in fp:
            per_type[f.error_type.value]["fp"] += 1
            false_claimed += max(f.difference, Decimal(0))
        injected += sum((Decimal(str(l["overcharge"])) for l in labels), Decimal(0))

        labelled_lines = {l["line_no"] for l in labels if l["line_no"] is not None}
        flagged = {f.line_no for f in findings if f.line_no is not None}
        for ln in range(1, len(r["invoice"]["lines"]) + 1):
            if ln not in labelled_lines:
                clean_lines += 1
                flagged_clean_lines += ln in flagged
        if not labels:
            clean_inv += 1
            flagged_clean_inv += bool(findings)
        per_invoice.append(dict(seq=r["seq"], file=r["file"], template=r["template"], labels=labels,
                                findings=[dict(type=f.error_type.value, line_no=f.line_no, diff=float(f.difference),
                                               rule=f.rule_id) for f in findings],
                                missed=[l["type"] for l in fn], false=[f.error_type.value for f in fp],
                                error=o.get("error"), latency=round(o["latency"], 3)))

    tot = dict(tp=sum(v["tp"] for v in per_type.values()), fn=sum(v["fn"] for v in per_type.values()),
               fp=sum(v["fp"] for v in per_type.values()))
    lat = sorted(o["latency"] for o in outs)
    report = dict(
        arm=arm, split=args.split, n_invoices=len(rows), generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        model=None if arm == "hybrid_heuristic" else __import__("freight_audit.config", fromlist=["x"]).get_settings().gemini_model,
        failures=failures, routed_to_review=review,
        extraction=None if args.mode == "llm_only" else dict(
            field_accuracy=pct(ext_ok, ext_n), perfect_invoices=pct(perfect, len(rows)),
            per_field={k: pct(*v) for k, v in sorted(per_field.items())}),
        detection=dict(
            overall=dict(**tot, recall=pct(tot["tp"], tot["tp"] + tot["fn"]), precision=pct(tot["tp"], tot["tp"] + tot["fp"])),
            per_type={k: dict(**v, recall=pct(v["tp"], v["tp"] + v["fn"]), precision=pct(v["tp"], v["tp"] + v["fp"]))
                      for k, v in sorted(per_type.items())}),
        false_alarms=dict(clean_lines=clean_lines, flagged_clean_lines=flagged_clean_lines,
                          clean_line_false_alarm_rate=pct(flagged_clean_lines, clean_lines),
                          clean_invoices=clean_inv, flagged_clean_invoices=flagged_clean_inv,
                          clean_invoice_false_alarm_rate=pct(flagged_clean_inv, clean_inv)),
        money_usd=dict(injected_overcharge=float(injected), correctly_identified=float(identified),
                       identified_pct=pct(float(identified), float(injected)), falsely_claimed=float(false_claimed)),
        cost=dict(total_usd=round(sum(o["cost"] for o in outs), 4),
                  per_invoice_usd=round(sum(o["cost"] for o in outs) / len(rows), 5),
                  input_tokens=sum(o["tokens"][0] for o in outs), output_tokens=sum(o["tokens"][1] for o in outs)),
        latency_s=dict(mean=round(statistics.mean(lat), 3), p50=round(lat[len(lat) // 2], 3),
                       p95=round(lat[min(len(lat) - 1, int(len(lat) * 0.95))], 3)),
        invoices=per_invoice,
    )
    return report


def to_markdown(r: dict) -> str:
    d = r["detection"]
    out = [f"### {r['arm']} on `{r['split']}` ({r['n_invoices']} invoices)", "",
           f"Generated {r['generated_at']}" + (f", model `{r['model']}`" if r["model"] else ""), ""]
    if r["extraction"]:
        out += [f"- Extraction field accuracy: **{r['extraction']['field_accuracy']}%** "
                f"(invoices extracted perfectly: {r['extraction']['perfect_invoices']}%)"]
    fa = r["false_alarms"]
    m = r["money_usd"]
    out += [f"- Detection: recall **{d['overall']['recall']}%**, precision **{d['overall']['precision']}%** "
            f"(TP {d['overall']['tp']}, FN {d['overall']['fn']}, FP {d['overall']['fp']})",
            f"- False alarms: {fa['clean_line_false_alarm_rate']}% of clean lines, "
            f"{fa['clean_invoice_false_alarm_rate']}% of clean invoices",
            f"- Money: injected USD {m['injected_overcharge']:,.2f}, correctly identified USD "
            f"{m['correctly_identified']:,.2f} ({m['identified_pct']}%), falsely claimed USD {m['falsely_claimed']:,.2f}",
            f"- Failures: {r['failures']}, routed to review: {r['routed_to_review']}",
            f"- Cost: USD {r['cost']['total_usd']} total, USD {r['cost']['per_invoice_usd']}/invoice; "
            f"latency mean {r['latency_s']['mean']}s, p95 {r['latency_s']['p95']}s", "",
            "| Error type | TP | FN | FP | Recall | Precision |", "|---|---|---|---|---|---|"]
    for k, v in d["per_type"].items():
        out.append(f"| {k} | {v['tp']} | {v['fn']} | {v['fp']} | {v['recall']}% | {v['precision']}% |")
    return "\n".join(out) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", default=str(HERE.parents[1] / "data" / "synthetic"))
    ap.add_argument("--split", default="test", choices=["dev", "test"])
    ap.add_argument("--mode", default="hybrid", choices=["hybrid", "llm_only"])
    ap.add_argument("--extractor", default="heuristic", choices=["heuristic", "gemini"])
    ap.add_argument("--limit", type=int, default=0, help="only the first N invoices (keeps API cost down)")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--out", default=str(HERE / "results"))
    ap.add_argument("--fresh", action="store_true", help="ignore any checkpoint and start over")
    a = ap.parse_args(argv)
    report = run(a)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    stem = f"{a.split}_{report['arm']}" + (f"_n{a.limit}" if a.limit else "")
    (out / f"{stem}.json").write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    md = to_markdown(report)
    (out / f"{stem}.md").write_text(md, encoding="utf-8")
    (out / f".ckpt_{stem}.jsonl").unlink(missing_ok=True)  # run complete; a rerun should start fresh
    print(md)
    return report


if __name__ == "__main__":
    main()
