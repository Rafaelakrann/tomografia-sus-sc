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
    # PET-CT (0206010095) é do mesmo subgrupo, mas usa outro equipamento: fica fora de todas as análises
    sia = sia[sia["PA_PROC_ID"] != PET_CT].copy()
    sia["grupo"] = sia["PA_PROC_ID"].map(GRUPOS).fillna("Outros")

    # Região de residência e região onde o exame foi feito
    regiao_mun = mapa.set_index("CODUFMUN")["regiao_saude"]
    sia["regiao_residencia"] = sia["PA_MUNPCN"].map(regiao_mun)
    sia["regiao_atendimento"] = sia["PA_UFMUN"].map(regiao_mun)
    por_regiao = sia.dropna(subset=["regiao_residencia"])

    # Recalcula os indicadores de acesso já sem o PET-CT
    indicadores = indicadores.set_index("regiao_saude")
    indicadores["exames_residentes"] = por_regiao.groupby("regiao_residencia")["PA_QTDAPR"].sum()
    realizados = sia.dropna(subset=["regiao_atendimento"]).groupby("regiao_atendimento")["PA_QTDAPR"].sum()
    indicadores["saldo"] = realizados - indicadores["exames_residentes"]
    indicadores["residentes_por_mil"] = indicadores["exames_residentes"] / indicadores["populacao"] * 1000
    indicadores = indicadores.fillna({"exames_residentes": 0, "saldo": 0}).reset_index()

    # ===== Indicadores por REGIÃO (aba 1) =====
    mensal = por_regiao.groupby(["regiao_residencia", "PA_CMP"], as_index=False)["PA_QTDAPR"].sum()

    custo = por_regiao.groupby("regiao_residencia")[["PA_QTDAPR", "PA_VALAPR"]].sum()
    custo = custo.join(indicadores.set_index("regiao_saude")["populacao"])
    custo.index.name = "regiao_saude"
    custo = custo.reset_index()
    custo["gasto_por_hab"] = custo["PA_VALAPR"] / custo["populacao"]
    custo["valor_medio"] = custo["PA_VALAPR"] / custo["PA_QTDAPR"]

    tipos = por_regiao.groupby(["regiao_residencia", "grupo"], as_index=False)["PA_QTDAPR"].sum()

    # Percentual dos exames dos residentes feitos na própria região
    propria = por_regiao[por_regiao["regiao_residencia"] == por_regiao["regiao_atendimento"]]
    propria_regiao = (propria.groupby("regiao_residencia")["PA_QTDAPR"].sum()
                      / por_regiao.groupby("regiao_residencia")["PA_QTDAPR"].sum() * 100)

    # Produtividade: exames por tomógrafo nos estabelecimentos com tomógrafo que produziram pelo SUS
    tc = pd.read_parquet(PASTA / "tomografos_cnes_24.parquet")
    for coluna in ["COMPETEN", "CODUFMUN", "CNES"]:
        tc[coluna] = tc[coluna].astype(str).str.strip()
    tc_dez = tc[tc["COMPETEN"] == "202412"]
    tc_estab = tc_dez.groupby(["CNES", "CODUFMUN"], as_index=False)["QT_EXIST"].sum()
    tc_estab["exames"] = tc_estab["CNES"].map(sia.groupby("PA_CODUNI")["PA_QTDAPR"].sum()).fillna(0)
    tc_estab = tc_estab[tc_estab["exames"] > 0].merge(mapa, on="CODUFMUN", how="left")
    produtividade = tc_estab.groupby("regiao_saude", as_index=False)[["exames", "QT_EXIST"]].sum()
    produtividade["exames_por_tc"] = produtividade["exames"] / produtividade["QT_EXIST"]
    pct_fora = 1 - tc_estab["exames"].sum() / sia["PA_QTDAPR"].sum()

    # ===== Indicadores por MUNICÍPIO (aba 2) =====
    mensal_mun = sia.groupby(["PA_MUNPCN", "PA_CMP"], as_index=False)["PA_QTDAPR"].sum()
    fluxos = sia.groupby(["PA_MUNPCN", "PA_UFMUN"], as_index=False)["PA_QTDAPR"].sum()
    tipos_mun = sia.groupby(["PA_MUNPCN", "grupo"], as_index=False)["PA_QTDAPR"].sum()

    pop = pd.read_parquet(PASTA / "populacao_sc_2024.parquet")[["cod_ibge", "CODUFMUN", "municipio", "populacao"]]
    pop = pop.rename(columns={"populacao": "populacao_mun"})
    pop["municipio"] = pop["municipio"].str.replace(" - SC", "")

    municipios = pop.merge(mapa, on="CODUFMUN").merge(indicadores, on="regiao_saude")
    residentes = sia.groupby("PA_MUNPCN")[["PA_QTDAPR", "PA_VALAPR"]].sum()
    residentes.columns = ["exames_residentes_mun", "valor_residentes_mun"]
    no_proprio = sia[sia["PA_MUNPCN"] == sia["PA_UFMUN"]].groupby("PA_MUNPCN")["PA_QTDAPR"].sum()
    prod_mun = tc_estab.groupby("CODUFMUN")[["exames", "QT_EXIST"]].sum()

    municipios = municipios.join(residentes, on="CODUFMUN")
    municipios = municipios.join(no_proprio.rename("exames_no_proprio_mun"), on="CODUFMUN")
    municipios = municipios.join(sia.groupby("PA_UFMUN")["PA_QTDAPR"].sum().rename("exames_realizados_mun"), on="CODUFMUN")
    municipios = municipios.join(tc_dez.groupby("CODUFMUN")["QT_EXIST"].sum().rename("tomografos"), on="CODUFMUN")
    municipios = municipios.join(prod_mun.rename(columns={"exames": "exames_tc_mun", "QT_EXIST": "tc_produtivos_mun"}),
                                 on="CODUFMUN")
    colunas = ["exames_residentes_mun", "valor_residentes_mun", "exames_no_proprio_mun", "exames_realizados_mun",
               "tomografos", "exames_tc_mun", "tc_produtivos_mun"]
    municipios[colunas] = municipios[colunas].fillna(0)
    municipios["por_mil_mun"] = municipios["exames_residentes_mun"] / municipios["populacao_mun"] * 1000

    geo = ajustar_orientacao(json.loads((PASTA / "municipios_sc.geojson").read_text(encoding="utf-8")))
    return (indicadores, geo, mensal, custo, tipos, propria_regiao, produtividade, pct_fora,
            municipios, mensal_mun, fluxos, tipos_mun)


