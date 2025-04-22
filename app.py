"""
app.py — Multi‑Fuel Carbon & Cost Scenario Explorer (MCCSE)
"""

from __future__ import annotations

import sys
import types
from dataclasses import dataclass
from typing import Dict
from datetime import datetime

import pandas as pd
import plotly.express as px
import streamlit as st

# ─────────────────────────  DATA CLASSES & CONSTANTS  ───────────────────────── #


@dataclass(frozen=True)
class Fuel:
    label: str
    density_t_m3: float
    lhv_mj_kg: float
    co2_factor_kg_t: float
    price_usd_t: float


@dataclass(frozen=True)
class VesselClass:
    name: str
    coefficient_a: float
    cargo_tonnes: int


FUEL_DATA: Dict[str, Fuel] = {
    "VLSFO": Fuel("VLSFO", 0.97, 40.2, 3_114, 650),
    "LNG": Fuel("LNG", 0.45, 50.0, 2_750, 450),
    "Bio‑VLSFO": Fuel("Bio‑VLSFO", 0.93, 39.7, 180, 900),
    "Methanol": Fuel("Methanol", 0.79, 19.9, 1_375, 550),
    "SMR (Nuclear)": Fuel("SMR (Nuclear)", 19.1, 80_620, 0, 0),
}

A_HANDY, A_SUPRA, A_PAN = (24 / 16**3, 30 / 16**3, 44 / 16**3)
VESSEL_CLASSES: Dict[str, VesselClass] = {
    "Handysize (40 kt DWT)": VesselClass("Handysize", A_HANDY, 40_000),
    "Supramax (55 kt DWT)":  VesselClass("Supramax",  A_SUPRA, 55_000),
    "Panamax (75 kt DWT)":   VesselClass("Panamax",   A_PAN,    75_000),
}

# ───────────────────────────────  CALCULATIONS  ────────────────────────────── #

calc_mod = types.ModuleType("mccse.calculations")


def penalty_factor(foul: float, wind: float, solar: float) -> float:
    fouling = 1 + foul / 100.0
    assist = 1 - (wind + solar) / 100.0
    return max(fouling * assist, 0.7)


def voyage_days(dist_nm: float, speed_kn: float) -> float:
    return dist_nm / (speed_kn * 24.0)


def fuel_tonnes(
    vessel: VesselClass,
    fuel: Fuel,
    speed_kn: float,
    dist_nm: float,
    foul: float,
    wind: float,
    solar: float,
) -> float:
    if fuel.label.startswith("SMR"):
        return 0.0
    daily = vessel.coefficient_a * speed_kn**3 * penalty_factor(foul, wind, solar)
    return daily * voyage_days(dist_nm, speed_kn)


def co2_t(fuel_t: float, fuel: Fuel) -> float:
    return fuel_t * fuel.co2_factor_kg_t / 1_000.0


def fuel_cost(fuel_t: float, fuel: Fuel) -> float:
    return fuel_t * fuel.price_usd_t


def carbon_cost(co2: float, price: float) -> float:
    return co2 * price


def usd_per_tonne_mile(total: float, cargo_t: int, dist_nm: float) -> float:
    return total / (cargo_t * dist_nm)


# register helpers so import works if users move to package structure
for _n, _o in list(locals().items()):
    if callable(_o) and _n not in ("calc_mod", "Fuel", "VesselClass"):
        setattr(calc_mod, _n, _o)
sys.modules.setdefault("mccse", types.ModuleType("mccse"))
sys.modules["mccse"].calculations = calc_mod
sys.modules["mccse.calculations"] = calc_mod

# ───────────────────────────────  STREAMLIT UI  ────────────────────────────── #

st.set_page_config(
    page_title="MCCSE – Multi‑Fuel Carbon & Cost Scenario Explorer",
    layout="wide",
)

# centre‑aligned logo per user layout
left, middle, right = st.columns([1, 2, 1])
with middle:
    st.image("mccse_logo_wide.png", width=1000)

st.title("Multi‑Fuel Carbon & Cost Scenario Explorer (MCCSE)")

# ─────────────────────────────  SIDEBAR INPUTS  ───────────────────────────── #

with st.sidebar:
    st.header("Vessel")
    ship_class = st.selectbox("Class", VESSEL_CLASSES.keys(), index=2)
    speed_kn = st.slider("Speed (kn)", 8.0, 16.0, 13.0, 0.1)
    st.divider()

    st.header("Fuel")
    fuel_label = st.radio("Type", list(FUEL_DATA.keys()), index=0)
    st.divider()

    st.header("Voyage")
    distance_nm = st.number_input("Distance (nm)", 100.0, 50_000.0, 10_000.0, 100.0)
    st.divider()

    st.header("Efficiency changes")
    hull_fouling_pct = st.slider("Hull fouling (%)", 0, 15, 0)

    want_wind = st.checkbox("Wind‑assist sails")
    wind_pct = st.slider(
        "Wind benefit (%)", 0, 30, 10, disabled=not want_wind, key="wind_pct_slider"
    )
    wind_assist_pct = wind_pct if want_wind else 0

    want_solar = st.checkbox("Solar PV assist")
    solar_pct = st.slider(
        "Solar benefit (%)", 0, 10, 3, disabled=not want_solar, key="solar_pct_slider"
    )
    solar_assist_pct = solar_pct if want_solar else 0
    st.divider()

    st.header("Carbon pricing")
    carbon_price_usd_t = st.number_input(
        "Price (USD / t CO₂)", 0.0, 1_000.0, 100.0, 10.0
    )

    calculate_clicked = st.button("Calculate")

