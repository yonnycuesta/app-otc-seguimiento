import re
import streamlit as st
import pandas as pd
from datetime import datetime, time, timedelta
import concurrent.futures
import plotly.graph_objects as go

import Sytex

cliente_description = r"1. Nombre Cliente:(.*?)\n"

st.set_page_config(
    page_title="Seguimiento OTC |Plataforma para realizar un seguimiento detallado de las Órdenes de Trabajo de Campo (OTCs), mostrando en tiempo real el estado de cada solicitud.",
    page_icon="images/logue.png",
    layout="wide",
)


def seg_Descrip(texto):
    cliente_match = re.search(cliente_description, texto)
    cliente = cliente_match.group(1).strip() if cliente_match else None
    return cliente


def FindTask_status(id):
    Taskurl = f"https://app.sytex.io/api/statushistory/?content_type__model=task&object_id={id}&status_field__in=status,status_step"
    return Sytex.RunApi(Taskurl)


def FindTask(id):
    Taskurl = "https://app.sytex.io/api/task/?id=" + id
    return Sytex.RunApi(Taskurl)


def converhora(fecha_hora_original):
    fecha_hora_objeto = datetime.fromisoformat(fecha_hora_original)
    fecha_hora_objeto -= timedelta(hours=2)
    fecha_hora_militar = fecha_hora_objeto.strftime("%Y/%m/%d %H:%M:%S")
    return fecha_hora_militar


def FindTask_desde_hasta(fecha):
    fecha_str = fecha.strftime("%Y-%m-%d")
    Taskurl = f"https://app.sytex.io/api/task/?plan_date_duration={fecha_str}&project=144528&task_template=741&status_step_name=2898&status_step_name=1249&status_step_name=4014&status_step_name=1246&status_step_name=1300&status_step_name=1245&limit=10000"
    return Sytex.RunApi(Taskurl)


def generar_dataframe(fecha):
    tareas = FindTask_desde_hasta(fecha)

    if tareas["count"] == 0:
        return None

    lista_tareas = [str(tarea["id"]) for tarea in tareas["results"]]

    with concurrent.futures.ThreadPoolExecutor() as executor:
        estados = list(executor.map(FindTask_status, lista_tareas))
        detalles_tareas = list(executor.map(FindTask, lista_tareas))

    registros = []
    for tarea, estado in zip(detalles_tareas, estados):
        tarea_actual = tarea["results"][0]
        codigo = tarea_actual["code"]

        # Extraer información adicional
        if tarea_actual["description"] != None:
            cliente = seg_Descrip(tarea_actual["description"])
        else:
            cliente = "Sin cliente"

        evento = tarea_actual.get("name", "Sin descripción")

        # Tecnico
        if tarea_actual.get("assigned_staff"):
            tecnico = tarea_actual["assigned_staff"]["name"]
        else:
            tecnico = "Sin asignar"

        # Sitio
        if tarea_actual["sites"][0]["name"] != None:
            sitio = tarea_actual["sites"][0]["name"]
        else:
            sitio = "Sin definir"

        # Obtener el último estado y su timestamp
        ultimo_estado = None
        ultimo_timestamp = None

        cambios_ordenados = sorted(
            estado["results"],
            key=lambda x: x["when_created"] if x.get("when_created") else "",
            reverse=True,
        )

        for cambio in cambios_ordenados:
            if cambio.get("to_status_step"):
                ultimo_estado = cambio["to_status_step"]["name"]["name"]
                ultimo_timestamp = converhora(cambio["when_created"])
                break

        registros.append(
            {
                "Codigo": codigo,
                "Tecnico asignado": tecnico,
                "Estado": ultimo_estado,
                "Timestamp": ultimo_timestamp,
                "Cliente": cliente,
                "Evento": evento,
                "Ubicación": sitio,
            }
        )

    return pd.DataFrame(registros)


def process_data(df):
    if "Timestamp" in df.columns:
        df["Timestamp"] = pd.to_datetime(df["Timestamp"])
    return df


