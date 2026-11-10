import json
from pathlib import Path
from urllib.request import urlopen

import pandas as pd

ANO = 2024
PASTA_PROCESSADOS = Path("dados/processados")
PASTA_PROCESSADOS.mkdir(parents=True, exist_ok=True)

# Tabela 6579: estimativas de população residente
# n6 = municípios | "in n3 42" = só os de Santa Catarina (código 42)
# v/9324 = variável população residente estimada
url = (
    "https://apisidra.ibge.gov.br/values/t/6579"
    f"/n6/in%20n3%2042/v/9324/p/{ANO}"
)

print("Consultando a API do IBGE...")
with urlopen(url, timeout=120) as resposta:
    dados = json.load(resposta)

# A primeira linha da resposta é o cabeçalho, as demais são os dados
pop = pd.DataFrame(dados[1:])
print("Colunas recebidas:", pop.columns.tolist())
print(pop.head(3))

pop = pop.rename(columns={"D1C": "cod_ibge", "D1N": "municipio", "V": "populacao"})
pop = pop[["cod_ibge", "municipio", "populacao"]]
pop["populacao"] = pd.to_numeric(pop["populacao"], errors="coerce")

# O DATASUS usa o código do município com 6 dígitos, sem o dígito verificador
pop["CODUFMUN"] = pop["cod_ibge"].str[:6]

pop.to_parquet(PASTA_PROCESSADOS / f"populacao_sc_{ANO}.parquet", index=False)
print()
print(f"{len(pop)} municípios | população total de SC: {int(pop['populacao'].sum()):,}")