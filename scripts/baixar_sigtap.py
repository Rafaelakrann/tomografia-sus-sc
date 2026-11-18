import io
import zipfile
from ftplib import FTP
from pathlib import Path

import pandas as pd

PASTA_BRUTOS = Path("dados/brutos/sigtap")
PASTA_PROCESSADOS = Path("dados/processados")
PASTA_BRUTOS.mkdir(parents=True, exist_ok=True)

# 1. Encontra a Tabela Unificada de dezembro de 2024 (ou a mais próxima)
ftp = FTP("ftp2.datasus.gov.br", timeout=120)
ftp.login()
ftp.cwd("/public/sistemas/tup/downloads")
arquivos = sorted(ftp.nlst("TabelaUnificada_2024*.zip"))
print("Arquivos de 2024 encontrados:", arquivos)

nome = [a for a in arquivos if "202412" in a][-1:] or arquivos[-1:]
nome = nome[0]
destino = PASTA_BRUTOS / nome
if not destino.exists():
    print(f"Baixando {nome}...")
    with open(destino, "wb") as arquivo:
        ftp.retrbinary(f"RETR {nome}", arquivo.write)
ftp.quit()

# 2. Lê o layout e a tabela de procedimentos de dentro do zip
with zipfile.ZipFile(destino) as zip_ref:
    layout_txt = zip_ref.read("tb_procedimento_layout.txt").decode("latin-1")
    dados_txt = zip_ref.read("tb_procedimento.txt").decode("latin-1")

print()
print("Layout:")
print(layout_txt)

linhas = [linha.replace(";", ",").split(",") for linha in layout_txt.strip().splitlines()[1:]]
nomes_colunas = [linha[0].strip() for linha in linhas]
posicoes = [(int(linha[2]) - 1, int(linha[3])) for linha in linhas]

proc = pd.read_fwf(io.StringIO(dados_txt), colspecs=posicoes, names=nomes_colunas, dtype=str)

# 3. Mantém só a tomografia (subgrupo 0206) e salva
tomo = proc[proc["CO_PROCEDIMENTO"].str.startswith("0206")][["CO_PROCEDIMENTO", "NO_PROCEDIMENTO"]]
tomo.to_csv(PASTA_PROCESSADOS / "procedimentos_tomografia.csv", index=False, encoding="utf-8-sig")
print(f"{len(tomo)} procedimentos de tomografia salvos")
print(tomo.to_string(index=False))