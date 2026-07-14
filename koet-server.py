#!/usr/bin/env python3
"""
KOET Web UI backend — Flask server that runs koet.py as a subprocess
and streams its output to the browser via Server-Sent Events.

Start with:  python3 koet-server.py
Then open:   http://127.0.0.1:5002
"""

import csv
import json
import re
import signal
import socket
import statistics
import subprocess
import threading
from pathlib import Path

from flask import Flask, Response, jsonify, request, send_file, stream_with_context

app = Flask(__name__)

REPO_ROOT = Path(__file__).parent.resolve()
HOST = "127.0.0.1"
PORT = 5002

ALLOWED_ORIGINS = {
    f"http://{HOST}:{PORT}",
    f"http://localhost:{PORT}",
    "null",  # file:// origin
}

# One test run at a time
_run_state = {
    "running": False,
    "proc": None,
    "log_dir": None,
    "returncode": None,
    "awaiting_confirm": False,
    "kpi": {},  # copy of run config for results parsing
}
_run_lock = threading.Lock()


# ---------------------------------------------------------------------------
# CORS
# ---------------------------------------------------------------------------

@app.after_request
def add_cors(response):
    origin = request.headers.get("Origin", "null")
    if origin in ALLOWED_ORIGINS or not origin:
        response.headers["Access-Control-Allow-Origin"] = origin or "*"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    response.headers["Cache-Control"] = "no-cache"
    response.headers["X-Accel-Buffering"] = "no"
    return response


@app.route("/", defaults={"path": ""}, methods=["OPTIONS"])
@app.route("/<path:path>", methods=["OPTIONS"])
def options_handler(path=""):
    return "", 204


# ---------------------------------------------------------------------------
# SSE helpers
# ---------------------------------------------------------------------------

def sse(type_, line):
    return f"data: {json.dumps({'type': type_, 'line': line})}\n\n"