# ─────────────────────────────  CALCULATION  ───────────────────────────────── #

@st.cache_data(show_spinner=False)
def run_model(
    vessel_key: str,
    fuel_key: str,
    speed: float,
    dist_nm: float,
    foul: int,
    wind: int,
    solar: int,
    co2_price: float,
) -> dict[str, float]:
    vessel = VESSEL_CLASSES[vessel_key]
    fuel = FUEL_DATA[fuel_key]

    fuel_t = fuel_tonnes(vessel, fuel, speed, dist_nm, foul, wind, solar)
    co2 = co2_t(fuel_t, fuel)
    fuel_sp = fuel_cost(fuel_t, fuel)
    carb_sp = carbon_cost(co2, co2_price)
    total = fuel_sp + carb_sp
    ctm = usd_per_tonne_mile(total, vessel.cargo_tonnes, dist_nm)
    return {
        "fuel_t": fuel_t,
        "co2_t": co2,
        "fuel_spend": fuel_sp,
        "carbon_spend": carb_sp,
        "total_spend": total,
        "usd_per_tonne_mile": ctm,
    }


# session state history init
if "history" not in st.session_state:
    st.session_state.history = []

# compute on click / first load
if calculate_clicked or "kpi" not in st.session_state:
    st.session_state.kpi = run_model(
        ship_class,
        fuel_label,
        speed_kn,
        distance_nm,
        hull_fouling_pct,
        wind_assist_pct,
        solar_assist_pct,
        carbon_price_usd_t,
    )
    # store snapshot in history
    snapshot = {
        "Time": datetime.now().strftime("%H:%M:%S"),
        "Vessel": ship_class.split()[0],
        "Fuel": fuel_label.split()[0],
        "Speed (kn)": speed_kn,
        "Dist (nm)": distance_nm,
        "Fuel (t)": round(st.session_state.kpi["fuel_t"], 1),
        "CO₂ (t)": round(st.session_state.kpi["co2_t"], 1),
        "$/t‑mile": round(st.session_state.kpi["usd_per_tonne_mile"], 5),
    }
    st.session_state.history.append(snapshot)

kpi = st.session_state.kpi

# ─────────────────────────────  MAIN OUTPUT  ──────────────────────────────── #
m1, m2, m3, m4, m5 = st.columns(5)
m1.metric("Fuel (t)", f"{kpi['fuel_t']:.1f}")
m2.metric("CO₂ (t)", f"{kpi['co2_t']:.1f}")
m3.metric("Fuel cost", f"${kpi['fuel_spend']:,.0f}")
m4.metric("Carbon cost", f"${kpi['carbon_spend']:,.0f}")
m5.metric("$ / tonne‑mile", f"${kpi['usd_per_tonne_mile']:.5f}")

st.subheader("Cost breakdown")
st.plotly_chart(
    px.bar(
        pd.DataFrame(
            {"Component": ["Fuel", "Carbon"], "USD": [kpi["fuel_spend"], kpi["carbon_spend"]]}
        ),
        x="Component",
        y="USD",
        text_auto=".2s",
    ),
    use_container_width=True,
)

# ─────────────────────────────  SESSION HISTORY  ─────────────────────────── #
if st.session_state.history:
    st.subheader("Calculation history")
    hist_df = pd.DataFrame(st.session_state.history)
    st.dataframe(hist_df, use_container_width=True)

# ─────────────────────────────  ABOUT SECTION  ───────────────────────────── #
with st.expander("About MCCSE", expanded=True):
    st.markdown(
        """
MCCSE calculates fuel burn and emissions for a vessel class, voyage distance, fuel type and optional energy‑saving
technologies (wind sails or solar PV). All results for single voyages; upfront capital costs (e.g. nuclear SMR) are not included and the model is massively simplified.
This tool should be used as a illustrative tool and is not necessarily representative of real-world conditions. It uses estimates of fuel prices and emissions.

### Data sources

* **IMO MEPC.391(81)** – propulsion reference coefficients
* **Baltic Exchange Indices** - fuel consumption for vessel classes
* **SGMF (2024)** – LHVs, densities & CO₂ factors for fuels  
* **Bunkerworld Q1‑2025** – average spot prices for conventional fuels  
* **BAR Tech / Wärtsilä (2024)** – wind and solar assist benchmarks  
* Carbon‑price default (\\$100 / t CO₂) reflects forward **EU‑ETS** pricing.
"""
    )