(indicadores, geo, mensal, custo, tipos, propria_regiao, produtividade, pct_fora,
 municipios, mensal_mun, fluxos, tipos_mun) = carregar_dados()

# Médias de Santa Catarina, usadas como referência nas duas abas
total_sc = indicadores[["exames_residentes", "populacao", "QT_SUS_AJUST"]].sum()
media_exames = total_sc["exames_residentes"] / total_sc["populacao"] * 1000
media_tc_sus = total_sc["QT_SUS_AJUST"] / total_sc["populacao"] * 100_000
media_gasto_hab = custo["PA_VALAPR"].sum() / custo["populacao"].sum()
media_valor = custo["PA_VALAPR"].sum() / custo["PA_QTDAPR"].sum()
media_prod = produtividade["exames"].sum() / produtividade["QT_EXIST"].sum()


def grafico_tipos(dados, titulo):
    """Barras com o percentual de exames por grupo de procedimento."""
    dist = dados.groupby("grupo")["PA_QTDAPR"].sum().sort_values()
    fig = go.Figure(go.Bar(
        x=dist.values / dist.sum() * 100, y=dist.index, orientation="h", marker_color=AZUL,
        customdata=dist.values,
        hovertemplate="%{y}: %{x:.1f}% (%{customdata:,.0f} exames)<extra></extra>",
    ))
    return layout(fig, titulo, 420)


# ---------- Barra lateral ----------
st.sidebar.header("Filtros")
regioes = sorted(indicadores["regiao_saude"])
escolha = st.sidebar.selectbox("Região de saúde de residência", ["Todas as regiões"] + regioes)
todas = escolha == "Todas as regiões"
lista = municipios if todas else municipios[municipios["regiao_saude"] == escolha]
cidade = st.sidebar.selectbox("Município de residência", ["Nenhum"] + sorted(lista["municipio"]))
if cidade != "Nenhum":
    st.sidebar.success("Abra a aba **Município** para ver todos os indicadores da cidade.")
