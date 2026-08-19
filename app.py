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


def query_bigquery(project_id, query, _parameters=()):
    client = get_bigquery_client(project_id)
    job_config = bigquery.QueryJobConfig(query_parameters=list(_parameters))
    return client.query(query, job_config=job_config).result().to_dataframe()


@st.cache_data(ttl=600)
def load_top_clubs(project_id, season):
    query = f"""
        WITH club_base AS (
            SELECT
                club_id,
                name,
                MAX(total_market_value) AS total_market_value,
                MAX(squad_size) AS squad_size,
                MAX(SAFE_CAST(net_transfer_record AS FLOAT64))
                    AS net_transfer_record
            FROM {table_ref(project_id, "clubs")}
            WHERE last_season = @season
            GROUP BY club_id, name
        )
        (
            SELECT
                name,
                net_transfer_record,
                "Mejores" AS category
            FROM club_base
            WHERE net_transfer_record IS NOT NULL
            ORDER BY net_transfer_record DESC
            LIMIT 5
        )

        UNION ALL

        (
            SELECT
                name,
                net_transfer_record,
                "Peores" AS category
            FROM club_base
            WHERE net_transfer_record IS NOT NULL
            ORDER BY net_transfer_record ASC
            LIMIT 5
        )
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


def load_player_valuations(project_id, player_id):
    query = f"""
        SELECT date, market_value_in_eur
        FROM {table_ref(project_id, "player_valuations")}
        WHERE player_id = @player_id
          AND market_value_in_eur IS NOT NULL
        ORDER BY date
    """
    parameters = (
        bigquery.ScalarQueryParameter("player_id", "INT64", int(player_id)),
    )
    result = query_bigquery(project_id, query, _parameters=parameters)
    result["date"] = pd.to_datetime(result["date"], errors="coerce")
    return result.dropna(subset=["date"])


@st.cache_data(ttl=600)
def load_event_counts(project_id, season):
    query = f"""
        SELECT events.type, COUNT(*) AS event_count
        FROM {table_ref(project_id, "game_events")} AS events
        INNER JOIN {table_ref(project_id, "games")} AS games
            ON events.game_id = games.game_id
        WHERE events.type IS NOT NULL
          AND games.season = @season
        GROUP BY events.type
        ORDER BY event_count DESC
    """
    parameters = (bigquery.ScalarQueryParameter("season", "INT64", int(season)),)
    return query_bigquery(project_id, query, _parameters=parameters)


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

selected_season = st.sidebar.number_input(
    "Última temporada de clubes",
    min_value=2000,
    max_value=2030,
    value=2025,
    step=1,
)

if "active_season" not in st.session_state:
    st.session_state.active_season = selected_season

if st.sidebar.button("Actualizar", type="primary", use_container_width=True):
    st.session_state.active_season = selected_season
    load_top_clubs.clear()
    load_event_counts.clear()
    st.rerun()

season = st.session_state.active_season

st.subheader("Resumen del fútbol en BigQuery")

try:
    clubs = load_top_clubs(project_id, season)
    players = load_player_names(project_id)
    event_counts = load_event_counts(project_id, season)

    first_column, second_column = st.columns(2)

    with first_column:
        st.markdown("#### Equipos con mejor y peor balance de transferencias")
        if clubs.empty:
            st.info(
                "No hay balances de transferencias numéricos para esa temporada. "
                "Vuelve a ejecutar el pipeline después de actualizar script_main.py."
            )
        else:
            metric_column = "net_transfer_record"
            clubs[metric_column] = pd.to_numeric(
                clubs[metric_column], errors="coerce"
            )
            clubs["metric_label"] = clubs[metric_column].map(format_euros)

            chart = px.bar(
                clubs.sort_values(metric_column),
                x=metric_column,
                y="name",
                orientation="h",
                text="metric_label",
                color="category",
                labels={
                    metric_column: "Balance neto de transferencias",
                    "name": "Club",
                    "category": "Resultado",
                },
                color_discrete_map={"Mejores": "#35b779", "Peores": "#ef6548"},
            )
            chart.update_layout(height=440)
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
    player_options = {
        f"{row.name} (ID: {int(row.player_id)})": int(row.player_id)
        for row in players.itertuples(index=False)
    }
    selected_player = st.selectbox("Jugador", list(player_options))
    selected_player_id = player_options[selected_player]
    valuations = load_player_valuations(project_id, selected_player_id)

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