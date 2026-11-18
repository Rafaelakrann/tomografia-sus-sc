import json
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

PASTA = Path(__file__).parent / "dados" / "processados"
AZUL, VERMELHO, CINZA, TEXTO_SUAVE = "#2a78d6", "#e34948", "#c3c2b7", "#52514e"
MESES = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]
PET_CT = "0206010095"

# Agrupamento dos 16 procedimentos de tomografia do SIGTAP por região do corpo
GRUPOS = {
    "0206010079": "Crânio", "0206010060": "Crânio",
    "0206010010": "Coluna", "0206010028": "Coluna", "0206010036": "Coluna", "0206010087": "Coluna",
    "0206010044": "Face e pescoço", "0206010052": "Face e pescoço",
    "0206020031": "Tórax", "0206020040": "Tórax",
    "0206030010": "Abdômen e pelve", "0206030037": "Abdômen e pelve",
    "0206020015": "Membros e articulações", "0206020023": "Membros e articulações",
    "0206030029": "Membros e articulações",
    "0206010095": "PET-CT",
}

st.set_page_config(page_title="Tomografia no SUS em SC", layout="wide")


# ---------- Funções auxiliares ----------
def br(valor, casas=0):
    """Formata números no padrão brasileiro: 1.234,5"""
    texto = f"{valor:,.{casas}f}"
    return texto.replace(",", "X").replace(".", ",").replace("X", ".")


def reais(valor, casas=2):
    return f"R$ {br(valor, casas)}"


def diferenca(valor, casas):
    sinal = "+" if valor >= 0 else ""
    return f"{sinal}{br(valor, casas)} vs. média SC"


def layout(fig, titulo, altura):
    """Aplica o mesmo visual a todos os gráficos."""
    fig.update_layout(title=titulo, separators=",.", height=altura,
                      margin=dict(l=10, r=10, t=60, b=10),
                      plot_bgcolor="white", xaxis=dict(gridcolor="#e1e0d9"))
    return fig


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