st.sidebar.markdown("[Código e metodologia no GitHub](https://github.com/Rafaelakrann/tomografia-sus-sc)")

# ---------- Cabeçalho ----------
st.title("Acesso à tomografia no SUS em Santa Catarina, 2024")
st.caption("Tomografias computadorizadas ambulatoriais realizadas pelo SUS, por local de residência do paciente, "
           "e tomógrafos cadastrados no CNES. PET-CT não incluído. Fontes: DATASUS (SIA, CNES e SIGTAP) e IBGE.")

aba_geral, aba_mun = st.tabs(["Santa Catarina e regiões", "Município"])

# =====================================================================
# ABA 1: SANTA CATARINA E REGIÕES
# =====================================================================
with aba_geral:
    st.caption(f"Recorte: **{escolha}**. Use o filtro de região na barra lateral.")

    # ---------- Acesso ----------
    st.subheader("Acesso")
    selecao = indicadores if todas else indicadores[indicadores["regiao_saude"] == escolha]
    populacao = selecao["populacao"].sum()
    exames = selecao["exames_residentes"].sum()
    taxa_exames = exames / populacao * 1000
    taxa_tc_sus = selecao["QT_SUS_AJUST"].sum() / populacao * 100_000

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Tomografias SUS de residentes", br(exames))
    col2.metric("Exames por mil habitantes", br(taxa_exames, 1),
                None if todas else diferenca(taxa_exames - media_exames, 1))
    col3.metric("Tomógrafos cadastrados (dez/2024)", br(selecao["QT_EXIST"].sum()))
    col4.metric("Tomógrafos SUS por 100 mil hab.", br(taxa_tc_sus, 2),
                None if todas else diferenca(taxa_tc_sus - media_tc_sus, 2))

    # ---------- Mapa ----------
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

    recorte = mensal if todas else mensal[mensal["regiao_residencia"] == escolha]
    serie = recorte.groupby("PA_CMP")["PA_QTDAPR"].sum().sort_index()
    fig = go.Figure(go.Scatter(
        x=[MESES[int(cmp[4:]) - 1] for cmp in serie.index], y=serie.values,
        mode="lines+markers", line=dict(color=AZUL, width=2),
        hovertemplate="%{x}: %{y:,.0f} exames<extra></extra>",
    ))
    fig = layout(fig, f"Tomografias SUS de residentes por mês: {escolha}", 360)
    fig.update_yaxes(rangemode="tozero", gridcolor="#e1e0d9")
    st.plotly_chart(fig)

    # ---------- Custo e tipos de exame ----------
    st.subheader("Custo para o SUS e tipos de exame")
    sel_custo = custo if todas else custo[custo["regiao_saude"] == escolha]
    gasto_total = sel_custo["PA_VALAPR"].sum()
    gasto_hab = gasto_total / sel_custo["populacao"].sum()
    valor_medio = gasto_total / sel_custo["PA_QTDAPR"].sum()

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

    sel_tipos = tipos if todas else tipos[tipos["regiao_residencia"] == escolha]
    direita_tipos.plotly_chart(grafico_tipos(sel_tipos, f"Tipos de tomografia (% dos exames): {escolha}"))

    # ---------- Produtividade dos tomógrafos ----------
    st.subheader("Produtividade dos tomógrafos")
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
               f"pela região onde ficam. {br(pct_fora * 100, 1)}% da produção SUS veio de estabelecimentos sem tomógrafo cadastrado e "
               f"não entra neste cálculo. Internações não estão incluídas.")

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

    # ---------- Tabela ----------
    st.subheader("Indicadores por região de saúde")
    tabela = indicadores.merge(custo[["regiao_saude", "gasto_por_hab", "valor_medio"]], on="regiao_saude")
    tabela["propria_regiao"] = tabela["regiao_saude"].map(propria_regiao)
    tabela = tabela.rename(columns={
        "regiao_saude": "Região de saúde",
        "QT_EXIST": "Tomógrafos",
        "QT_SUS_AJUST": "Tomógrafos SUS",
        "populacao": "População",
        "tc_sus_ajust_por_100mil": "Tomógrafos SUS por 100 mil hab.",
        "exames_residentes": "Tomografias SUS (residentes)",
        "residentes_por_mil": "Exames por mil hab.",
        "saldo": "Saldo de exames",
        "gasto_por_hab": "Gasto por habitante (R$)",
        "valor_medio": "Valor médio por exame (R$)",
        "propria_regiao": "Feitos na própria região (%)",
    }).drop(columns=["tc_sus_por_100mil", "tc_por_100mil", "QT_SUS"], errors="ignore")
    tabela = tabela.sort_values("Exames por mil hab.", ascending=False)
    st.dataframe(tabela, hide_index=True, column_config={
        "Tomógrafos SUS por 100 mil hab.": st.column_config.NumberColumn(format="%.2f"),
        "Exames por mil hab.": st.column_config.NumberColumn(format="%.1f"),
        "Gasto por habitante (R$)": st.column_config.NumberColumn(format="%.2f"),
        "Valor médio por exame (R$)": st.column_config.NumberColumn(format="%.2f"),
        "Feitos na própria região (%)": st.column_config.NumberColumn(format="%.1f"),
    })

