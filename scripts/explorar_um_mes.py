from ftplib import FTP
from pathlib import Path

import pandas as pd
from dbfread import DBF
from pyreaddbc import readdbc

print("Funções disponíveis:", [f for f in dir(readdbc) if not f.startswith("_")])

# Pasta onde o arquivo bruto vai ficar
pasta = Path("dados/brutos")
pasta.mkdir(parents=True, exist_ok=True)

nome = "PASC2401.dbc"
destino = pasta / nome

# 1. Baixa o arquivo, se ainda não foi baixado
if not destino.exists():
    print(f"Baixando {nome}...")
    ftp = FTP("ftp.datasus.gov.br", timeout=120)
    ftp.login()
    ftp.cwd("/dissemin/publicos/SIASUS/200801_/Dados")
    with open(destino, "wb") as arquivo:
        ftp.retrbinary(f"RETR {nome}", arquivo.write)
    ftp.quit()

tamanho_mb = destino.stat().st_size / 1024 / 1024
print(f"Arquivo: {destino} ({tamanho_mb:.1f} MB)")

# 2. Descompacta o .dbc para .dbf, se ainda não foi feito
arquivo_dbf = destino.with_suffix(".dbf")
if not arquivo_dbf.exists():
    print("Descompactando .dbc para .dbf...")
    readdbc.dbc2dbf(str(destino), str(arquivo_dbf))

# 3. Lê o .dbf linha por linha e guarda só as tomografias
tabela = DBF(str(arquivo_dbf), encoding="iso-8859-1", load=False)
print("Colunas:", tabela.field_names)

registros = []
total = 0
for linha in tabela:
    total += 1
    if str(linha["PA_PROC_ID"]).startswith("0206"):
        registros.append(linha)
    if total % 500_000 == 0:
        print(f"{total:,} linhas lidas...")

tomo = pd.DataFrame(registros)
print()
print(f"Total de linhas no mês: {total:,}")
print(f"Registros de tomografia: {len(tomo):,}")
print("Procedimentos de tomografia mais frequentes:")
print(tomo["PA_PROC_ID"].value_counts().head(10))