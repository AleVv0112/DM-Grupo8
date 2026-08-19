import os
import re

import pandas as pd
import plotly.express as px
import streamlit as st
from google.cloud import bigquery
from google.oauth2 import service_account


st.set_page_config(
    page_title="Football Data Explorer",
    page_icon="⚽",
    layout="wide",
)

DATASET_NAME = "football_data"
PROJECT_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{4,28}[a-z0-9]$")


def get_project_id():
    """Obtiene el proyecto desde secrets, variable de entorno o ADC."""
    try:
        configured_project = st.secrets.get("gcp_project")
        service_account_config = st.secrets.get("gcp_service_account")
    except Exception:
        configured_project = None
        service_account_config = None

    project_id = configured_project or os.getenv("GOOGLE_CLOUD_PROJECT")
    if project_id:
        return project_id

    if service_account_config:
        return service_account_config["project_id"]

    return bigquery.Client().project


@st.cache_resource
def get_bigquery_client(project_id):
    """Crea un cliente reutilizable para las consultas de BigQuery."""
    try:
        service_account_config = st.secrets.get("gcp_service_account")
    except Exception:
        service_account_config = None

    if service_account_config:
        credentials = service_account.Credentials.from_service_account_info(
            dict(service_account_config)
        )
        return bigquery.Client(project=project_id, credentials=credentials)

    return bigquery.Client(project=project_id)


def table_ref(project_id, table_name):
    if not PROJECT_PATTERN.fullmatch(project_id):
        raise ValueError("El ID del proyecto de Google Cloud no es válido.")
    return f"`{project_id}.{DATASET_NAME}.{table_name}`"


@st.cache_data(ttl=600)
def query_bigquery(project_id, query, _parameters=()):
    client = get_bigquery_client(project_id)
    job_config = bigquery.QueryJobConfig(query_parameters=list(_parameters))
    return client.query(query, job_config=job_config).result().to_dataframe()


@st.cache_data(ttl=600)
def load_top_clubs(project_id, season):
    query = f"""
        SELECT name, total_market_value, squad_size
        FROM {table_ref(project_id, "clubs")}
        WHERE last_season = @season
          AND total_market_value IS NOT NULL
        ORDER BY total_market_value DESC
        LIMIT 10
    """
    parameters = (bigquery.ScalarQueryParameter("season", "INT64", season),)
    return query_bigquery(project_id, query, _parameters=parameters)


@st.cache_data(ttl=600)
def load_player_names(project_id):
    query = f"""
        SELECT player_id, name
        FROM {table_ref(project_id, "players")}
        WHERE name IS NOT NULL
        ORDER BY name
    """
    return query_bigquery(project_id, query)


@st.cache_data(ttl=600)
def load_player_valuations(project_id, player_id):
    query = f"""
        SELECT date, market_value_in_eur
        FROM {table_ref(project_id, "player_valuations")}
        WHERE player_id = @player_id
          AND market_value_in_eur IS NOT NULL
        ORDER BY date
    """
    parameters = (bigquery.ScalarQueryParameter("player_id", "INT64", player_id),)
    result = query_bigquery(project_id, query, _parameters=parameters)
    result["date"] = pd.to_datetime(result["date"], errors="coerce")
    return result.dropna(subset=["date"])


@st.cache_data(ttl=600)
def load_event_counts(project_id):
    query = f"""
        SELECT type, COUNT(*) AS event_count
        FROM {table_ref(project_id, "game_events")}
        WHERE type IS NOT NULL
        GROUP BY type
        ORDER BY event_count DESC
    """
    return query_bigquery(project_id, query)


def format_euros(value):
    if value >= 1_000_000:
        return f"€{value / 1_000_000:.1f} M"
    if value >= 1_000:
        return f"€{value / 1_000:.0f} K"
    return f"€{value:.0f}"


st.title("Football Data Explorer")
st.caption("Exploración interactiva de las tablas almacenadas en Google BigQuery")

try:
    project_id = get_project_id()
    client = get_bigquery_client(project_id)
    client.get_dataset(f"{project_id}.{DATASET_NAME}")
except Exception as error:
    st.error("No se pudo conectar con BigQuery.")
    st.code(
        "gcloud auth application-default login\n"
        "streamlit run app.py",
        language="powershell",
    )
    st.caption(f"Detalle técnico: {error}")
    st.stop()

st.sidebar.header("Filtros")
st.sidebar.caption(f"Proyecto: {project_id}")

season = st.sidebar.number_input(
    "Última temporada de clubes",
    min_value=2000,
    max_value=2030,
    value=2025,
    step=1,
)

st.subheader("Resumen del fútbol en BigQuery")

try:
    clubs = load_top_clubs(project_id, season)
    players = load_player_names(project_id)
    event_counts = load_event_counts(project_id)

    first_column, second_column = st.columns(2)

    with first_column:
        st.markdown("#### Top 10 clubes por valor de mercado")
        if clubs.empty:
            st.info("No hay clubes para esa temporada.")
        else:
            clubs["market_value_label"] = clubs["total_market_value"].map(format_euros)
            chart = px.bar(
                clubs.sort_values("total_market_value"),
                x="total_market_value",
                y="name",
                orientation="h",
                text="market_value_label",
                labels={"total_market_value": "Valor de mercado", "name": "Club"},
                color="total_market_value",
                color_continuous_scale="Tealgrn",
            )
            chart.update_layout(coloraxis_showscale=False, height=440)
            st.plotly_chart(chart, use_container_width=True)

    with second_column:
        st.markdown("#### Tipos de eventos registrados")
        if event_counts.empty:
            st.info("No hay eventos disponibles.")
        else:
            chart = px.bar(
                event_counts,
                x="type",
                y="event_count",
                labels={"type": "Tipo de evento", "event_count": "Cantidad"},
                color="event_count",
                color_continuous_scale="Sunsetdark",
            )
            chart.update_layout(coloraxis_showscale=False, height=440)
            st.plotly_chart(chart, use_container_width=True)

    st.markdown("#### Evolución del valor de un jugador")
    player_options = dict(zip(players["name"], players["player_id"]))
    selected_player = st.selectbox("Jugador", list(player_options))
    valuations = load_player_valuations(project_id, player_options[selected_player])

    if valuations.empty:
        st.info("No hay valoraciones históricas para este jugador.")
    else:
        chart = px.line(
            valuations,
            x="date",
            y="market_value_in_eur",
            markers=True,
            labels={"date": "Fecha", "market_value_in_eur": "Valor de mercado"},
        )
        chart.update_yaxes(tickprefix="€", separatethousands=True)
        chart.update_layout(height=400)
        st.plotly_chart(chart, use_container_width=True)

except Exception as error:
    st.error("La conexión funciona, pero una consulta no pudo completarse.")
    st.caption(f"Detalle técnico: {error}")