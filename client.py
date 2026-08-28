"""
client.py — ClinicalTrials.gov API v2 | Camada ETL
=====================================================
Responsabilidades:
  - Extract  : requisições HTTP à API (com paginação automática)
  - Transform : normalização / achatamento dos dados JSON
  - Load      : exportação para CSV, JSON ou DataFrame (pandas)

Base URL: https://clinicaltrials.gov/api/v2
Autenticação: não necessária
"""

from __future__ import annotations

import csv
import json
import logging
import time
from pathlib import Path
from typing import Any, Generator, Optional

import requests

# ---------------------------------------------------------------------------
# Configuração
# ---------------------------------------------------------------------------

BASE_URL = "https://clinicaltrials.gov/api/v2"
DEFAULT_PAGE_SIZE = 100          # máximo suportado pela API: 1 000
DEFAULT_FIELDS = [
    "NCTId",
    "BriefTitle",
    "OverallStatus",
    "Phase",
    "Condition",
    "InterventionName",
    "LeadSponsorName",
    "StartDate",
    "PrimaryCompletionDate",
    "EnrollmentCount",
    "StudyType",
    "HasResults",
]

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)


# ---------------------------------------------------------------------------
# EXTRACT
# ---------------------------------------------------------------------------

class ClinicalTrialsClient:
    """Cliente HTTP para a API do ClinicalTrials.gov (v2)."""

    def __init__(self, page_size: int = DEFAULT_PAGE_SIZE, sleep_between_pages: float = 0.3):
        self.page_size = page_size
        self.sleep_between_pages = sleep_between_pages
        self.session = requests.Session()
        self.session.headers.update({"Accept": "application/json"})

    # ------------------------------------------------------------------
    # Primitiva: busca uma página
    # ------------------------------------------------------------------

    def _fetch_page(
        self,
        params: dict[str, Any],
        page_token: Optional[str] = None,
    ) -> dict[str, Any]:
        """Faz GET /studies e retorna o JSON bruto de uma página."""
        request_params = {**params}
        if page_token:
            request_params["pageToken"] = page_token

        response = self.session.get(f"{BASE_URL}/studies", params=request_params, timeout=30)
        response.raise_for_status()
        return response.json()

    # ------------------------------------------------------------------
    # Iterador de todas as páginas (paginação automática)
    # ------------------------------------------------------------------

    def iter_studies(
        self,
        query_cond: Optional[str] = None,
        query_term: Optional[str] = None,
        query_intr: Optional[str] = None,
        query_titles: Optional[str] = None,
        query_spons: Optional[str] = None,
        query_lead: Optional[str] = None,
        query_id: Optional[str] = None,
        filter_overall_status: Optional[list[str]] = None,
        filter_ids: Optional[list[str]] = None,
        filter_advanced: Optional[str] = None,
        filter_geo: Optional[str] = None,
        fields: Optional[list[str]] = None,
        sort: Optional[list[str]] = None,
        max_studies: Optional[int] = None,
    ) -> Generator[dict[str, Any], None, None]:
        """
        Itera sobre todos os estudos que correspondem aos parâmetros.
        Faz paginação automática até esgotar os resultados ou atingir max_studies.

        Yields
        ------
        dict
            Objeto JSON bruto de cada estudo (campo 'studies' da API).
        """
        params: dict[str, Any] = {"pageSize": self.page_size, "format": "json"}

        if query_cond:                   params["query.cond"]          = query_cond
        if query_term:                   params["query.term"]          = query_term
        if query_intr:                   params["query.intr"]          = query_intr
        if query_titles:                 params["query.titles"]        = query_titles
        if query_spons:                  params["query.spons"]         = query_spons
        if query_lead:                   params["query.lead"]          = query_lead
        if query_id:                     params["query.id"]            = query_id
        if filter_overall_status:        params["filter.overallStatus"]= ",".join(filter_overall_status)
        if filter_ids:                   params["filter.ids"]          = ",".join(filter_ids)
        if filter_advanced:              params["filter.advanced"]     = filter_advanced
        if filter_geo:                   params["filter.geo"]          = filter_geo
        if fields:                       params["fields"]              = ",".join(fields)
        if sort:                         params["sort"]                = ",".join(sort)

        total_yielded = 0
        page_token: Optional[str] = None
        page_num = 1

        while True:
            logger.info("Buscando página %d ...", page_num)
            data = self._fetch_page(params, page_token)

            studies = data.get("studies", [])
            for study in studies:
                if max_studies and total_yielded >= max_studies:
                    return
                yield study
                total_yielded += 1

            page_token = data.get("nextPageToken")
            if not page_token:
                break

            page_num += 1
            time.sleep(self.sleep_between_pages)

        logger.info("Extração concluída. Total de estudos: %d", total_yielded)

    # ------------------------------------------------------------------
    # Busca de estudo único por NCT ID
    # ------------------------------------------------------------------

    def get_study(self, nct_id: str, fields: Optional[list[str]] = None) -> dict[str, Any]:
        """Retorna o JSON completo de um estudo específico pelo NCT ID."""
        params: dict[str, Any] = {"format": "json"}
        if fields:
            params["fields"] = ",".join(fields)

        response = self.session.get(f"{BASE_URL}/studies/{nct_id}", params=params, timeout=30)
        response.raise_for_status()
        return response.json()

    # ------------------------------------------------------------------
    # Versão da API / timestamp dos dados
    # ------------------------------------------------------------------

    def get_version(self) -> dict[str, str]:
        """Retorna versão da API e timestamp da última atualização dos dados."""
        response = self.session.get(f"{BASE_URL}/version", timeout=10)
        response.raise_for_status()
        return response.json()


