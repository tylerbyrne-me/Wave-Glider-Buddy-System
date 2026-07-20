"""
Declarative Slocum data-bundle registry.

Each bundle declares ERDDAP variables, preprocessor, and whether server-side
time decimation is allowed. Future sensors (e.g. dissolved oxygen) register
here without new parallel cache/service modules.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable, Optional

import pandas as pd

from ..core.data import processors
from ..core.slocum_erddap_client import (
    SLOCUM_CHECKLIST_VARIABLES,
    SLOCUM_CTD_VARIABLES,
    SLOCUM_DASHBOARD_VARIABLES,
)

# Bump when parquet schema / preprocess semantics change so overage keys invalidate.
BUNDLE_SCHEMA_VERSION = "4"


@dataclass(frozen=True)
class SlocumBundleSpec:
    name: str
    erddap_variables: tuple[str, ...]
    preprocess: Callable[[pd.DataFrame], pd.DataFrame]
    allow_decimation: bool = True
    schema_version: str = BUNDLE_SCHEMA_VERSION
    description: str = ""


SLOCUM_BUNDLES: dict[str, SlocumBundleSpec] = {
    "dashboard": SlocumBundleSpec(
        name="dashboard",
        erddap_variables=tuple(SLOCUM_DASHBOARD_VARIABLES),
        preprocess=processors.preprocess_slocum_dashboard_df,
        allow_decimation=True,
        description="Vehicle navigation, power, and track variables for the mission dashboard.",
    ),
    "ctd": SlocumBundleSpec(
        name="ctd",
        erddap_variables=tuple(SLOCUM_CTD_VARIABLES),
        preprocess=processors.preprocess_slocum_ctd_df,
        allow_decimation=False,
        description="CTD science profiles (temperature, conductivity, density, salinity, pressure).",
    ),
    "checklist": SlocumBundleSpec(
        name="checklist",
        erddap_variables=tuple(SLOCUM_CHECKLIST_VARIABLES),
        preprocess=processors.preprocess_slocum_checklist_df,
        allow_decimation=False,
        description="Flight and science variables for daily pilot checklist autofill (full resolution for Plot-it).",
    ),
}

# Bundles synced into the rolling hot mirror by default.
DEFAULT_MIRROR_BUNDLES: tuple[str, ...] = ("dashboard", "ctd", "checklist")


def get_bundle_spec(bundle: str) -> SlocumBundleSpec:
    key = (bundle or "").strip().lower()
    if key not in SLOCUM_BUNDLES:
        raise KeyError(
            f"Unknown Slocum bundle '{bundle}'. "
            f"Registered: {', '.join(sorted(SLOCUM_BUNDLES))}."
        )
    return SLOCUM_BUNDLES[key]


def list_bundle_names() -> list[str]:
    return list(SLOCUM_BUNDLES.keys())


def iter_bundle_specs(names: Optional[Iterable[str]] = None) -> list[SlocumBundleSpec]:
    if names is None:
        names = DEFAULT_MIRROR_BUNDLES
    return [get_bundle_spec(name) for name in names]


def preprocess_bundle_df(bundle: str, raw: Optional[pd.DataFrame]) -> pd.DataFrame:
    spec = get_bundle_spec(bundle)
    if raw is None:
        return pd.DataFrame()
    return spec.preprocess(raw)