def create_gantt_figure(df_filtered, fecha_seleccionada):
    colors = {
        "Asignada": "#FFA500",
        "en camino": "#1E90FF",
        "En proceso": "#FFD700",
        "Devuelta": "#FF4444",
        "Completada": "#32CD32",
        "Aberta": "#B7B7B7",
    }

    fig = go.Figure()

    start_time = datetime.combine(
        fecha_seleccionada, datetime.min.time().replace(hour=7, minute=30)
    )
    end_time = datetime.combine(
        fecha_seleccionada, datetime.min.time().replace(hour=17, minute=0)
    )

    df_filtered = df_filtered.sort_values("Codigo")
    estados_mostrados = set()

    for idx, row in df_filtered.iterrows():
        task_name = f"{row['Tecnico asignado']} - OTC {row['Codigo']}"

        if pd.notna(row["Timestamp"]):
            duration = timedelta(minutes=30)
            end_timestamp = row["Timestamp"] + duration

            shown_start = max(row["Timestamp"], start_time)
            shown_end = min(end_timestamp, end_time)

            # Hora Tica
            hour_tica = row["Timestamp"] - timedelta(hours=1)
            # Crear el texto para el hover
            hover_text = (
                f"OTC: {row['Codigo']}<br>"
                f"Cliente: {row['Cliente']}<br>"
                f"Evento: {row['Evento']}<br>"
                f"Estado: {row['Estado']}<br>"
                f"Hora COL: {row['Timestamp'].strftime('%H:%M:%S')}<br>"
                f"Hora TICA: {hour_tica.strftime('%H:%M:%S')}<br>"
                f"Ubicación: {row['Ubicación']}"
            )

            # Mostrar en la leyenda solo si es la primera vez que aparece este estado
            show_in_legend = row["Estado"] not in estados_mostrados
            if show_in_legend:
                estados_mostrados.add(row["Estado"])

            fig.add_trace(
                go.Bar(
                    x=[(shown_end - shown_start).total_seconds() / 3600],
                    y=[task_name],
                    orientation="h",
                    base=[(shown_start - start_time).total_seconds() / 3600],
                    marker_color=colors.get(row["Estado"], "#808080"),
                    name=row["Estado"],
                    text=row["Estado"],
                    textposition="inside",
                    showlegend=show_in_legend,  # Solo mostrar en leyenda si es la primera vez
                    legendgroup=row["Estado"],
                    hovertext=hover_text,
                    hoverinfo="text",
                )
            )

    current_time = datetime.now() - timedelta(hours=5)

    if start_time <= current_time <= end_time:
        fig.add_vline(
            x=(current_time - start_time).total_seconds() / 3600,
            line=dict(color="red", width=2, dash="dash"),
            annotation_text="Tiempo actual",
            annotation_position="top",
        )

    fig.update_layout(
        barmode="overlay",
        height=max(400, len(df_filtered) * 40),
        xaxis=dict(
            title="Hora del día",
            range=[0, (end_time - start_time).total_seconds() / 3600],
            tickformat="%H:%M",
            tickmode="array",
            tickvals=[i / 2 for i in range(20)],
            ticktext=[
                (start_time + timedelta(minutes=30 * i)).strftime("%H:%M")
                for i in range(20)
            ],
        ),
        yaxis=dict(title="Órdenes", autorange="reversed"),
        showlegend=True,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        margin=dict(l=200),
        hoverlabel=dict(bgcolor="white", font_size=12, font_family="Arial"),
    )

    return fig


