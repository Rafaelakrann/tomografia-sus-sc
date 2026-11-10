from ftplib import FTP
from pathlib import Path

import pandas as pd
from dbfread import DBF
from pyreaddbc import readdbc

ANO = 24
UF = "SC"
APAGAR_BRUTOS = True

PASTA_BRUTOS = Path("dados/brutos")
PASTA_PROCESSADOS = Path("dados/processados")
PASTA_BRUTOS.mkdir(parents=True, exist_ok=True)
PASTA_PROCESSADOS.mkdir(parents=True, exist_ok=True)

PASTA_FTP = "/dissemin/publicos/CNES/200508_/Dados/EQ"
COLUNAS = ["COMPETEN", "CNES", "CODUFMUN", "REGSAUDE", "QT_EXIST", "QT_USO", "IND_SUS", "IND_NSUS"]


def conectar():
    ftp = FTP("ftp.datasus.gov.br", timeout=120)
    ftp.login()
    ftp.cwd(PASTA_FTP)
    return ftp


def ler_mes(nome):
    destino = PASTA_BRUTOS / nome
    if not destino.exists():
        print(f"  Baixando {nome}...")
        ftp = conectar()
        with open(destino, "wb") as arquivo:
            ftp.retrbinary(f"RETR {nome}", arquivo.write)
        ftp.quit()

    arquivo_dbf = destino.with_suffix(".dbf")
    if not arquivo_dbf.exists():
        readdbc.dbc2dbf(str(destino), str(arquivo_dbf))

    eq = pd.DataFrame(iter(DBF(str(arquivo_dbf), encoding="iso-8859-1")))

    if APAGAR_BRUTOS:
        destino.unlink(missing_ok=True)
        arquivo_dbf.unlink(missing_ok=True)
    return eq


def main():
    ftp = conectar()
    arquivos = sorted(ftp.nlst(f"EQ{UF}{ANO}*"))
    ftp.quit()
    print(f"{len(arquivos)} arquivos encontrados")

    tomografos = []
    municipios = []

    for nome in arquivos:
        print(f"{nome}:")
        eq = ler_mes(nome)

        # Padroniza os códigos como texto, sem espaços
        eq["TIPEQUIP"] = eq["TIPEQUIP"].astype(str).str.strip()
        eq["CODEQUIP"] = eq["CODEQUIP"].astype(str).str.strip().str.zfill(2)

        # Guarda a relação município -> região de saúde
        municipios.append(eq[["CODUFMUN", "REGSAUDE"]].drop_duplicates())

        # Filtra só os tomógrafos computadorizados (tipo 1, código 11)
        tc = eq[(eq["TIPEQUIP"] == "1") & (eq["CODEQUIP"] == "11")][COLUNAS].copy()
        for coluna in ["QT_EXIST", "QT_USO", "IND_SUS", "IND_NSUS"]:
            tc[coluna] = pd.to_numeric(tc[coluna], errors="coerce").fillna(0)

        print(f"  {len(tc)} estabelecimentos | {int(tc['QT_EXIST'].sum())} tomógrafos existentes")
        tomografos.append(tc)

    pd.concat(tomografos).to_parquet(PASTA_PROCESSADOS / f"tomografos_cnes_{ANO}.parquet", index=False)

    mapa = pd.concat(municipios).drop_duplicates()
    mapa.to_parquet(PASTA_PROCESSADOS / "municipio_regiao_saude.parquet", index=False)

    print("Extração concluída!")


if __name__ == "__main__":
    main()