from ftplib import FTP
from pathlib import Path

import pandas as pd
from dbfread import DBF
from pyreaddbc import readdbc

ANO = 24              # 2024
UF = "SC"
APAGAR_BRUTOS = True  # apaga .dbc e .dbf depois de processar cada mês

PASTA_BRUTOS = Path("dados/brutos")
PASTA_PROCESSADOS = Path("dados/processados")
PASTA_BRUTOS.mkdir(parents=True, exist_ok=True)
PASTA_PROCESSADOS.mkdir(parents=True, exist_ok=True)

PASTA_FTP = "/dissemin/publicos/SIASUS/200801_/Dados"
COLUNAS = ["PA_CMP", "PA_CODUNI", "PA_UFMUN", "PA_MUNPCN", "PA_PROC_ID", "PA_QTDAPR", "PA_VALAPR"]
CHAVES = ["PA_CMP", "PA_CODUNI", "PA_UFMUN", "PA_MUNPCN", "PA_PROC_ID"]


def listar_arquivos():
    ftp = FTP("ftp.datasus.gov.br", timeout=120)
    ftp.login()
    ftp.cwd(PASTA_FTP)
    arquivos = sorted(ftp.nlst(f"PA{UF}{ANO}*"))
    ftp.quit()
    return arquivos


def baixar(nome):
    destino = PASTA_BRUTOS / nome
    if not destino.exists():
        print(f"  Baixando {nome}...")
        ftp = FTP("ftp.datasus.gov.br", timeout=120)
        ftp.login()
        ftp.cwd(PASTA_FTP)
        with open(destino, "wb") as arquivo:
            ftp.retrbinary(f"RETR {nome}", arquivo.write)
        ftp.quit()
    return destino


def extrair_tomografias(arquivo_dbc):
    arquivo_dbf = arquivo_dbc.with_suffix(".dbf")
    if not arquivo_dbf.exists():
        print("  Descompactando...")
        readdbc.dbc2dbf(str(arquivo_dbc), str(arquivo_dbf))

    print("  Lendo e filtrando tomografias...")
    tabela = DBF(str(arquivo_dbf), encoding="iso-8859-1", load=False)
    registros = []
    for linha in tabela:
        if str(linha["PA_PROC_ID"]).startswith("0206"):
            registros.append({coluna: linha[coluna] for coluna in COLUNAS})

    tomo = pd.DataFrame(registros, columns=COLUNAS)
    tomo["PA_QTDAPR"] = pd.to_numeric(tomo["PA_QTDAPR"], errors="coerce").fillna(0)
    tomo["PA_VALAPR"] = pd.to_numeric(tomo["PA_VALAPR"], errors="coerce").fillna(0)

    resumo = (
        tomo.groupby(CHAVES, as_index=False)[["PA_QTDAPR", "PA_VALAPR"]]
        .sum()
    )
    return resumo, arquivo_dbf


def main():
    arquivos = listar_arquivos()
    print(f"{len(arquivos)} arquivos encontrados: {arquivos}")

    for nome in arquivos:
        saida = PASTA_PROCESSADOS / f"tomografias_{Path(nome).stem}.parquet"
        if saida.exists():
            print(f"{nome}: já processado, pulando.")
            continue

        print(f"{nome}:")
        arquivo_dbc = baixar(nome)
        resumo, arquivo_dbf = extrair_tomografias(arquivo_dbc)
        resumo.to_parquet(saida, index=False)
        print(f"  Salvo {saida} | {int(resumo['PA_QTDAPR'].sum()):,} exames")

        if APAGAR_BRUTOS:
            arquivo_dbc.unlink(missing_ok=True)
            arquivo_dbf.unlink(missing_ok=True)

    print("Extração concluída!")


if __name__ == "__main__":
    main()