def sse_response(generator):
    return Response(
        stream_with_context(generator),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


def classify_line(line):
    s = line.strip()
    # Strip ANSI escape codes before prefix check
    s = re.sub(r'\033\[[0-9;]*m', '', s)
    if s.startswith("OK:"):
        return "ok"
    if s.startswith("ERROR:"):
        return "error"
    if s.startswith("WARNING:"):
        return "warning"
    if s.startswith("INFO:"):
        return "info"
    if s.startswith("QUIT:"):
        return "quit"
    return "normal"


# ---------------------------------------------------------------------------
# Static
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    ui = REPO_ROOT / "koet-ui.html"
    if not ui.exists():
        return "koet-ui.html not found", 404
    return send_file(str(ui))


# ---------------------------------------------------------------------------
# Hosts JSON
# ---------------------------------------------------------------------------

HOSTS_FILE = REPO_ROOT / "hosts.json"


def _valid_ip(ip):
    try:
        socket.inet_aton(ip.strip())
        return ip.strip().count(".") == 3
    except OSError:
        return False


@app.route("/api/hosts", methods=["GET"])
def get_hosts():
    try:
        data = json.loads(HOSTS_FILE.read_text()) if HOSTS_FILE.exists() else {}
        return jsonify(data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/hosts", methods=["POST"])
def save_hosts():
    body = request.get_json(force=True, silent=True) or {}
    # Accept either a dict {ip: role} or a list of IPs
    if isinstance(body, list):
        ips = body
        hosts = {ip: "ECE" for ip in ips}
    elif isinstance(body, dict):
        hosts = body
        ips = list(body.keys())
    else:
        return jsonify({"error": "body must be a JSON object or array"}), 400

    bad = [ip for ip in ips if not _valid_ip(str(ip))]
    if bad:
        return jsonify({"error": f"invalid IPs: {bad}"}), 400
    if not 2 <= len(ips) <= 64:
        return jsonify({"error": f"host count {len(ips)} must be between 2 and 64"}), 400

    try:
        HOSTS_FILE.write_text(json.dumps(hosts, indent=2))
        return jsonify({"ok": True, "hosts": hosts})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ---------------------------------------------------------------------------
# Run management
# ---------------------------------------------------------------------------

def _build_argv(cfg):
    argv = ["python3", "koet.py"]
    argv += ["-l", str(cfg.get("latency", 1.0))]
    argv += ["-c", str(cfg.get("fping_count", 500))]
    argv += ["-p", str(cfg.get("perf_runtime", 1200))]
    argv += ["-m", str(cfg.get("min_throughput", 2000))]
    if cfg.get("hosts", "").strip():
        argv += ["--hosts", cfg["hosts"].strip()]
    if cfg.get("rdma", "").strip():
        argv += ["--rdma", cfg["rdma"].strip()]
    if cfg.get("rpm_check_disabled"):
        argv.append("--rpm_check_disabled")
    if cfg.get("save_hosts"):
        argv.append("--save-hosts")
    return argv


@app.route("/api/run", methods=["POST"])
def api_run():
    with _run_lock:
        if _run_state["running"]:
            return jsonify({"error": "a test is already running"}), 409

        cfg = request.get_json(force=True, silent=True) or {}
        argv = _build_argv(cfg)

        try:
            proc = subprocess.Popen(
                argv,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                bufsize=0,
                cwd=str(REPO_ROOT),
            )
        except Exception as e:
            return jsonify({"error": str(e)}), 500

        _run_state.update({
            "running": True,
            "proc": proc,
            "log_dir": None,
            "returncode": None,
            "awaiting_confirm": False,
            "kpi": {
                "latency": cfg.get("latency", 1.0),
                "min_throughput": cfg.get("min_throughput", 2000),
            },
        })
        return jsonify({"ok": True, "argv": argv})


@app.route("/api/stream")
def api_stream():
    def generate():
        proc = _run_state.get("proc")
        if proc is None:
            yield sse("error", "no process running")
            yield sse("done", json.dumps({"returncode": None, "log_dir": None}))
            return

        for raw in iter(proc.stdout.readline, b""):
            line = raw.decode("utf-8", errors="replace").rstrip()
            if not line:
                continue

            # Detect log directory path emitted by koet.py
            if "log/" in line and _run_state["log_dir"] is None:
                m = re.search(r'log[/\\](\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2})', line)
                if m:
                    _run_state["log_dir"] = str(REPO_ROOT / "log" / m.group(1))

            # Detect interactive confirmation prompt
            if "Do you want to continue?" in line:
                _run_state["awaiting_confirm"] = True
                yield sse("prompt", line)
            else:
                yield sse(classify_line(line), line)

        proc.wait()
        with _run_lock:
            _run_state["running"] = False
            _run_state["returncode"] = proc.returncode

        yield sse("done", json.dumps({
            "returncode": proc.returncode,
            "log_dir": _run_state["log_dir"],
        }))

    return sse_response(generate())


@app.route("/api/confirm", methods=["POST"])
def api_confirm():
    answer = (request.get_json(force=True, silent=True) or {}).get("answer", "n")
    if answer not in ("y", "n"):
        return jsonify({"error": "answer must be 'y' or 'n'"}), 400

    proc = _run_state.get("proc")
    if proc is None or not _run_state.get("awaiting_confirm"):
        return jsonify({"error": "not awaiting confirmation"}), 400

    try:
        proc.stdin.write((answer + "\n").encode())
        proc.stdin.flush()
        _run_state["awaiting_confirm"] = False
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/stop", methods=["POST"])
def api_stop():
    proc = _run_state.get("proc")
    if proc is None:
        return jsonify({"error": "no process running"}), 400
    try:
        proc.send_signal(signal.SIGTERM)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/status")
def api_status():
    return jsonify({
        "running": _run_state["running"],
        "returncode": _run_state["returncode"],
        "log_dir": _run_state["log_dir"],
        "awaiting_confirm": _run_state["awaiting_confirm"],
    })


# ---------------------------------------------------------------------------
# Log history
# ---------------------------------------------------------------------------

@app.route("/api/logs")
def api_logs():
    log_base = REPO_ROOT / "log"
    if not log_base.exists():
        return jsonify([])
    dirs = sorted(
        [d.name for d in log_base.iterdir()
         if d.is_dir() and re.match(r'\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}', d.name)],
        reverse=True,
    )
    return jsonify(dirs)


# ---------------------------------------------------------------------------
# Results parsing
# ---------------------------------------------------------------------------

def _strip_ansi(s):
    return re.sub(r'\033\[[0-9;]*m', '', s)


def _parse_throughput(log_dir, kpi_mbps):
    csv_path = Path(log_dir) / "throughput.csv"
    hosts, values = [], []
    if csv_path.exists():
        with open(csv_path, newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                hosts.append(row.get("Host", ""))
                try:
                    values.append(float(row.get("Throughput MB/sec", 0)))
                except ValueError:
                    values.append(0.0)
    return {
        "hosts": hosts,
        "values_mbps": values,
        "kpi_mbps": kpi_mbps,
        "pass": [v >= kpi_mbps for v in values],
    }


def _parse_latency_file(filepath):
    """Parse a lat_<ip>_all fping output file.
    Each line: <dstip>: <v1> <v2> ... (or '-' for timeout)
    Returns dict per srchost: {dstip: [float latencies]}
    """
    results = {}
    try:
        with open(filepath) as f:
            for line in f:
                line = _strip_ansi(line).strip()
                if ":" not in line:
                    continue
                parts = line.split(":", 1)
                dst_ip = parts[0].strip()
                vals_raw = parts[1].strip().split()
                vals = []
                for v in vals_raw:
                    try:
                        vals.append(float(v.replace("-", "1000.0")))
                    except ValueError:
                        vals.append(1000.0)
                if vals:
                    results[dst_ip] = vals
    except OSError as e:
        app.logger.warning("cannot read latency file %s: %s", filepath, e)
    return results


def _parse_latency(log_dir, kpi_msec):
    log_path = Path(log_dir)
    lat_files = sorted(log_path.glob("lat_*_all"))

    src_hosts, means, maxs, mins, stddevs = [], [], [], [], []

    for lat_file in lat_files:
        # Extract source IP from filename: lat_<ip>_all
        name = lat_file.stem  # lat_10.0.0.1_all → need to strip prefix/suffix
        src_ip = name[4:-4] if name.startswith("lat_") and name.endswith("_all") else name

        per_dst = _parse_latency_file(lat_file)
        # exclude self-pings (srcip == dstip)
        all_vals = []
        for dst_ip, vals in per_dst.items():
            if dst_ip != src_ip:
                all_vals.extend(vals)

        if not all_vals:
            continue

        src_hosts.append(src_ip)
        m = sum(all_vals) / len(all_vals)
        means.append(round(m, 3))
        maxs.append(round(max(all_vals), 3))
        mins.append(round(min(all_vals), 3))
        try:
            sd = statistics.stdev(all_vals) if len(all_vals) > 1 else 0.0
        except statistics.StatisticsError:
            sd = 0.0
        stddevs.append(round(sd, 3))

    return {
        "hosts": src_hosts,
        "mean_msec": means,
        "max_msec": maxs,
        "min_msec": mins,
        "stddev_msec": stddevs,
        "kpi_msec": kpi_msec,
        "pass": [m < kpi_msec for m in means],
    }


def _parse_nsd_files(log_dir):
    log_path = Path(log_dir)
    nsd_hosts, nsd_means = [], []
    rx_errors, tx_errors, retransmits = {}, {}, {}

    for nsd_file in sorted(log_path.glob("nsd_*.json")):
        try:
            data = json.loads(nsd_file.read_text())
        except (OSError, json.JSONDecodeError) as e:
            app.logger.warning("cannot parse %s: %s", nsd_file, e)
            continue

        stem = nsd_file.stem  # nsd_10.0.0.1 or nsd_mess
        label = stem[4:] if stem.startswith("nsd_") else stem

        # NSD latency
        try:
            avg = float(data["networkDelay"][0]["average"])
            nsd_hosts.append(label)
            nsd_means.append(round(avg, 3))
        except (KeyError, IndexError, TypeError, ValueError):
            pass

        # Network errors
        net_data = data.get("netData", {})
        for host, stats in net_data.items():
            try:
                rx_errors[host] = rx_errors.get(host, 0) + int(stats.get("rxErrors", 0))
                tx_errors[host] = tx_errors.get(host, 0) + int(stats.get("txErrors", 0))
                retransmits[host] = retransmits.get(host, 0) + int(stats.get("retransmit", 0))
            except (TypeError, ValueError):
                pass

    return (
        {"hosts": nsd_hosts, "mean_msec": nsd_means},
        {"rx": rx_errors, "tx": tx_errors, "retransmit": retransmits},
    )


@app.route("/api/results")
def api_results():
    log_dir_param = request.args.get("log_dir", "").strip()
    if log_dir_param:
        # Strip any path separators to constrain to the log/ directory
        bare = Path(log_dir_param).name
        p = REPO_ROOT / "log" / bare
        log_dir = str(p)
    else:
        log_dir = _run_state.get("log_dir")

    if not log_dir or not Path(log_dir).is_dir():
        return jsonify({"error": f"log directory not found: {log_dir}"}), 404

    kpi = _run_state.get("kpi", {})
    kpi_mbps = float(kpi.get("min_throughput", 2000))
    kpi_msec = float(kpi.get("latency", 1.0))

    throughput = _parse_throughput(log_dir, kpi_mbps)
    latency = _parse_latency(log_dir, kpi_msec)
    nsd_latency, errors = _parse_nsd_files(log_dir)

    total_errors = (
        sum(throughput["pass"].count(False) if throughput["pass"] else []) +
        latency["pass"].count(False)
    )
    passed = total_errors == 0 and (bool(throughput["hosts"]) or bool(latency["hosts"]))

    return jsonify({
        "log_dir": log_dir,
        "throughput": throughput,
        "latency": latency,
        "nsd_latency": nsd_latency,
        "errors": errors,
        "summary": {"total_errors": total_errors, "passed": passed},
    })


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print(f"KOET UI backend — http://{HOST}:{PORT}")
    print(f"Repo root: {REPO_ROOT}")
    app.run(host=HOST, port=PORT, debug=False, threaded=True)