# ---------- Carga dos dados ----------
@st.cache_data
def carregar_dados():
    indicadores = pd.read_csv(PASTA / "indicadores_por_regiao_2024.csv", encoding="utf-8-sig")
    mapa = pd.read_parquet(PASTA / "municipio_regiao_saude_oficial.parquet")[["CODUFMUN", "regiao_saude"]]

    sia = pd.concat(
        [pd.read_parquet(arquivo) for arquivo in sorted(PASTA.glob("tomografias_PASC24*.parquet"))],
        ignore_index=True,
    )
    for coluna in ["PA_CMP", "PA_MUNPCN", "PA_UFMUN", "PA_CODUNI", "PA_PROC_ID"]:
        sia[coluna] = sia[coluna].astype(str).str.strip()
    sia = sia[sia["PA_CMP"].str.startswith("2024")]

    # Série mensal por região de residência
    por_regiao = sia.merge(mapa, left_on="PA_MUNPCN", right_on="CODUFMUN", how="inner")
    mensal = por_regiao.groupby(["regiao_saude", "PA_CMP"], as_index=False)["PA_QTDAPR"].sum()

    # Série mensal e fluxos por município (de onde o paciente mora para onde fez o exame)
    mensal_mun = sia.groupby(["PA_MUNPCN", "PA_CMP"], as_index=False)["PA_QTDAPR"].sum()
    fluxos = sia.groupby(["PA_MUNPCN", "PA_UFMUN"], as_index=False)["PA_QTDAPR"].sum()

    # Tomógrafos cadastrados por município em dezembro de 2024
    tc = pd.read_parquet(PASTA / "tomografos_cnes_24.parquet")
    for coluna in ["COMPETEN", "CODUFMUN"]:
        tc[coluna] = tc[coluna].astype(str).str.strip()
    tc_mun = tc[tc["COMPETEN"] == "202412"].groupby("CODUFMUN")["QT_EXIST"].sum().rename("tomografos")

    # Tabela de municípios
    pop = pd.read_parquet(PASTA / "populacao_sc_2024.parquet")[["cod_ibge", "CODUFMUN", "municipio", "populacao"]]
    pop = pop.rename(columns={"populacao": "populacao_mun"})
    pop["municipio"] = pop["municipio"].str.replace(" - SC", "")

    municipios = pop.merge(mapa, on="CODUFMUN").merge(indicadores, on="regiao_saude")
    municipios = municipios.join(sia.groupby("PA_MUNPCN")["PA_QTDAPR"].sum().rename("exames_residentes_mun"), on="CODUFMUN")
    municipios = municipios.join(sia.groupby("PA_UFMUN")["PA_QTDAPR"].sum().rename("exames_realizados_mun"), on="CODUFMUN")
    municipios = municipios.join(tc_mun, on="CODUFMUN")
    colunas = ["exames_residentes_mun", "exames_realizados_mun", "tomografos"]
    municipios[colunas] = municipios[colunas].fillna(0)
    municipios["por_mil_mun"] = municipios["exames_residentes_mun"] / municipios["populacao_mun"] * 1000

    # Custo para o SUS por região de residência
    custo = por_regiao.groupby("regiao_saude")[["PA_QTDAPR", "PA_VALAPR"]].sum()
    custo = custo.join(indicadores.set_index("regiao_saude")["populacao"]).reset_index()
    custo["gasto_por_hab"] = custo["PA_VALAPR"] / custo["populacao"]
    custo["valor_medio"] = custo["PA_VALAPR"] / custo["PA_QTDAPR"]

    # Tipos de exame por região de residência, com os nomes do SIGTAP
    procs = pd.read_csv(PASTA / "procedimentos_tomografia.csv", dtype=str, encoding="utf-8-sig")
    tipos = por_regiao.merge(procs, left_on="PA_PROC_ID", right_on="CO_PROCEDIMENTO", how="left")
    tipos["grupo"] = tipos["PA_PROC_ID"].map(GRUPOS).fillna("Outros")
    tipos = tipos.groupby(["regiao_saude", "grupo"], as_index=False)["PA_QTDAPR"].sum()

    # Produtividade: exames por tomógrafo nos estabelecimentos com tomógrafo que produziram pelo SUS
    tc["CNES"] = tc["CNES"].astype(str).str.strip()
    tc_estab = tc[tc["COMPETEN"] == "202412"].groupby(["CNES", "CODUFMUN"], as_index=False)["QT_EXIST"].sum()
    sem_pet = sia[sia["PA_PROC_ID"] != PET_CT]          # PET-CT usa outro equipamento
    tc_estab["exames"] = tc_estab["CNES"].map(sem_pet.groupby("PA_CODUNI")["PA_QTDAPR"].sum()).fillna(0)
    tc_estab = tc_estab[tc_estab["exames"] > 0].merge(mapa, on="CODUFMUN", how="left")
    produtividade = tc_estab.groupby("regiao_saude", as_index=False)[["exames", "QT_EXIST"]].sum()
    produtividade["exames_por_tc"] = produtividade["exames"] / produtividade["QT_EXIST"]
    pct_fora = 1 - tc_estab["exames"].sum() / sem_pet["PA_QTDAPR"].sum()

    geo = ajustar_orientacao(json.loads((PASTA / "municipios_sc.geojson").read_text(encoding="utf-8")))
    return indicadores, mensal, geo, municipios, mensal_mun, fluxos, custo, tipos, produtividade, pct_fora


(indicadores, mensal, geo, municipios, mensal_mun, fluxos,
 custo, tipos, produtividade, pct_fora) = carregar_dados()

# ---------- Barra lateral ----------
st.sidebar.header("Filtro")
regioes = sorted(indicadores["regiao_saude"])
escolha = st.sidebar.selectbox("Região de saúde de residência", ["Todas as regiões"] + regioes)
todas = escolha == "Todas as regiões"
lista = municipios if todas else municipios[municipios["regiao_saude"] == escolha]
cidade = st.sidebar.selectbox("Município de residência", ["Nenhum"] + sorted(lista["municipio"]))
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
col1.metric("Tomografias SUS de residentes em 2024", br(exames))
col2.metric("Exames por mil habitantes", br(taxa_exames, 1),
            None if todas else diferenca(taxa_exames - media_exames, 1))
