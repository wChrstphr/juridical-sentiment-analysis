#!/usr/bin/env python3
"""
Executa todos os scrapers sequencialmente (um por um) com retry automático para timeout.
Permite rastreamento detalhado de logs individuais.
"""

import subprocess
import json
import time
import sys
import os
import argparse
from pathlib import Path
from datetime import datetime

def resolve_script(tribunal: str) -> Path | None:
    """Resolve o scraper principal do tribunal pela pasta, sem depender do nome do arquivo."""
    tribunal_dir = Path(tribunal)
    if not tribunal_dir.exists() or not tribunal_dir.is_dir():
        return None

    candidates = sorted(
        p for p in tribunal_dir.glob("scraper_pdf_*.py")
        if "playwright_test" not in p.name.lower()
    )
    return candidates[0] if candidates else None


def run_scraper(tribunal: str, max_retries: int = 3, timeout_sec: int = 900) -> dict:
    """
    Executa um scraper com retry automático para timeout.
    
    Args:
        tribunal: Nome do tribunal (ex: 'tjsp')
        max_retries: Quantidade de tentativas se houver timeout
        timeout_sec: Timeout em segundos por tentativa
    
    Returns:
        dict com resultado da execução
    """
    script = resolve_script(tribunal)

    if not script:
        return {
            "tribunal": tribunal,
            "status": "script_not_found",
            "script": f"{tribunal}/scraper_pdf_*.py",
            "attempts": 0
        }

    for attempt in range(1, max_retries + 1):
        attempt_timeout = timeout_sec * attempt
        print(f"\n{'='*70}")
        print(f"[{tribunal.upper()}] Tentativa {attempt}/{max_retries}")
        print(f"Script: {script}")
        print(f"Timeout: {attempt_timeout}s")
        print(f"{'='*70}\n")

        start_time = time.time()

        env = os.environ.copy()
        env.setdefault("SCRAPER_NON_INTERACTIVE", "1")
        env.setdefault("GOOGLE_CHROME_BIN", "/snap/bin/chromium")

        run_cfgs = [
            {
                "cmd": ["python", str(script)],
                "cwd": str(Path.cwd()),
            },
            {
                "cmd": ["python", script.name],
                "cwd": str(script.parent),
            },
        ]

        last_return_code = None
        succeeded = False
        try:
            for idx, cfg in enumerate(run_cfgs, 1):
                if idx == 2:
                    print("   Tentando fallback com cwd da pasta do tribunal...")

                result = subprocess.run(
                    cfg["cmd"],
                    cwd=cfg["cwd"],
                    capture_output=False,
                    timeout=attempt_timeout,
                    text=True,
                    input="s\n\n\n",
                    env=env,
                )
                last_return_code = result.returncode

                if result.returncode == 0:
                    succeeded = True
                    break

            duration = time.time() - start_time

            if succeeded:
                print(f"\n✅ {tribunal.upper()} SUCESSO (tentativa {attempt}, {duration:.1f}s)")
                return {
                    "tribunal": tribunal,
                    "status": "success",
                    "script": str(script),
                    "return_code": 0,
                    "duration_sec": duration,
                    "attempts": attempt
                }

            print(f"\n⚠️  {tribunal.upper()} erro com código {last_return_code} (tentativa {attempt}, {duration:.1f}s)")
            if attempt < max_retries:
                print("   Reenviando em 5s...")
                time.sleep(5)
            else:
                return {
                    "tribunal": tribunal,
                    "status": "error",
                    "script": str(script),
                    "return_code": last_return_code,
                    "duration_sec": duration,
                    "attempts": attempt
                }

        except subprocess.TimeoutExpired:
            duration = time.time() - start_time
            print(f"\n⏱️  {tribunal.upper()} TIMEOUT após {duration:.1f}s (tentativa {attempt}/{max_retries})")
            if attempt < max_retries:
                print(f"   Reenviando em 10s...")
                time.sleep(10)
            else:
                return {
                    "tribunal": tribunal,
                    "status": "timeout",
                    "script": str(script),
                    "return_code": -9,
                    "duration_sec": duration,
                    "attempts": attempt
                }
    
    return {
        "tribunal": tribunal,
        "status": "failed_all_attempts",
        "script": str(script),
        "attempts": max_retries
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Executa scrapers sequencialmente com retry e fallback de cwd.")
    parser.add_argument("--only", default="", help="Lista separada por vírgula de tribunais para rodar.")
    parser.add_argument("--timeout", type=int, default=900, help="Timeout base por tentativa em segundos.")
    parser.add_argument("--retries", type=int, default=3, help="Número máximo de tentativas por tribunal.")
    return parser.parse_args()


def main():
    args = parse_args()

    tribunals = [
        "tjac", "tjal", "tjam", "tjba", "tjce", "tjdf", "tjes", "tjgo",
        "tjma", "tjms", "tjpb", "tjpe", "tjrj", "tjrs", "tjsc", "tjsp", "tjto"
    ]

    if args.only:
        only_set = {t.strip() for t in args.only.split(",") if t.strip()}
        tribunals = [t for t in tribunals if t in only_set]
    
    results = []
    start_total = time.time()
    
    print(f"\n{'#'*70}")
    print(f"# EXECUÇÃO SEQUENCIAL DOS SCRAPERS - {datetime.now().isoformat()}")
    print(f"# Total de tribunais: {len(tribunals)}")
    print(f"{'#'*70}\n")
    
    for i, tribunal in enumerate(tribunals, 1):
        print(f"\n[{i}/{len(tribunals)}] Iniciando {tribunal.upper()}...")
        result = run_scraper(tribunal, max_retries=args.retries, timeout_sec=args.timeout)
        results.append(result)
        print(f"[{i}/{len(tribunals)}] {tribunal.upper()} -> {result['status'].upper()}")
    
    total_duration = time.time() - start_total
    
    # Resumo final
    print(f"\n{'='*70}")
    print(f"RESUMO FINAL")
    print(f"{'='*70}\n")
    
    status_counts = {}
    for r in results:
        status = r["status"]
        status_counts[status] = status_counts.get(status, 0) + 1
    
    for status, count in sorted(status_counts.items()):
        print(f"  {status}: {count}")
    
    print(f"\nDuração total: {total_duration/60:.1f} minutos\n")
    
    # Salvar relatório JSON
    report = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "total_tribunals": len(tribunals),
        "total_duration_sec": total_duration,
        "status_count": status_counts,
        "results": results
    }
    
    report_path = (Path.cwd() / "logs" / "scraper_check" / f"report_sequential_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    
    print(f"Relatório: {report_path}")
    
    # Retornar código de sucesso só se nenhum falhou
    failed = sum(1 for r in results if r["status"] not in ["success"])
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
