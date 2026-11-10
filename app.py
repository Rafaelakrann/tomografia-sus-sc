import json
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

PASTA = Path(__file__).parent / "dados" / "processados"
AZUL, VERMELHO, CINZA, TEXTO_SUAVE = "#2a78d6", "#e34948", "#c3c2b7", "#52514e"
MESES = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]

st.set_page_config(page_title="Tomografia no SUS em SC", layout="wide")


def br(valor, casas=0):
    """Formata números no padrão brasileiro: 1.234,5"""
    texto = f"{valor:,.{casas}f}"
    return texto.replace(",", "X").replace(".", ",").replace("X", ".")


def diferenca(valor, casas):
    sinal = "+" if valor >= 0 else ""
    return f"{sinal}{br(valor, casas)} vs. média SC"

def area_assinada(anel):
    """Positiva se o contorno é anti-horário, negativa se é horário."""
    return sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in zip(anel, anel[1:]))


def ajustar_orientacao(geo):
    """Deixa o contorno externo em sentido horário e os buracos em anti-horário, como o Plotly espera."""
    for municipio in geo["features"]:
        geometria = municipio["geometry"]
        if geometria["type"] == "MultiPolygon":
            poligonos = geometria["coordinates"]
        else:
            poligonos = [geometria["coordinates"]]
        for poligono in poligonos:
            for posicao, anel in enumerate(poligono):
                esta_horario = area_assinada(anel) < 0
                deve_ser_horario = posicao == 0   # o primeiro anel é o contorno externo
                if esta_horario != deve_ser_horario:
                    anel.reverse()
    return geo

@st.cache_data
def carregar_dados():
    indicadores = pd.read_csv(PASTA / "indicadores_por_regiao_2024.csv", encoding="utf-8-sig")

    mapa = pd.read_parquet(PASTA / "municipio_regiao_saude_oficial.parquet")[["CODUFMUN", "regiao_saude"]]
    sia = pd.concat(
        [pd.read_parquet(arquivo) for arquivo in sorted(PASTA.glob("tomografias_PASC24*.parquet"))],
        ignore_index=True,
    )
    for coluna in ["PA_CMP", "PA_MUNPCN"]:
        sia[coluna] = sia[coluna].astype(str).str.strip()
    sia = sia[sia["PA_CMP"].str.startswith("2024")]
    sia = sia.merge(mapa, left_on="PA_MUNPCN", right_on="CODUFMUN", how="inner")
    mensal = sia.groupby(["regiao_saude", "PA_CMP"], as_index=False)["PA_QTDAPR"].sum()

    # Mapa: cada município recebe os indicadores da sua região de saúde
    geo = ajustar_orientacao(json.loads((PASTA / "municipios_sc.geojson").read_text(encoding="utf-8")))
    pop = pd.read_parquet(PASTA / "populacao_sc_2024.parquet")[["cod_ibge", "CODUFMUN", "municipio"]]
    municipios = pop.merge(mapa, on="CODUFMUN").merge(indicadores, on="regiao_saude")
    municipios["municipio"] = municipios["municipio"].str.replace(" - SC", "")

    return indicadores, mensal, geo, municipios


indicadores, mensal, geo, municipios = carregar_dados()

# ---------- Barra lateral ----------
st.sidebar.header("Filtro")
regioes = sorted(indicadores["regiao_saude"])
escolha = st.sidebar.selectbox("Região de saúde de residência", ["Todas as regiões"] + regioes)
todas = escolha == "Todas as regiões"
st.sidebar.markdown("[Código e metodologia no GitHub](https://github.com/Rafaelakrann/tomografia-sus-sc)")

# ---------- Cabeçalho ----------
st.title("Acesso à tomografia no SUS em Santa Catarina, 2024")
st.caption("Tomografias ambulatoriais realizadas pelo SUS, por região de residência do paciente, "
           "e tomógrafos cadastrados no CNES. Fontes: DATASUS (SIA e CNES) e IBGE.")

# ---------- Números principais ----------
selecao = indicadores if todas else indicadores[indicadores["regiao_saude"] == escolha]

total_sc = indicadores[["exames_residentes", "populacao", "QT_SUS_AJUST"]].sum()
media_exames = total_sc["exames_residentes"] / total_sc["populacao"] * 1000
media_tc_sus = total_sc["QT_SUS_AJUST"] / total_sc["populacao"] * 100_000

populacao = selecao["populacao"].sum()
exames = selecao["exames_residentes"].sum()
taxa_exames = exames / populacao * 1000
taxa_tc_sus = selecao["QT_SUS_AJUST"].sum() / populacao * 100_000

col1, col2, col3, col4 = st.columns(4)
col1.metric("Tomografias SUS em 2024", br(exames))
col2.metric("Exames por mil habitantes", br(taxa_exames, 1),
            None if todas else diferenca(taxa_exames - media_exames, 1))
col3.metric("Tomógrafos cadastrados (dez/2024)", br(selecao["QT_EXIST"].sum()))
col4.metric("Tomógrafos SUS por 100 mil hab.", br(taxa_tc_sus, 2),
            None if todas else diferenca(taxa_tc_sus - media_tc_sus, 2))

# ---------- Mapa ----------
st.subheader("Mapa por região de saúde")
opcoes = {
    "Exames por mil habitantes": ("residentes_por_mil", ".1f"),
    "Tomógrafos SUS por 100 mil hab.": ("tc_sus_ajust_por_100mil", ".2f"),
    "Saldo de exames (polos x dependentes)": ("saldo", ",.0f"),
}
indicador = st.radio("Indicador do mapa", list(opcoes), horizontal=True)
coluna, formato = opcoes[indicador]

