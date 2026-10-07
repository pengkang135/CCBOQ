"""Bridge to CostSpread search API via docker exec.

Provides costspread_search() that calls the CostSpread backend's
/api/rates/search endpoint, which uses search-dictionary.js for
bilingual query expansion + weighted field scoring (name=100,
synonym=60, name_en=30, features=15, searchText=5).

Requires: costspread-backend-1 Docker container running.
"""

import json
import subprocess
import sys

NODE_SCRIPT = r"""
const http = require('http');
const q = process.argv[1];
const country = process.argv[2] || '';
const pageSize = parseInt(process.argv[3]) || 40;

let url = 'http://localhost:3000/api/rates/search?query=' + encodeURIComponent(q) + '&pageSize=' + pageSize;
if (country) url += '&country=' + encodeURIComponent(country);

http.get(url, res => {
  let d = '';
  res.on('data', c => d += c);
  res.on('end', () => {
    try {
      const r = JSON.parse(d);
      console.log(JSON.stringify({ok: true, total: r.total, results: r.results}));
    } catch(e) {
      console.log(JSON.stringify({ok: false, error: e.message, raw: d.slice(0, 200)}));
    }
  });
}).on('error', e => {
  console.log(JSON.stringify({ok: false, error: e.message}));
});
"""


def costspread_search(query, country="泰国", page_size=40, timeout=15):
    """Search CostSpread rates database via the backend API.

    Args:
        query: Search query string (short keywords work best, 1-3 words).
               Supports both English and Chinese.
        country: Filter by country (default "泰国").
        page_size: Max results to return (default 40).
        timeout: HTTP timeout in seconds (default 15).

    Returns:
        dict with keys: ok, total, results (list of rate dicts), error (if failed)
    """
    node_script = NODE_SCRIPT.strip()
    cmd = [
        "docker", "exec", "costspread-backend-1",
        "node", "-e", node_script,
        query, country, str(page_size)
    ]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding='utf-8',
        )
        if result.returncode != 0:
            return {"ok": False, "error": f"docker exec failed: {result.stderr.strip()}"}
        output = result.stdout.strip()
        if not output:
            return {"ok": False, "error": "empty output"}
        return json.loads(output)
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"timeout after {timeout}s"}
    except json.JSONDecodeError as e:
        return {"ok": False, "error": f"JSON parse error: {e}", "raw": result.stdout[:200] if 'result' in dir() else ''}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def costspread_search_multi(queries, country="泰国", page_size=30, timeout=15):
    """Search with multiple queries and merge/dedup results.

    Args:
        queries: List of query strings to try.
        country: Country filter.
        page_size: Max results per query.
        timeout: Timeout per query.

    Returns:
        List of unique rate dicts, sorted by best match score (descending).
    """
    seen_ids = set()
    merged = []
    for q in queries:
        r = costspread_search(q, country=country, page_size=page_size, timeout=timeout)
        if r.get("ok") and r.get("results"):
            for item in r["results"]:
                rid = str(item.get("_id", ""))
                if rid and rid not in seen_ids:
                    seen_ids.add(rid)
                    merged.append(item)
    return merged


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python costspread_search.py <query> [country] [page_size]")
        sys.exit(1)
    q = sys.argv[1]
    country = sys.argv[2] if len(sys.argv) > 2 else "泰国"
    page_size = int(sys.argv[3]) if len(sys.argv) > 3 else 10
    result = costspread_search(q, country=country, page_size=page_size)
    if result.get("ok"):
        print(f"Total: {result['total']}")
        for i, item in enumerate(result.get("results", [])):
            name = item.get("name", "")[:80]
            price = item.get("price_incl_tax", "?")
            unit = item.get("unit", "?")
            print(f"  {i+1}. {name} | {price} THB / {unit}")
    else:
        print(f"Error: {result.get('error', 'unknown')}")