col3.metric("Tomógrafos cadastrados (dez/2024)", br(selecao["QT_EXIST"].sum()))
col4.metric("Tomógrafos SUS por 100 mil hab.", br(taxa_tc_sus, 2),
            None if todas else diferenca(taxa_tc_sus - media_tc_sus, 2))

# ---------- Detalhe do município ----------
if cidade != "Nenhum":
    m = municipios[municipios["municipio"] == cidade].iloc[0]
    st.subheader(f"{cidade} · {m['regiao_saude']}")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Tomografias SUS de residentes", br(m["exames_residentes_mun"]))
    c2.metric("Exames por mil habitantes", br(m["por_mil_mun"], 1),
              diferenca(m["por_mil_mun"] - media_exames, 1))
    c3.metric("Exames realizados no município", br(m["exames_realizados_mun"]))
    c4.metric("Tomógrafos cadastrados (dez/2024)", br(m["tomografos"]))

    if m["populacao_mun"] < 10_000:
        st.info(f"{cidade} tem {br(m['populacao_mun'])} habitantes. Em municípios pequenos, "
                "poucos exames mudam muito a taxa por mil habitantes.")

    if m["exames_residentes_mun"] == 0:
        st.warning(f"Não há tomografias SUS registradas para residentes de {cidade} em 2024.")
    else:
        esquerda_mun, direita_mun = st.columns(2)

        # Para onde os moradores foram fazer tomografia
        destinos = fluxos[fluxos["PA_MUNPCN"] == m["CODUFMUN"]].merge(
            municipios[["CODUFMUN", "municipio"]], left_on="PA_UFMUN", right_on="CODUFMUN", how="left")
        destinos["municipio"] = destinos["municipio"].fillna("Fora de SC")
        destinos = destinos.groupby("municipio")["PA_QTDAPR"].sum()
        total_destinos = destinos.sum()
        destinos = destinos.sort_values().tail(10)
        fig = go.Figure(go.Bar(
            x=destinos.values, y=destinos.index, orientation="h",
            marker_color=[AZUL if nome == cidade else CINZA for nome in destinos.index],
            customdata=destinos.values / total_destinos * 100,
            hovertemplate="%{y}: %{x:,.0f} exames (%{customdata:.1f}%)<extra></extra>",
        ))
        esquerda_mun.plotly_chart(layout(fig, "Onde os moradores fizeram tomografia (10 principais)", 420))

        # Evolução mensal dos residentes
        meses_2024 = [f"2024{mes:02d}" for mes in range(1, 13)]
        serie_mun = (mensal_mun[mensal_mun["PA_MUNPCN"] == m["CODUFMUN"]]
                     .set_index("PA_CMP")["PA_QTDAPR"].reindex(meses_2024, fill_value=0))
        fig = go.Figure(go.Scatter(
            x=MESES, y=serie_mun.values, mode="lines+markers", line=dict(color=AZUL, width=2),
            hovertemplate="%{x}: %{y:,.0f} exames<extra></extra>",
        ))
        fig = layout(fig, "Tomografias SUS de residentes por mês", 420)
        fig.update_yaxes(rangemode="tozero", gridcolor="#e1e0d9")
        direita_mun.plotly_chart(fig)

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

# ---------- Desigualdade entre regiões ----------
st.subheader("Desigualdade entre regiões de saúde")
taxas = indicadores["residentes_por_mil"]
media_regioes = taxas.mean()
desvio = taxas.std()
d1, d2, d3, d4 = st.columns(4)
d1.metric("Mediana entre as regiões", br(taxas.median(), 1))
d2.metric("Desvio padrão", br(desvio, 1))
d3.metric("Coeficiente de variação", f"{br(desvio / media_regioes * 100, 1)}%")
d4.metric("Maior taxa ÷ menor taxa", f"{br(taxas.max() / taxas.min(), 1)} vezes")
st.caption("Calculado sobre as taxas de tomografias SUS por mil habitantes das 17 regiões. "
           "O coeficiente de variação é o desvio padrão dividido pela média das regiões: "
           "quanto maior, mais desiguais são as regiões entre si.")