def main():
    st.subheader("Seguimiento de OTCs - ICE")

    if "df" not in st.session_state:
        st.session_state.df = None

    fecha_seleccionada = st.sidebar.date_input("Seleccionar fecha")

    if st.sidebar.button("Generar Informe"):
        with st.spinner("Generando informe..."):
            df = generar_dataframe(fecha_seleccionada)
            if df is not None:
                st.session_state.df = process_data(df)
            else:
                st.error("No se encontraron datos para la fecha seleccionada")

    if st.session_state.df is not None:
        df = st.session_state.df

        all_states = [
            "Asignada",
            "en camino",
            "En proceso",
            "Devuelta",
            "Completada",
            "Abierta",
        ]
        selected_states = st.sidebar.multiselect(
            "Filtrar por estados", all_states, default=all_states
        )

        technicians = df["Tecnico asignado"].dropna().unique()
        all_technicians = sorted(
            [tech for tech in technicians if isinstance(tech, str)]
        )

        if not all_technicians:
            st.error("No se encontraron técnicos asignados en los datos")
            return

        selected_technicians = st.sidebar.multiselect(
            "Filtrar por técnicos", all_technicians, default=all_technicians
        )

        mask = (df["Tecnico asignado"].isin(selected_technicians)) & (
            df["Estado"].isin(selected_states)
        )
        df_filtered = df[mask].copy()

        if not df_filtered.empty:
            fig = create_gantt_figure(df_filtered, fecha_seleccionada)
            st.plotly_chart(fig, use_container_width=True)

            st.subheader("Estadísticas del día")
            col1, col2, col3, col4, col5 = st.columns(5)

            with col1:
                st.metric("Total de órdenes", len(df_filtered))

            with col2:
                completed = len(df_filtered[df_filtered["Estado"] == "Asignada"])
                st.metric("ASIGNADAS", completed)

            with col3:
                completed = len(df_filtered[df_filtered["Estado"] == "Completada"])
                st.metric("COMPLETADAS", completed)

            with col4:
                in_progress = len(df_filtered[df_filtered["Estado"] == "En proceso"])
                st.metric("EN PROCESO", in_progress)
                
            with col5:
                returned = len(df_filtered[df_filtered["Estado"] == "Devuelta"])
                st.metric("DEVUELTA", returned)

            # with col5:
            #     earliest = df_filtered["Timestamp"].min()
            #     latest = df_filtered["Timestamp"].max()
            #     if pd.notna(earliest) and pd.notna(latest):
            #         avg_time = (latest - earliest).total_seconds() / 3600
            #         st.metric("Tiempo total de operación", f"{avg_time:.2f} hrs")

            st.subheader("Resumen por técnico")
            summary_df = pd.DataFrame(
                {
                    "Técnico": selected_technicians,
                    "Asignadas": [
                        len(
                            df_filtered[
                                (df_filtered["Tecnico asignado"] == tech)
                                & (df_filtered["Estado"] == "Asignada")
                            ]
                        )
                        for tech in selected_technicians
                    ],
                    "En Camino": [
                        len(
                            df_filtered[
                                (df_filtered["Tecnico asignado"] == tech)
                                & (df_filtered["Estado"] == "en camino")
                            ]
                        )
                        for tech in selected_technicians
                    ],
                    "En Proceso": [
                        len(
                            df_filtered[
                                (df_filtered["Tecnico asignado"] == tech)
                                & (df_filtered["Estado"] == "En proceso")
                            ]
                        )
                        for tech in selected_technicians
                    ],
                    "Devueltas": [
                        len(
                            df_filtered[
                                (df_filtered["Tecnico asignado"] == tech)
                                & (df_filtered["Estado"] == "Devuelta")
                            ]
                        )
                        for tech in selected_technicians
                    ],
                    "Completadas": [
                        len(
                            df_filtered[
                                (df_filtered["Tecnico asignado"] == tech)
                                & (df_filtered["Estado"] == "Completada")
                            ]
                        )
                        for tech in selected_technicians
                    ],
                    "Abiertas": [
                        len(
                            df_filtered[
                                (df_filtered["Tecnico asignado"] == tech)
                                & (df_filtered["Estado"] == "Abierta")
                            ]
                        )
                        for tech in selected_technicians
                    ],
                    "Total Órdenes": [
                        len(df_filtered[df_filtered["Tecnico asignado"] == tech])
                        for tech in selected_technicians
                    ],
                }
            )
            st.dataframe(summary_df, hide_index=True)
            
            # Nueva sección: Tabla dinámica basada en df_filtered y el período de 42 horas
            st.subheader("Resumen General del Día")
            current_time = datetime.now() - timedelta(hours=5)  # Ajuste a zona horaria COL

            # Filtrar tareas por estado y calcular si están prescritas (más de 42 horas desde Timestamp)
            def is_prescribed(timestamp):
                if pd.isna(timestamp):
                    return False
                time_diff = current_time - timestamp
                return time_diff > timedelta(hours=42)

            # Contar tareas por estado y si están prescritas
            atendidas = df_filtered[df_filtered["Estado"] == "Completada"]
            devueltas = df_filtered[df_filtered["Estado"] == "Devuelta"]
            asignadas = df_filtered[df_filtered["Estado"] == "Asignada"]

            resumen_dia = pd.DataFrame({
                "Estado": ["Completadas", "Devueltas", "Asignadas"],
                "Completadas": [
                    len(atendidas[~atendidas["Timestamp"].apply(is_prescribed)]),
                    len(devueltas[~devueltas["Timestamp"].apply(is_prescribed)]),
                    len(asignadas[~asignadas["Timestamp"].apply(is_prescribed)])
                ],
                "Prescritas": [
                    len(atendidas[atendidas["Timestamp"].apply(is_prescribed)]),
                    len(devueltas[devueltas["Timestamp"].apply(is_prescribed)]),
                    len(asignadas[asignadas["Timestamp"].apply(is_prescribed)])
                ],
                "Total": [
                    len(atendidas),
                    len(devueltas),
                    len(asignadas)
                ]
            })
            st.dataframe(resumen_dia, hide_index=True)


        else:
            st.warning("No hay datos para mostrar con los filtros seleccionados.")
    else:
        st.info("Selecciona una fecha y presiona 'Generar Informe' para comenzar.")


if __name__ == "__main__":
    main()
