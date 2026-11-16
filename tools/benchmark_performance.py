"""Repeatable local hot-path benchmark. Uses only a disposable SQLite database.

Run from the repository root: .venv/Scripts/python tools/benchmark_performance.py
Add --baseline-head to time the pre-edit methods from the current Git HEAD.
Use --baseline-ref COMMIT to keep the comparison reproducible after committing.
Numbers measure individual operations, not end-to-end Telegram latency.
"""

import asyncio
import ast
import argparse
import json
import statistics
import sys
import subprocess
import tempfile
import time
from dataclasses import asdict
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from arena_assets import render_arena_index
from arena_engine import FIGHTER_CLASSES
from arena_web import battle_view, menu_view
from database import Database


def measure(call, repeats):
    call()
    samples = []
    for _ in range(repeats):
        start = time.perf_counter()
        call()
        samples.append((time.perf_counter() - start) * 1000)
    return {"median_ms": round(statistics.median(samples), 4), "runs": repeats}


async def measure_async(call, repeats):
    await call()
    samples = []
    for _ in range(repeats):
        start = time.perf_counter()
        await call()
        samples.append((time.perf_counter() - start) * 1000)
    return {"median_ms": round(statistics.median(samples), 4), "runs": repeats}


async def main():
    result = {"arena_index": measure(lambda: render_arena_index(ROOT / "webapp"), 100)}
    with tempfile.TemporaryDirectory(prefix="gnida-perf-") as directory:
        db = Database(Path(directory) / "benchmark.sqlite3")
        await db.connect()
        try:
            await db.upsert_chat(-100, "Benchmark")
            await db.upsert_user(-100, 10, "tester", "Tester")
            battle = await db.arena_wasteland(-100, 10, 10, personal=True)
            result["battle_snapshot_builtin"] = await measure_async(
                lambda: battle_view(db, battle, 10), 50
            )
            result["menu_builtin"] = await measure_async(lambda: menu_view(db, -100, 10), 10)
            class_payload = asdict(FIGHTER_CLASSES["ragamuffin"])
            class_payload["passives"] = list(class_payload["passives"])
            for index in range(40):
                class_id = f"perf_class_{index}"
                db.connection.execute(
                    "INSERT INTO custom_fighter_classes(class_id,name,definition_json,created_by,created_at,hidden) VALUES(?,?,?,10,0,0)",
                    (class_id, class_id, json.dumps(class_payload)),
                )
            for index in range(400):
                payload = dict(name=f"Skill {index}", class_id=f"perf_class_{index % 40}",
                               merchant_available=True, damage_type="magic", power=12, cost=10,
                               effects=[dict(kind="bleed", value=2, turns=3)])
                db.connection.execute(
                    "INSERT INTO custom_fighter_skills(skill_id,name,definition_json,created_by,created_at) VALUES(?,?,?,10,0)",
                    (f"perf_skill_{index}", payload["name"], json.dumps(payload)),
                )
            db.connection.commit()
            result["catalog_40_classes_400_skills"] = measure(db._fighter_catalog_locked, 200)
            result["battle_snapshot_custom"] = await measure_async(
                lambda: battle_view(db, battle, 10), 50
            )
            result["menu_custom"] = await measure_async(lambda: menu_view(db, -100, 10), 5)
            db.connection.executemany(
                "INSERT INTO businesses(chat_id,owner_id,business_type,created_at,last_accrued) VALUES(?,?,'field',0,0)",
                ((-100 - index // 100, 1000 + index) for index in range(10000)),
            )
            db.connection.executemany(
                "INSERT INTO business_workers(chat_id,owner_id,worker_id,role,assigned_at) VALUES(?,?,?,'worker',0)",
                ((-100 - index // 100, 1000 + index, 20000 + index * 4 + worker)
                 for index in range(10000) for worker in range(4)),
            )
            db.connection.commit()
            # Isolate discovery cost; do not simulate or time economic rewards.
            with patch.object(db, "_settle_business_locked", return_value=None):
                result["message_business_lookup_nonowner"] = await measure_async(
                    lambda: db.settle_businesses_for_user(99999999), 100
                )
                result["message_business_lookup_worker"] = await measure_async(
                    lambda: db.settle_businesses_for_user(20000), 100
                )
        finally:
            await db.close()
    print(json.dumps(result, indent=2))


def head_function(path, class_name, name, namespace, ref="HEAD"):
    """Load only a requested function definition; never switch or edit files."""
    source = subprocess.check_output(["git", "show", f"{ref}:{path}"], cwd=ROOT).decode("utf-8")
    tree = ast.parse(source)
    body = next(node.body for node in tree.body if isinstance(node, ast.ClassDef) and node.name == class_name) if class_name else tree.body
    function = next(node for node in body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name)
    scope = dict(namespace)
    exec(compile(ast.Module(body=[function], type_ignores=[]), f"{ref}:{path}", "exec"), scope)
    return scope[name]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    baseline = parser.add_mutually_exclusive_group()
    baseline.add_argument("--baseline-head", action="store_true")
    baseline.add_argument("--baseline-ref")
    args = parser.parse_args()
    ref = args.baseline_ref or ("HEAD" if args.baseline_head else None)
    if ref:
        import arena_assets
        import arena_modules
        import arena_store
        import database
        with ExitStack() as stack:
            for module, cls, name in (
                (arena_store, "ArenaMixin", "_fighter_catalog_locked"),
                (arena_modules, "ClassModulesMixin", "_arena_class_enabled_locked"),
                (arena_modules, "ClassModulesMixin", "_arena_content_enabled_locked"),
                (database, "Database", "settle_businesses_for_user"),
            ):
                old = head_function(module.__name__ + ".py", cls, name, vars(module), ref)
                stack.enter_context(patch.object(getattr(module, cls), name, old))
            render_arena_index = head_function("arena_assets.py", None, "render_arena_index", vars(arena_assets), ref)
            asyncio.run(main())
    else:
        asyncio.run(main())