# ---------- Custo e tipos de exame ----------
st.subheader("Custo para o SUS e tipos de exame")
sel_custo = custo if todas else custo[custo["regiao_saude"] == escolha]
gasto_total = sel_custo["PA_VALAPR"].sum()
gasto_hab = gasto_total / sel_custo["populacao"].sum()
valor_medio = gasto_total / sel_custo["PA_QTDAPR"].sum()
media_gasto_hab = custo["PA_VALAPR"].sum() / custo["populacao"].sum()
media_valor = custo["PA_VALAPR"].sum() / custo["PA_QTDAPR"].sum()

k1, k2, k3 = st.columns(3)
k1.metric("Valor aprovado pelo SUS em 2024", reais(gasto_total, 0))
k2.metric("Gasto por habitante", reais(gasto_hab),
          None if todas else diferenca(gasto_hab - media_gasto_hab, 2))
k3.metric("Valor médio por exame", reais(valor_medio),
          None if todas else diferenca(valor_medio - media_valor, 2))

esquerda_custo, direita_tipos = st.columns(2)

dados = custo.sort_values("gasto_por_hab")
cores = [AZUL if todas or nome == escolha else CINZA for nome in dados["regiao_saude"]]
fig = go.Figure(go.Bar(
    x=dados["gasto_por_hab"], y=dados["regiao_saude"], orientation="h", marker_color=cores,
    hovertemplate="%{y}: R$ %{x:,.2f} por habitante<extra></extra>",
))
fig.add_vline(x=media_gasto_hab, line_dash="dash", line_color=TEXTO_SUAVE,
              annotation_text=f"Média SC: {reais(media_gasto_hab)}", annotation_position="top")
esquerda_custo.plotly_chart(layout(fig, "Gasto SUS com tomografia por habitante (R$)", 540))

sel_tipos = tipos if todas else tipos[tipos["regiao_saude"] == escolha]
dist = sel_tipos.groupby("grupo")["PA_QTDAPR"].sum().sort_values()
fig = go.Figure(go.Bar(
    x=dist.values / dist.sum() * 100, y=dist.index, orientation="h", marker_color=AZUL,
    customdata=dist.values,
    hovertemplate="%{y}: %{x:.1f}% (%{customdata:,.0f} exames)<extra></extra>",
))
direita_tipos.plotly_chart(layout(fig, f"Tipos de tomografia (% dos exames): {escolha}", 540))

# ---------- Produtividade dos tomógrafos ----------
st.subheader("Produtividade dos tomógrafos")
media_prod = produtividade["exames"].sum() / produtividade["QT_EXIST"].sum()
dados = produtividade.sort_values("exames_por_tc")
cores = [AZUL if todas or nome == escolha else CINZA for nome in dados["regiao_saude"]]
fig = go.Figure(go.Bar(
    x=dados["exames_por_tc"], y=dados["regiao_saude"], orientation="h", marker_color=cores,
    customdata=dados["QT_EXIST"],
    hovertemplate="%{y}: %{x:,.0f} exames por tomógrafo (%{customdata} tomógrafos)<extra></extra>",
))
fig.add_vline(x=media_prod, line_dash="dash", line_color=TEXTO_SUAVE,
              annotation_text=f"Média SC: {br(media_prod)}", annotation_position="top")
st.plotly_chart(layout(fig, "Tomografias SUS ambulatoriais por tomógrafo em 2024", 540))
st.caption(f"Considera os estabelecimentos com tomógrafo cadastrado em dez/2024 que registraram produção SUS, "
           f"e os exames realizados nesses estabelecimentos, por região onde ficam. Exames de PET-CT foram excluídos, "
           f"porque usam outro equipamento. {br(pct_fora * 100, 1)}% da produção SUS veio de estabelecimentos "
           f"sem tomógrafo cadastrado e não entra neste cálculo. Internações não estão incluídas, "
           f"então a produtividade real dos equipamentos é maior.")

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
- **Custo:** soma do valor aprovado (`PA_VALAPR`) pelo SUS para os exames ambulatoriais, por região de residência.
- **Tipos de exame:** procedimentos agrupados por região do corpo, com os nomes oficiais do SIGTAP (dez/2024).
  O PET-CT faz parte do mesmo subgrupo, mas usa outro equipamento.
- **Limitações:** só inclui a produção ambulatorial (o SIH, das internações, não entra) e não inclui exames
  pagos por planos de saúde ou particulares.
""")