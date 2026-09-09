"""
Motor de recomendaciones basado en reglas.

Traduce las métricas agregadas de cada zona (visitas, dwell, tasa de
detención) en recomendaciones de negocio en lenguaje llano -- sin usar
ningún modelo de IA de pago ni dependencias externas. 100% gratuito y
funciona sin conexión a internet, lo cual también refuerza el criterio
de viabilidad edge del reto.

IMPORTANTE (honestidad técnica): estas reglas identifican PATRONES DE
COMPORTAMIENTO observables (tráfico, permanencia), no el "por qué"
psicológico del cliente. El texto se redacta como "esto podría sugerir..."
en vez de afirmaciones causales certeras, para no sobre-prometer algo
que la visión computacional no puede realmente inferir.

Uso:
    python dashboard\\ai_insights.py --summary data\\output\\zone_summary_merl_demo.csv
"""

import argparse
import os
import pandas as pd


def parse_args():
    parser = argparse.ArgumentParser(description="Genera recomendaciones de negocio a partir de métricas de zona.")
    parser.add_argument("--summary", type=str, required=True,
                         help="CSV de zone_summary generado por zoning.py")
    return parser.parse_args()


def _classify_traffic_dwell(row, median_visits, median_dwell, has_comparison: bool):
    """Determina el cuadrante tráfico x dwell de una zona. Si solo hay una
    zona (has_comparison=False), usa la tasa de detención como proxy."""
    if not has_comparison:
        if row["stop_rate_pct"] >= 50:
            return "alto_trafico_alto_dwell"
        return "alto_trafico_bajo_dwell"

    high_traffic = row["total_visits"] >= median_visits
    high_dwell = row["avg_dwell_seconds"] >= median_dwell

    if high_traffic and high_dwell:
        return "alto_trafico_alto_dwell"
    elif high_traffic and not high_dwell:
        return "alto_trafico_bajo_dwell"
    elif not high_traffic and high_dwell:
        return "bajo_trafico_alto_dwell"
    else:
        return "bajo_trafico_bajo_dwell"


def generate_recommendation(row, quadrant: str) -> dict:
    """Devuelve un diccionario con diagnóstico + sugerencia accionable,
    redactado en lenguaje llano y sin afirmaciones causales que la
    visión computacional no puede sostener."""
    zone_label = row["zone_label"]

    templates = {
        "alto_trafico_alto_dwell": {
            "diagnostico": (
                f"'{zone_label}' tiene buen tráfico y la gente se detiene ahí "
                f"({row['stop_rate_pct']:.0f}% de tasa de detención, "
                f"{row['avg_dwell_seconds']:.1f}s de permanencia promedio). "
                f"Este comportamiento sugiere que la ubicación está funcionando bien."
            ),
            "sugerencia": (
                "Mantener el producto actual en esta zona. Es un buen candidato "
                "para productos de margen alto o para destacar novedades, ya que "
                "capta atención de forma consistente."
            ),
        },
        "alto_trafico_bajo_dwell": {
            "diagnostico": (
                f"'{zone_label}' recibe tráfico, pero la mayoría pasa de largo "
                f"({row['stop_rate_pct']:.0f}% de tasa de detención). Esto podría "
                f"sugerir que es una zona de paso más que una zona de decisión de compra."
            ),
            "sugerencia": (
                "Considerar señalética llamativa o producto de impulso económico "
                "en esta zona, ya que el tráfico ya existe -- el reto es captar la "
                "atención en el trayecto, no atraer más gente."
            ),
        },
        "bajo_trafico_alto_dwell": {
            "diagnostico": (
                f"'{zone_label}' tiene poco tráfico, pero quienes llegan sí se "
                f"detienen ({row['avg_dwell_seconds']:.1f}s de permanencia promedio). "
                f"Esto podría sugerir interés genuino en el producto, limitado "
                f"principalmente por la baja visibilidad de la zona."
            ),
            "sugerencia": (
                "Evaluar si esta zona está en un punto poco visible del recorrido. "
                "Podría beneficiarse de moverse a un pasillo con más flujo, o de "
                "señalización que dirija más tráfico hacia ella."
            ),
        },
        "bajo_trafico_bajo_dwell": {
            "diagnostico": (
                f"'{zone_label}' es una zona fría: poco tráfico y quienes pasan "
                f"no se detienen. Es la combinación menos favorable para el "
                f"espacio que ocupa."
            ),
            "sugerencia": (
                "Candidata a reubicar producto de alta rotación aquí, o a "
                "repensar completamente su función en el layout -- actualmente "
                "el espacio no está generando valor proporcional a lo que ocupa."
            ),
        },
    }

    result = templates[quadrant].copy()
    result["zone_id"] = row["zone_id"]
    result["zone_label"] = zone_label
    result["quadrant"] = quadrant
    return result


def generate_all_recommendations(summary_df: pd.DataFrame) -> list:
    if summary_df.empty:
        return []

    has_comparison = len(summary_df) > 1
    median_visits = summary_df["total_visits"].median() if has_comparison else None
    median_dwell = summary_df["avg_dwell_seconds"].median() if has_comparison else None

    recommendations = []
    for _, row in summary_df.iterrows():
        quadrant = _classify_traffic_dwell(row, median_visits, median_dwell, has_comparison)
        recommendations.append(generate_recommendation(row, quadrant))

    return recommendations


def generate_executive_summary(summary_df: pd.DataFrame, recommendations: list) -> str:
    """Un párrafo introductorio de alto nivel, para encabezar el reporte."""
    if summary_df.empty:
        return "No hay datos suficientes todavía para generar un resumen."

    n_zones = len(summary_df)
    n_calientes = sum(1 for r in recommendations if r["quadrant"] == "alto_trafico_alto_dwell")
    n_frias = sum(1 for r in recommendations if r["quadrant"] == "bajo_trafico_bajo_dwell")
    total_visits = summary_df["total_visits"].sum()

    summary = (
        f"Se analizaron {n_zones} zona(s) con un total de {total_visits} visitas registradas. "
    )
    if n_calientes > 0:
        summary += f"{n_calientes} zona(s) muestran un desempeño sólido (buen tráfico y permanencia). "
    if n_frias > 0:
        summary += f"{n_frias} zona(s) están subutilizadas y son candidatas prioritarias de revisión. "
    if n_calientes == 0 and n_frias == 0:
        summary += "El desempeño general es mixto, sin extremos claros -- revisar el detalle por zona."

    return summary


def main():
    args = parse_args()

    if not os.path.exists(args.summary):
        print(f"ERROR: no se encontró el archivo '{args.summary}'")
        return

    summary_df = pd.read_csv(args.summary)
    recommendations = generate_all_recommendations(summary_df)
    exec_summary = generate_executive_summary(summary_df, recommendations)

    print("=" * 70)
    print("RESUMEN EJECUTIVO")
    print("=" * 70)
    print(exec_summary)
    print()
    print("=" * 70)
    print("RECOMENDACIONES POR ZONA")
    print("=" * 70)
    for rec in recommendations:
        print(f"\n[{rec['zone_label']}]")
        print(f"Diagnóstico: {rec['diagnostico']}")
        print(f"Sugerencia:  {rec['sugerencia']}")


if __name__ == "__main__":
    main()