# =====================================================================
# ABA 2: MUNICÍPIO
# =====================================================================
with aba_mun:
    if cidade == "Nenhum":
        st.info("Escolha um município na barra lateral para ver todos os indicadores dele.")
    else:
        m = municipios[municipios["municipio"] == cidade].iloc[0]
        regiao = m["regiao_saude"]
        exames_mun = m["exames_residentes_mun"]
        st.header(cidade)
        st.caption(f"Região de saúde: **{regiao}** · População estimada em 2024: "
                   f"{br(m['populacao_mun'])} habitantes")
        if m["populacao_mun"] < 10_000:
            st.info("Em municípios pequenos, poucos exames mudam muito as taxas por habitante.")

        # ---------- Acesso ----------
        st.subheader("Acesso")
        pct_proprio = m["exames_no_proprio_mun"] / exames_mun * 100 if exames_mun else 0
        a1, a2, a3, a4 = st.columns(4)
        a1.metric("Tomografias SUS de residentes", br(exames_mun))
        a2.metric("Exames por mil habitantes", br(m["por_mil_mun"], 1),
                  diferenca(m["por_mil_mun"] - media_exames, 1))
        a3.metric("Feitos no próprio município", f"{br(pct_proprio, 1)}%" if exames_mun else "—")
        a4.metric("Exames realizados no município", br(m["exames_realizados_mun"]))
        st.caption("\"Exames realizados no município\" inclui pacientes de outras cidades atendidos ali.")

        if exames_mun == 0:
            st.warning(f"Não há tomografias SUS registradas para residentes de {cidade} em 2024.")
        else:
            # ---------- Custo ----------
            st.subheader("Custo para o SUS")
            gasto_hab_mun = m["valor_residentes_mun"] / m["populacao_mun"]
            valor_medio_mun = m["valor_residentes_mun"] / exames_mun
            b1, b2, b3 = st.columns(3)
            b1.metric("Valor aprovado pelo SUS em 2024", reais(m["valor_residentes_mun"], 0))
            b2.metric("Gasto por habitante", reais(gasto_hab_mun),
                      diferenca(gasto_hab_mun - media_gasto_hab, 2))
            b3.metric("Valor médio por exame", reais(valor_medio_mun),
                      diferenca(valor_medio_mun - media_valor, 2))

        # ---------- Tomógrafos ----------
        st.subheader("Tomógrafos no município")
        e1, e2 = st.columns(2)
        e1.metric("Tomógrafos cadastrados (dez/2024)", br(m["tomografos"]))
        if m["tc_produtivos_mun"] > 0:
            prod_mun = m["exames_tc_mun"] / m["tc_produtivos_mun"]
            e2.metric("Tomografias SUS por tomógrafo em 2024", br(prod_mun),
                      f"{'+' if prod_mun >= media_prod else ''}{br(prod_mun - media_prod)} vs. média SC")
        else:
            e2.metric("Tomografias SUS por tomógrafo em 2024", "—")
            st.caption("O município não tem tomógrafo cadastrado com produção SUS ambulatorial em 2024.")

        if exames_mun > 0:
            # ---------- Comparação ----------
            st.subheader("Comparação com a região e o estado")
            reg_ind = indicadores.set_index("regiao_saude").loc[regiao]
            reg_custo = custo.set_index("regiao_saude").loc[regiao]
            comparacao = pd.DataFrame({
                "Indicador": ["Exames por mil habitantes", "Gasto por habitante (R$)",
                              "Valor médio por exame (R$)", "Exames feitos no próprio território (%)"],
                cidade: [br(m["por_mil_mun"], 1), br(gasto_hab_mun, 2), br(valor_medio_mun, 2),
                         br(pct_proprio, 1)],
                regiao: [br(reg_ind["residentes_por_mil"], 1), br(reg_custo["gasto_por_hab"], 2),
                         br(reg_custo["valor_medio"], 2), br(propria_regiao.get(regiao, 0), 1)],
                "Santa Catarina": [br(media_exames, 1), br(media_gasto_hab, 2), br(media_valor, 2), "—"],
            })
            st.dataframe(comparacao, hide_index=True)
            st.caption("No território: para o município, exames feitos na própria cidade; "
                       "para a região, exames feitos na própria região de saúde.")

            # ---------- Destinos e tipos de exame ----------
            esquerda_mun, direita_mun = st.columns(2)
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

            sel_tipos_mun = tipos_mun[tipos_mun["PA_MUNPCN"] == m["CODUFMUN"]]
            direita_mun.plotly_chart(grafico_tipos(sel_tipos_mun, f"Tipos de tomografia (% dos exames): {cidade}"))

            # ---------- Evolução mensal ----------
            meses_2024 = [f"2024{mes:02d}" for mes in range(1, 13)]
            serie_mun = (mensal_mun[mensal_mun["PA_MUNPCN"] == m["CODUFMUN"]]
                         .set_index("PA_CMP")["PA_QTDAPR"].reindex(meses_2024, fill_value=0))
            fig = go.Figure(go.Scatter(
                x=MESES, y=serie_mun.values, mode="lines+markers", line=dict(color=AZUL, width=2),
                hovertemplate="%{x}: %{y:,.0f} exames<extra></extra>",
            ))
            fig = layout(fig, f"Tomografias SUS de residentes por mês: {cidade}", 360)
            fig.update_yaxes(rangemode="tozero", gridcolor="#e1e0d9")
            st.plotly_chart(fig)