# ---------------------------------------------------------------------------
# TRANSFORM
# ---------------------------------------------------------------------------

def flatten_study(study: dict[str, Any]) -> dict[str, Any]:
    """
    Achata o objeto JSON de um estudo em um dicionário plano,
    adequado para exportação tabular (CSV / DataFrame).
    """
    proto = study.get("protocolSection", {})
    id_mod    = proto.get("identificationModule",  {})
    status_mod= proto.get("statusModule",          {})
    desc_mod  = proto.get("descriptionModule",     {})
    design_mod= proto.get("designModule",          {})
    enroll_mod= design_mod.get("enrollmentInfo",   {})
    sponsor_mod=proto.get("sponsorCollaboratorsModule", {})
    lead      = sponsor_mod.get("leadSponsor",     {})
    arms_mod  = proto.get("armsInterventionsModule", {})
    cond_mod  = proto.get("conditionsModule",      {})
    elig_mod  = proto.get("eligibilityModule",     {})
    contacts  = proto.get("contactsLocationsModule", {})

    # intervenções: pega o nome da primeira, ou todas separadas por ";"
    interventions = arms_mod.get("interventions", [])
    intervention_names = ";".join(
        i.get("name", "") for i in interventions
    ) if interventions else ""

    conditions = ";".join(cond_mod.get("conditions", []))

    # fases
    phases = ";".join(design_mod.get("phases", []))

    flat = {
        "nct_id":                   id_mod.get("nctId", ""),
        "brief_title":              id_mod.get("briefTitle", ""),
        "official_title":           id_mod.get("officialTitle", ""),
        "acronym":                  id_mod.get("acronym", ""),
        "overall_status":           status_mod.get("overallStatus", ""),
        "start_date":               status_mod.get("startDateStruct", {}).get("date", ""),
        "primary_completion_date":  status_mod.get("primaryCompletionDateStruct", {}).get("date", ""),
        "completion_date":          status_mod.get("completionDateStruct", {}).get("date", ""),
        "study_type":               design_mod.get("studyType", ""),
        "phases":                   phases,
        "enrollment_count":         enroll_mod.get("count", ""),
        "enrollment_type":          enroll_mod.get("type", ""),
        "conditions":               conditions,
        "intervention_names":       intervention_names,
        "lead_sponsor_name":        lead.get("name", ""),
        "lead_sponsor_class":       lead.get("class", ""),
        "minimum_age":              elig_mod.get("minimumAge", ""),
        "maximum_age":              elig_mod.get("maximumAge", ""),
        "sex":                      elig_mod.get("sex", ""),
        "healthy_volunteers":       elig_mod.get("healthyVolunteers", ""),
        "brief_summary":            desc_mod.get("briefSummary", ""),
        "has_results":              study.get("hasResults", False),
    }
    return flat


def transform_studies(studies: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Aplica flatten_study a uma lista de estudos."""
    return [flatten_study(s) for s in studies]


# ---------------------------------------------------------------------------
# LOAD
# ---------------------------------------------------------------------------

def load_to_csv(records: list[dict[str, Any]], output_path: str | Path) -> None:
    """Salva lista de registros achatados em um arquivo CSV."""
    if not records:
        logger.warning("Nenhum registro para salvar.")
        return

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    fieldnames = list(records[0].keys())
    with output_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(records)

    logger.info("CSV salvo em: %s  (%d linhas)", output_path, len(records))


def load_to_json(records: list[dict[str, Any]], output_path: str | Path) -> None:
    """Salva lista de registros em um arquivo JSON."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with output_path.open("w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)

    logger.info("JSON salvo em: %s  (%d registros)", output_path, len(records))


def load_to_dataframe(records: list[dict[str, Any]]):
    """Retorna um pandas DataFrame a partir dos registros achatados."""
    try:
        import pandas as pd
        df = pd.DataFrame(records)
        logger.info("DataFrame criado: %d linhas x %d colunas", *df.shape)
        return df
    except ImportError:
        raise ImportError(
            "pandas não está instalado. Execute: pip install pandas"
        )


# ---------------------------------------------------------------------------
# Pipeline completo (Extract → Transform → Load)
# ---------------------------------------------------------------------------

def run_etl(
    output_path: str | Path,
    output_format: str = "csv",
    max_studies: Optional[int] = None,
    fields: Optional[list[str]] = None,
    **search_kwargs,
):
    """
    Executa o pipeline ETL completo.

    Parâmetros
    ----------
    output_path   : caminho do arquivo de saída
    output_format : 'csv' | 'json' | 'dataframe'
    max_studies   : limite de estudos a extrair (None = todos)
    fields        : campos a retornar da API (None = campos padrão)
    **search_kwargs : parâmetros de busca (ver ClinicalTrialsClient.iter_studies)

    Retorna
    -------
    list[dict] ou pandas.DataFrame (quando output_format='dataframe')
    """
    client = ClinicalTrialsClient()

    # -- Extract --
    raw_studies = list(
        client.iter_studies(
            fields=fields or DEFAULT_FIELDS,
            max_studies=max_studies,
            **search_kwargs,
        )
    )

    # -- Transform --
    records = transform_studies(raw_studies)

    # -- Load --
    if output_format == "csv":
        load_to_csv(records, output_path)
    elif output_format == "json":
        load_to_json(records, output_path)
    elif output_format == "dataframe":
        return load_to_dataframe(records)
    else:
        raise ValueError(f"output_format inválido: '{output_format}'. Use 'csv', 'json' ou 'dataframe'.")

    return records
