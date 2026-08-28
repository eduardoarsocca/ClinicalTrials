"""
main.py — Interface de linha de comando para busca no ClinicalTrials.gov
=========================================================================
Uso:
    python main.py

O script pergunta interativamente os parâmetros de busca e executa o ETL.
Você também pode passar argumentos direto pela linha de comando (ver --help).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from client import (
    ClinicalTrialsClient,
    DEFAULT_FIELDS,
    load_to_csv,
    load_to_json,
    run_etl,
    transform_studies,
)


# ---------------------------------------------------------------------------
# Helpers de UI
# ---------------------------------------------------------------------------

def _ask(prompt: str, default: str = "") -> str:
    """Lê input do usuário; retorna default se vazio."""
    suffix = f" [{default}]" if default else ""
    value = input(f"{prompt}{suffix}: ").strip()
    return value if value else default


def _ask_list(prompt: str) -> list[str] | None:
    """Lê uma lista separada por vírgulas; retorna None se vazio."""
    value = input(f"{prompt} (vírgula p/ múltiplos, Enter p/ pular): ").strip()
    if not value:
        return None
    return [v.strip() for v in value.split(",") if v.strip()]


def _section(title: str) -> None:
    print(f"\n{'─'*60}")
    print(f"  {title}")
    print('─'*60)


# ---------------------------------------------------------------------------
# Modo interativo
# ---------------------------------------------------------------------------

def interactive_mode() -> None:
    print("\n" + "="*60)
    print("  ClinicalTrials.gov — Extrator de Dados (API v2)")
    print("="*60)

    # ---- Verificar versão da API ----------------------------------------
    client = ClinicalTrialsClient()
    try:
        version = client.get_version()
        print(f"\n✔  API v{version.get('apiVersion')}  |  Dados atualizados em: {version.get('dataTimestamp')}")
    except Exception as e:
        print(f"\n⚠  Não foi possível verificar a versão da API: {e}")

    # ---- Parâmetros de busca -------------------------------------------
    _section("1. PARÂMETROS DE BUSCA")

    query_cond   = _ask("Condição / doença (query.cond)   ex: lung cancer")
    query_intr   = _ask("Intervenção / tratamento (query.intr)")
    query_spons  = _ask("Patrocinador (query.spons)")
    query_lead   = _ask("Lead sponsor name (query.lead)")
    query_titles = _ask("Título / acrônimo (query.titles)")
    query_term   = _ask("Termos gerais (query.term)   ex: AREA[LastUpdatePostDate]RANGE[2023-01-01,MAX]")
    query_id     = _ask("IDs de estudo (query.id)   ex: NCT04852770")

    # ---- Filtros -------------------------------------------------------
    _section("2. FILTROS")

    print("  Status disponíveis: RECRUITING, COMPLETED, NOT_YET_RECRUITING,")
    print("  ACTIVE_NOT_RECRUITING, TERMINATED, SUSPENDED, WITHDRAWN")
    raw_status = _ask_list("Status (filter.overallStatus)")
    filter_status = [s.upper() for s in raw_status] if raw_status else None

    filter_ids_input = _ask_list("NCT IDs específicos (filter.ids)")
    filter_advanced  = _ask("Filtro avançado Essie (filter.advanced)   ex: AREA[StartDate]2022")
    filter_geo       = _ask("Filtro geográfico (filter.geo)   ex: distance(-23.55,-46.63,50km)")

    # ---- Campos e ordenação -------------------------------------------
    _section("3. CAMPOS E ORDENAÇÃO")

    print("  Campos padrão:", ", ".join(DEFAULT_FIELDS))
    custom_fields_raw = _ask_list("Campos customizados (deixe vazio para usar os padrão)")
    fields = custom_fields_raw if custom_fields_raw else DEFAULT_FIELDS

    sort_raw = _ask("Ordenação (ex: LastUpdatePostDate | EnrollmentCount:desc)")
    sort = [s.strip() for s in sort_raw.split(",") if s.strip()] if sort_raw else None

    # ---- Limites e saída -----------------------------------------------
    _section("4. SAÍDA")

    max_studies_raw = _ask("Máximo de estudos a extrair (Enter = todos)", "")
    max_studies = int(max_studies_raw) if max_studies_raw.isdigit() else None

    output_format = _ask("Formato de saída", "csv").lower()
    while output_format not in ("csv", "json"):
        output_format = _ask("Formato inválido. Digite 'csv' ou 'json'", "csv").lower()

    default_filename = f"results.{output_format}"
    output_path = _ask("Caminho do arquivo de saída", default_filename)

    # ---- Confirmar e executar ------------------------------------------
    _section("5. RESUMO DA BUSCA")
    params_summary = {
        "query.cond":            query_cond   or "—",
        "query.intr":            query_intr   or "—",
        "query.spons":           query_spons  or "—",
        "query.lead":            query_lead   or "—",
        "query.titles":          query_titles or "—",
        "query.term":            query_term   or "—",
        "query.id":              query_id     or "—",
        "filter.overallStatus": str(filter_status) if filter_status else "—",
        "filter.ids":           str(filter_ids_input) if filter_ids_input else "—",
        "filter.advanced":       filter_advanced or "—",
        "filter.geo":            filter_geo   or "—",
        "fields":               ", ".join(fields),
        "sort":                 str(sort) if sort else "—",
        "max_studies":          str(max_studies) if max_studies else "todos",
        "output_format":        output_format,
        "output_path":          output_path,
    }
    for k, v in params_summary.items():
        print(f"  {k:<26}: {v}")

    confirm = input("\n  Confirmar e iniciar extração? [S/n]: ").strip().lower()
    if confirm in ("n", "nao", "não", "no"):
        print("  Operação cancelada.")
        sys.exit(0)

    # ---- ETL -----------------------------------------------------------
    print()
    run_etl(
        output_path=output_path,
        output_format=output_format,
        max_studies=max_studies,
        fields=fields,
        query_cond=query_cond   or None,
        query_intr=query_intr   or None,
        query_spons=query_spons  or None,
        query_lead=query_lead   or None,
        query_titles=query_titles or None,
        query_term=query_term   or None,
        query_id=query_id     or None,
        filter_overall_status=filter_status,
        filter_ids=filter_ids_input,
        filter_advanced=filter_advanced or None,
        filter_geo=filter_geo   or None,
        sort=sort,
    )

    print(f"\n✔  Concluído! Arquivo salvo em: {Path(output_path).resolve()}")


# ---------------------------------------------------------------------------
# Modo CLI (argumentos)
# ---------------------------------------------------------------------------

def cli_mode() -> None:
    parser = argparse.ArgumentParser(
        prog="main.py",
        description="Extrator de dados do ClinicalTrials.gov via API v2.",
        formatter_class=argparse.RawTextHelpFormatter,
    )

    # queries
    parser.add_argument("--cond",    metavar="TEXTO",  help="Condição / doença")
    parser.add_argument("--intr",    metavar="TEXTO",  help="Intervenção / tratamento")
    parser.add_argument("--spons",   metavar="TEXTO",  help="Patrocinador")
    parser.add_argument("--lead",    metavar="TEXTO",  help="Lead sponsor name")
    parser.add_argument("--titles",  metavar="TEXTO",  help="Título / acrônimo")
    parser.add_argument("--term",    metavar="TEXTO",  help="Termos gerais (Essie)")
    parser.add_argument("--id",      metavar="NCTID",  help="IDs de estudo")

    # filters
    parser.add_argument(
        "--status",
        metavar="STATUS",
        nargs="+",
        help="Status (ex: --status RECRUITING COMPLETED)",
    )
    parser.add_argument(
        "--ids",
        metavar="NCT",
        nargs="+",
        help="NCT IDs específicos (ex: --ids NCT04852770 NCT01728545)",
    )
    parser.add_argument("--advanced", metavar="QUERY",  help="Filtro avançado Essie")
    parser.add_argument("--geo",      metavar="GEO",    help="Filtro geográfico (ex: distance(-23.55,-46.63,50km))")

    # output
    parser.add_argument("--fields",  metavar="F", nargs="+", help="Campos a retornar (padrão: veja DEFAULT_FIELDS em client.py)")
    parser.add_argument("--sort",    metavar="S", nargs="+", help="Ordenação (ex: --sort LastUpdatePostDate)")
    parser.add_argument("--max",     metavar="N",  type=int,  help="Máximo de estudos")
    parser.add_argument("--format",  metavar="FMT", default="csv", choices=["csv", "json"], help="Formato de saída: csv | json (padrão: csv)")
    parser.add_argument("--out",     metavar="PATH", default="results.csv", help="Caminho do arquivo de saída (padrão: results.csv)")

    # estudo único
    parser.add_argument("--nct",  metavar="NCT_ID",  help="Retorna dados de um único estudo pelo NCT ID")

    args = parser.parse_args()

    # Consulta de estudo único
    if args.nct:
        client = ClinicalTrialsClient()
        study = client.get_study(args.nct, fields=args.fields)
        print(study)
        return

    # Se nenhum argumento de busca foi passado → modo interativo
    has_search = any([
        args.cond, args.intr, args.spons, args.lead,
        args.titles, args.term, args.id,
        args.status, args.ids, args.advanced, args.geo,
    ])
    if not has_search:
        interactive_mode()
        return

    # ETL direto por CLI
    output_path = args.out if args.out != "results.csv" else f"results.{args.format}"

    run_etl(
        output_path=output_path,
        output_format=args.format,
        max_studies=args.max,
        fields=args.fields or DEFAULT_FIELDS,
        query_cond=args.cond,
        query_intr=args.intr,
        query_spons=args.spons,
        query_lead=args.lead,
        query_titles=args.titles,
        query_term=args.term,
        query_id=args.id,
        filter_overall_status=args.status,
        filter_ids=args.ids,
        filter_advanced=args.advanced,
        filter_geo=args.geo,
        sort=args.sort,
    )

    print(f"\n✔  Arquivo salvo em: {Path(output_path).resolve()}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    cli_mode()
