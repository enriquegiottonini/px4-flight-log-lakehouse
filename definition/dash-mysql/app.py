import logging
import os
from datetime import datetime

import mysql.connector
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from dash import Dash, Input, Output, dcc, html

app = Dash(__name__)
server = app.server
app.title = "Dashboard agrícola"

VARIABLES = {
    "temperatura": (["tempMin", "tempMax", "tempAvg"], "Temperatura", "°C"),
    "humedad": (["humRelMin", "humRelMax", "humRelAvg"], "Humedad relativa", "%"),
    "radiacion": (["radSol"], "Radiación solar media del periodo", "W/m²"),
    "precipitacion": (["prec"], "Precipitación acumulada del periodo", "mm"),
}

app.layout = html.Div([
    html.H1("Monitoreo del campo experimental"),
    html.P("Dash + MySQL · Datos iniciales simulados · Consulta cada 10 segundos"),
    dcc.Dropdown(
        id="variable",
        options=[{"label": v[1], "value": k} for k, v in VARIABLES.items()],
        value="temperatura",
        clearable=False,
    ),
    dcc.Graph(id="grafica"),
    html.P(id="estado"),
    dcc.Interval(id="reloj", interval=10_000, n_intervals=0),
], style={"maxWidth": "1100px", "margin": "40px auto", "padding": "20px",
          "fontFamily": "Arial, sans-serif"})


def leer_datos():
    conexion = mysql.connector.connect(
        host=os.environ["DB_HOST"],
        port=int(os.environ.get("DB_PORT", "3306")),
        user=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
        database=os.environ["DB_NAME"],
        connection_timeout=5,
    )
    try:
        with conexion.cursor(dictionary=True) as cursor:
            cursor.execute("""
                SELECT id,fecha,tempMin,tempMax,tempAvg,
                       humRelMin,humRelMax,humRelAvg,radSol,prec
                FROM mediciones ORDER BY fecha DESC,id DESC LIMIT 1000
            """)
            registros = cursor.fetchall()
    finally:
        conexion.close()
    if not registros:
        return pd.DataFrame()
    return pd.DataFrame(registros).sort_values(["fecha", "id"])


@app.callback(
    Output("grafica", "figure"), Output("estado", "children"),
    Input("variable", "value"), Input("reloj", "n_intervals"),
)
def actualizar(variable, _):
    try:
        datos = leer_datos()
    except mysql.connector.Error:
        logging.exception("No se pudo consultar MySQL")
        fig = go.Figure()
        fig.add_annotation(text="No se pudo consultar MySQL. Se reintentará automáticamente.",
                           showarrow=False)
        return fig, "Conexión no disponible; revisa docker compose logs."
    if datos.empty:
        return go.Figure(), "La tabla todavía no tiene mediciones."
    columnas, titulo, unidad = VARIABLES[variable]
    if variable == "precipitacion":
        fig = px.bar(datos, x="fecha", y=columnas[0], title=titulo)
    else:
        fig = px.line(datos, x="fecha", y=columnas, markers=True, title=titulo)
    fig.update_layout(template="plotly_white", xaxis_title="Fecha",
                      yaxis_title=unidad, legend_title_text="Serie")
    return fig, (
        f"Última consulta: {datetime.now():%Y-%m-%d %H:%M:%S} (hora del contenedor). "
        f"Registros mostrados: {len(datos)} (máximo 1000)."
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8050, debug=False)