if coluna == "saldo":
    escala, meio = [[0, VERMELHO], [0.5, "#f0efec"], [1, AZUL]], 0
else:
    escala, meio = ["#cde2fb", "#104281"], None

fig = px.choropleth(
    municipios, geojson=geo, locations="cod_ibge", featureidkey="properties.codarea",
    color=coluna, color_continuous_scale=escala, color_continuous_midpoint=meio,
    hover_name="municipio",
    hover_data={"regiao_saude": True, coluna: f":{formato}", "cod_ibge": False},
    labels={"regiao_saude": "Região", coluna: indicador},
)
fig.update_traces(marker_line_color="white", marker_line_width=0.3)

if not todas:
    destaque = municipios[municipios["regiao_saude"] == escolha]
    fig.add_trace(go.Choropleth(
        geojson=geo, locations=destaque["cod_ibge"], featureidkey="properties.codarea",
        z=[1] * len(destaque), colorscale=[[0, "rgba(0,0,0,0)"], [1, "rgba(0,0,0,0)"]],
        showscale=False, marker_line_color="#0b0b0b", marker_line_width=1.5, hoverinfo="skip",
    ))

fig.update_geos(fitbounds="locations", visible=False)
fig.update_layout(height=520, margin=dict(l=0, r=0, t=10, b=0), separators=",.",
                  coloraxis_colorbar=dict(title=None))
st.plotly_chart(fig)

# ---------- Gráficos por região ----------
def layout(fig, titulo, altura):
    fig.update_layout(title=titulo, separators=",.", height=altura,
                      margin=dict(l=10, r=10, t=60, b=10),
                      plot_bgcolor="white", xaxis=dict(gridcolor="#e1e0d9"))
    return fig

esquerda, direita = st.columns(2)

dados = indicadores.sort_values("residentes_por_mil")
cores = [AZUL if todas or nome == escolha else CINZA for nome in dados["regiao_saude"]]
fig = go.Figure(go.Bar(
    x=dados["residentes_por_mil"], y=dados["regiao_saude"], orientation="h", marker_color=cores,
    hovertemplate="%{y}: %{x:.1f} exames por mil hab.<extra></extra>",
))
fig.add_vline(x=media_exames, line_dash="dash", line_color=TEXTO_SUAVE,
              annotation_text=f"Média SC: {br(media_exames, 1)}", annotation_position="top")
esquerda.plotly_chart(layout(fig, "Tomografias SUS por mil habitantes", 540))

dados = indicadores.sort_values("saldo")
cores = [
    (AZUL if saldo > 0 else VERMELHO) if (todas or nome == escolha) else CINZA
    for nome, saldo in zip(dados["regiao_saude"], dados["saldo"])
]
fig = go.Figure(go.Bar(
    x=dados["saldo"], y=dados["regiao_saude"], orientation="h", marker_color=cores,
    hovertemplate="%{y}: %{x:,.0f} exames<extra></extra>",
))
direita.plotly_chart(layout(fig, "Polos (azul) e regiões dependentes (vermelho)", 540))

# ---------- Produção mensal ----------
recorte = mensal if todas else mensal[mensal["regiao_saude"] == escolha]
serie = recorte.groupby("PA_CMP")["PA_QTDAPR"].sum().sort_index()
fig = go.Figure(go.Scatter(
    x=[MESES[int(cmp[4:]) - 1] for cmp in serie.index], y=serie.values,
    mode="lines+markers", line=dict(color=AZUL, width=2),
    hovertemplate="%{x}: %{y:,.0f} exames<extra></extra>",
))
fig = layout(fig, f"Produção mensal de tomografias SUS: {escolha}", 360)
fig.update_yaxes(rangemode="tozero", gridcolor="#e1e0d9")
st.plotly_chart(fig)

# ---------- Tabela ----------
st.subheader("Indicadores por região de saúde")
tabela = indicadores.rename(columns={
    "regiao_saude": "Região de saúde",
    "QT_EXIST": "Tomógrafos",
    "QT_SUS_AJUST": "Tomógrafos SUS",
    "populacao": "População",
    "tc_sus_ajust_por_100mil": "Tomógrafos SUS por 100 mil hab.",
    "exames_residentes": "Tomografias SUS (residentes)",
    "residentes_por_mil": "Exames por mil hab.",
    "saldo": "Saldo de exames",
}).sort_values("Exames por mil hab.", ascending=False)
st.dataframe(tabela, hide_index=True, column_config={
    "Tomógrafos SUS por 100 mil hab.": st.column_config.NumberColumn(format="%.2f"),
    "Exames por mil hab.": st.column_config.NumberColumn(format="%.1f"),
})

# ---------- Sobre os dados ----------
with st.expander("Sobre os dados, a auditoria e as limitações"):
    st.markdown("""
- **Exames:** soma da quantidade aprovada de procedimentos do subgrupo 0206 (diagnóstico por tomografia)
  no SIA/SUS, realizados em 2024, agrupados pelo município de residência do paciente.
- **Saldo:** exames realizados na região menos exames de residentes da região. Positivo indica um polo regional.
- **Tomógrafos SUS:** marcados como disponíveis ao SUS no CNES **ou** com produção SUS registrada,
  porque a auditoria encontrou tomógrafos marcados como "não SUS" que produziram pelo SUS.
- **Auditoria:** 9,8% das tomografias SUS foram registradas por estabelecimentos sem tomógrafo no CNES,
  e o campo de região de saúde do CNES é inconsistente, por isso foi usada a base territorial oficial do DATASUS.
- **Limitações:** só inclui a produção ambulatorial (o SIH, das internações, não entra) e não inclui exames
  pagos por planos de saúde ou particulares.
""")