# ---------- Sobre os dados ----------
with st.expander("Sobre os dados, a auditoria e as limitações"):
    st.markdown("""
- **Exames:** soma da quantidade aprovada de procedimentos do subgrupo 0206 (diagnóstico por tomografia)
  no SIA/SUS, realizados em 2024, agrupados pelo município de residência do paciente. O PET-CT (0206010095)
  foi excluído de todas as análises, porque usa outro equipamento (código 18 no CNES) e tem custo muito maior.
- **Saldo:** exames realizados na região menos exames de residentes da região. Positivo indica um polo regional.
- **Tomógrafos SUS:** marcados como disponíveis ao SUS no CNES **ou** com produção SUS registrada,
  porque a auditoria encontrou tomógrafos marcados como "não SUS" que produziram pelo SUS.
- **Custo:** soma do valor aprovado (`PA_VALAPR`) pelo SUS para os exames ambulatoriais, por local de residência.
- **Tipos de exame:** os 15 procedimentos de tomografia computadorizada agrupados por região do corpo,
  com os nomes oficiais do SIGTAP (dez/2024).
- **Auditoria:** 9,8% das tomografias SUS foram registradas por estabelecimentos sem tomógrafo no CNES,
  e o campo de região de saúde do CNES é inconsistente, por isso foi usada a base territorial oficial do DATASUS.
- **Limitações:** só inclui a produção ambulatorial (o SIH, das internações, não entra) e não inclui exames
  pagos por planos de saúde ou particulares.
""")